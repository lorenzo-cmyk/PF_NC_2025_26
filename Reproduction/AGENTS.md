# Benchmark Cluster Operations

Cluster-wide setup, orchestration, and pitfalls for the three benchmark
stacks on the same CloudLab cluster:

- eTran: AF_XDP + eBPF transports (Homa + TCP), micro_kernel + libetran.so
- Linux-Homa: Homa kernel module (PlatformLab/HomaModule)
- DCTCP: standard Linux TCP with tcp_dctcp + ECN (baseline)

Exact per-metric commands live in the runbooks:
`Reproduction/Runbook/eTran_Runbook.md`, `Reproduction/Runbook/Homa_Runbook.md`,
`Reproduction/Runbook/DCTCP_Runbook.md`.

Hardware: CloudLab xl170, single-socket 10-core E5-2640v4, Mellanox
ConnectX-4 Lx 25G, SMT on (20 logical CPUs), NIC `ens1f1np1`.

## Ansible

All playbooks live in `Reproduction/Ansible`. Run every command from that
directory with the project venv:

```bash
cd Reproduction/Ansible
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # once
export CLOUDLAB_USER=<your CloudLab username>                          # each shell
```

Inventory (`inventory/hosts.yml`): `@server` = node0, `@clients` =
node1-node9. SSH key: `~/.ssh/SSH_Key_Cloudlab`. `profile.py`:
`node_count=10` (update if the cluster size changes).

### Pipelines

| Stack | Command (from Reproduction/Ansible)                              | When                                                                              |
| ----- | ---------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| eTran | `.venv/bin/ansible-playbook playbooks/eTran/setup/site.yml`      | one-time: system deps, kernel build, install eTran                                |
| eTran | `.venv/bin/ansible-playbook playbooks/eTran/tuning/site.yml`     | one-time, persists reboot: mitigations off, C-states off, ASPM off, tuned, SMT on |
| eTran | `.venv/bin/ansible-playbook playbooks/eTran/evaluation/site.yml` | after EVERY reboot                                                                |
| Homa  | `.venv/bin/ansible-playbook playbooks/Homa/setup/site.yml`       | one-time: kernel build, install Homa module                                       |
| Homa  | `.venv/bin/ansible-playbook playbooks/Homa/tuning/site.yml`      | one-time                                                                          |
| DCTCP | `.venv/bin/ansible-playbook playbooks/DCTCP/setup/site.yml`      | one-time: clone HomaModule, compile cp_node, tcp_dctcp + ECN                      |

### After every reboot

A reboot resets: ARP table, `/etc/hosts`, NIC coalescing, flow control,
queue count, MTU (and, for Linux-Homa runs, the `homa` qdisc and
`net.homa.*` sysctls).

```bash
cd Reproduction/Ansible
.venv/bin/ansible-playbook playbooks/eTran/evaluation/01-network-prep.yml
.venv/bin/ansible-playbook playbooks/eTran/evaluation/03-verify-network.yml
# For Linux-Homa runs, also re-apply the Homa-specific steps (homa qdisc,
# net.homa.max_gso_size/hijack_tcp, governor):
.venv/bin/ansible-playbook playbooks/Homa/evaluation/01-network-prep.yml
```

Keep MTU at 1500 - the ToR switch does not support jumbo frames, so do
NOT set `mtu=9000` (skip the 02-mtu.yml playbook; its default is a no-op).

## Pre-flight

- DCTCP active on all nodes (for DCTCP runs): `net.ipv4.tcp_congestion_control
  = dctcp`, `net.ipv4.tcp_ecn = 1` (check with `sysctl`).
- Binaries present:
  - eTran: `/local/eTran/eTran/homa_app/cp_node`, and
    `/local/eTran/eTran/tcp_app/{epoll_server,epoll_client,flexkvs_server,flexkvs_bench}`
  - Homa/DCTCP: `/local/HomaModule/util/cp_node`
- Hostname resolution: cp_node resolves `node0..node9` via `getaddrinfo()`
  (`/etc/hosts` is set by 01-network-prep).
- Interface: `ens1f1np1` is hardcoded in `cp_node.cc`, `micro_kernel.cc`
  (default), and the process-proxy xdpsock
  (`process-proxy/{non_priviledged,priviledged}_process.c`) - recompile
  if your NIC differs. (`bench-afxdp/xdpsock.c` takes `-i` instead.)

## Benchmark procedure (generic)

The orchestration is the same for every metric; the exact server/client
commands come from the per-metric runbooks:

```bash
# 1. Kill stale processes on all involved nodes.
#    Use `pgrep -x` + kill by PID. NEVER `pkill -f micro_kernel` - with -f
#    it matches its own cmdline AND the screen wrapper (whose argv contains
#    "micro_kernel"), self-terminating before reaching the target.
for n in node0 node1 ...; do
  ssh $n "for p in \$(pgrep -x micro_kernel) \$(pgrep -x cp_node) \
      \$(pgrep -x epoll_server) \$(pgrep -x epoll_client); do \
      sudo kill -9 \$p 2>/dev/null; done; \
    sudo ip link set dev ens1f1np1 xdp off 2>/dev/null"
done

# 2. Clean shared memory (eTran only; mandatory between metrics).
for n in node0 node1 ...; do
  ssh $n "sudo rm -f /dev/shm/BufferPool_* /dev/shm/UMEM_* /dev/shm/LRPC_*"
done

# 3. Start micro_kernel (eTran only) in screen - no timeout, no taskset, no -b.
#    Default 20 queues matches NIC combined=20. CP_CPU=19 (defs.h:26) pins the
#    control_loop to core 19 (HT sibling of core 9) with SMT on.
for n in node0 node1 ...; do
  ssh $n "sudo screen -dmS micro_kernel bash -c \
    'cd /local/eTran/eTran/micro_kernel && exec ./micro_kernel -i ens1f1np1'"
done
sleep 5

# 4. Start the server in screen (persists across runs; no timeout).
ssh node0 "sudo screen -dmS server bash -c 'cd <app_dir> && exec <server_cmd>'"
sleep 3

# 5. Run clients with timeout (they exit when done), staggered 0.3s.
for i in 1 2 3 ...; do
  timeout 30 ssh node$i "cd <app_dir> && timeout 28 <client_cmd> 2>&1" \
    > /tmp/client_$i.out &
  sleep 0.3
done
wait

# 6. Collect results.
for i in 1 2 3 ...; do grep "Clients:" /tmp/client_$i.out | tail -1; done
ssh node0 "sudo screen -S server -X hardcopy /tmp/srv.log; \
  grep 'Servers:' /tmp/srv.log | tail -3"
```

- Restart micro_kernel + clean shm between metrics/workloads - stale BPF
  state causes silent stalls (0 completions).
- Full all-to-all runs (W2-W5) use `--both N --id N` on every node (eTran)
  or pre-started servers + piped stdin (kernel Homa) - see the runbooks.

## Per-stack specifics

| Stack      | Binaries                         | Server                                                                                                                     | Client                                          |
| ---------- | -------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| eTran Homa | `homa_app/cp_node`               | `env ETRAN_PROTO=homa ./cp_node server [--ports N]`                                                                        | `env ETRAN_PROTO=homa ./cp_node client <flags>` |
| eTran TCP  | `tcp_app/epoll_*`, `flexkvs_*`   | `env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=N ETRAN_NR_NIC_QUEUES=N LD_PRELOAD=../shared_lib/libetran.so ./epoll_server ...` | same env vars + LD_PRELOAD                      |
| Linux-Homa | `/local/HomaModule/util/cp_node` | `./cp_node server [--ports N]` (no env vars)                                                                               | `./cp_node client <flags>` (no env vars)        |
| DCTCP      | `/local/HomaModule/util/cp_node` | `./cp_node server --protocol tcp [--ports N]`                                                                              | `./cp_node client --protocol tcp <flags>`       |

Notes:
- eTran TCP: `ETRAN_NR_APP_THREADS` must equal the app thread count, and
  `ETRAN_NR_NIC_QUEUES` must match it. `flexkvs_server` hardcodes port 11211.
- `flexkvs_bench` `--time/--warmup/--cooldown` are stored but never enforced;
  `epoll_*` run forever - always wrap clients in `timeout`.
- Output is hidden over SSH (C stdout buffering): use
  `script -q -c 'VAR=val ./cmd' /dev/null` (env vars MUST be inside the
  `-c` argument - `env VAR=val script -q -c 'cmd'` does not pass them into
  the subshell) or `stdbuf -oL`.
- epoll `-s` flag: default `short_response=true` (server replies 100B);
  `-s` flips to echo the full request. Counterintuitive.

## Screen session management

```bash
# check micro_kernel is up
ssh nodeN "sudo screen -ls micro_kernel; sudo pgrep -a micro_kernel"

# collect server output without killing it
ssh node0 "sudo screen -S server -X hardcopy /tmp/srv.log; cat /tmp/srv.log"

# latest stats lines (scrollback may have truncated old output)
ssh node0 "sudo screen -S server -X hardcopy /tmp/srv.log; \
  grep 'Servers:' /tmp/srv.log | tail -5"

# kill when done
ssh nodeN "sudo screen -S micro_kernel -X quit; sudo pkill -9 micro_kernel"
ssh node0 "sudo screen -S server -X quit; sudo pkill -9 cp_node"

# after a SIGKILLed micro_kernel, detach the stale XDP program, or the next
# micro_kernel launch silently fails (XDP already attached)
sudo ip link set dev ens1f1np1 xdp off
```

## BPF XDP_EGRESS patch

Not worth the effort - skip it. The XDP_EGRESS patch
(`micro_kernel/eBPF/homa/main.c` lines 235-248) is mostly a waste of time
for current runs; do not re-apply it even if the eTran source is re-cloned.

## Anti-patterns

- `pkill -f micro_kernel` -> self-kills; use `pgrep -x` + `kill -9`.
- `nohup ... </dev/null` for micro_kernel -> monitor thread exits on stdin
  EOF; use `screen -dmS` (provides a pty).
- `timeout` on micro_kernel or the server -> wrap them in `screen`; only
  clients get `timeout`.
- `screen -wipe` -> hangs on stale `.lock` files; use `screen -ls` / kill
  by PID.
- Skipping shm cleanup between eTran metrics -> silent BPF stalls.
- `-b` (busy-poll) on micro_kernel -> breaks Homa benchmarks.
- `--queues N` on cp_node client -> kills throughput ~12x; never pass it
  (measured values: Report/Measurements/Tuning_History.md, "What hurts").
- Doubling `umem_num_frames` -> no help, extra overhead.
- GRO/TSO off or Intel Turbo off -> ~39% regression on metric 5; keep them on
  (measured values: Report/Measurements/Tuning_History.md, "What hurts").
- `taskset` on micro_kernel or app threads -> not needed; `CP_CPU=19`
  internal pin works with SMT on (app-thread taskset has no measurable effect).
- A micro_kernel stuck in D-state (uninterruptible BPF syscall, e.g.
  `bpf_map_update_elem`) cannot be killed even with SIGKILL; swap the node
  or reboot.
- `--workload 1000000` stalls (HOMA_MAX_MESSAGE_LENGTH off-by-one); use
  `999999` (already baked into the runbooks).
