# eTran Benchmark Session Notes

## Ansible evaluation pipeline (must run after EVERY reboot)

Reboot resets: ARP table, /etc/hosts, NIC coalescing, flow control, queue count, IRQ affinity, MTU.

```bash
# All ansible-playbook commands run from Ansible/ directory:
cd Ansible

# Required after every reboot:
.venv/bin/ansible-playbook playbooks/eTran/evaluation/01-network-prep.yml
.venv/bin/ansible-playbook playbooks/eTran/evaluation/02-irq-affinity.yml
.venv/bin/ansible-playbook playbooks/eTran/evaluation/04-verify-network.yml

# Optional: MTU (default 1500, skip for standard runs)
# .venv/bin/ansible-playbook playbooks/eTran/evaluation/03-mtu.yml --extra-vars 'mtu=9000'
```

**IRQ affinity (02) details**: There are 2 mlx5 devices on these nodes
(`0000:07:00.0` and `0000:03:00.1`). The 02-irq-affinity.yml playbook uses
`grep mlx5_comp /proc/interrupts` which picks up IRQs from BOTH devices.
The sort-order may interleave them. Always verify the pinning targets the
correct PCI slot for `ens1f1np1` (`0000:03:00.1`). After running, check:
```bash
for irq in $(grep "mlx5_comp@pci:0000:03:00.1" /proc/interrupts | sed 's/^ *//' | cut -d: -f1 | sort -n | head -10); do
  echo -n "IRQ $irq -> "; cat /proc/irq/$irq/smp_affinity_list
done
```

## Critical procedure for running benchmarks

Every metric run follows this exact sequence:

```bash
# 1. Kill everything on all involved nodes
#    IMPORTANT: never use `pkill -f micro_kernel` -- it matches the
#    pkill command's own cmdline and self-terminates before signalling
#    the targets. Kill by PID via pgrep -x.
for n in node0 node1 node2 ...; do
  ssh $n "for p in \$(pgrep -x micro_kernel) \$(pgrep -x cp_node); do \
      sudo kill -9 \$p 2>/dev/null; done; \
    sudo ip link set dev ens1f1np1 xdp off 2>/dev/null"
done

# 2. Clean shared memory
for n in node0 node1 node2 ...; do
  ssh $n "sudo rm -f /dev/shm/BufferPool_* /dev/shm/UMEM_* /dev/shm/LRPC_*"
done

# 3. Start micro_kernel on all involved nodes with screen (no timeout)
#    Recommended (improves metrics 5/6 by 5-25%): pin mk to a dedicated
#    high core via `taskset -c 9`. NEVER pin to core 0 -- core 0 carries
#    extra IRQ/mlx5_comp housekeeping and breaks mk startup at high load.
for n in node0 node1 node2 ...; do
  ssh $n "sudo screen -dmS micro_kernel bash -c \
    'cd /local/eTran/eTran/micro_kernel && exec taskset -c 9 ./micro_kernel -i ens1f1np1 -q 10'"
done
sleep 5

# 4. Start server on node0 with screen (no timeout — stays alive for multiple runs)
#    Pin server threads to cores 0-7 (leaving core 9 for mk).
ssh node0 "sudo screen -dmS server bash -c \
  'cd /local/eTran/eTran/homa_app && exec env ETRAN_PROTO=homa taskset -c 0-7 ./cp_node server'"
sleep 3

# 5. Run clients with timeout (they exit when done)
for i in 1 2 3 ...; do
  timeout 30 ssh node$i "cd /local/eTran/eTran/homa_app && timeout 28 \
    env ETRAN_PROTO=homa ./cp_node client ... 2>&1" > /tmp/client_$i.out &
  sleep 0.3
done
wait

# 6. Collect results from saved client logs and server screen log
for i in 1 2 3 ...; do grep "Clients:" /tmp/client_$i.out | tail -1; done
ssh node0 "sudo screen -S server -X hardcopy /tmp/srv.log; \
  grep 'Servers:' /tmp/srv.log | tail -3"
```

### Key principles
- **micro_kernel** and **server** run in `screen` with NO timeout — they persist
  across runs. Only restart them if switching metrics or hitting stale state.
- **clients** always use `timeout N` — they're ephemeral.
- Use `env VAR=val` (NOT `timeout VAR=val command`) — timeout doesn't parse env prefixes.
- Start clients sequentially with 0.3s stagger to avoid overwhelming the server
  (especially for multi-client metrics like #3, #5).

### TCP benchmark differences
The procedure above is for **Homa** metrics (1-6, 22). TCP benchmarks (13-21)
use different binaries and env vars:
- **Server**: `epoll_server` (TCP throughput) or `flexkvs_server` (KV) — both in
  `tcp_app/`. Must set `ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=10` via `env`.
- **Client**: `epoll_client` or `flexkvs_bench` — in `tcp_app/`. Same env vars.
- **micro_kernel** is still required (libetran.so routes TCP via AF_XDP).
- Output is hidden over SSH (C stdout buffering) — prefix with `script -q -c`.
- epoll_* `-s` flag: default is `short_response=true` (server replies 100B). `-s`
  flips to echo the full request back. Counterintuitive — `-s` means "send full".

### Controlling screen sessions
```bash
# Check micro_kernel is up
ssh nodeN "sudo screen -ls micro_kernel; sudo pgrep -a micro_kernel"

# Collect server output without killing it
ssh node0 "sudo screen -S server -X hardcopy /tmp/srv.log; cat /tmp/srv.log"

# Kill when done
ssh nodeN "sudo screen -S micro_kernel -X quit; sudo pkill -9 micro_kernel"
ssh node0 "sudo screen -S server -X quit; sudo pkill -9 cp_node"
```

### Reading server stats from screen
The server's screen buffer may truncate old output. To get the latest lines:
```bash
ssh node0 "sudo screen -S server -X hardcopy /tmp/srv.log; \
  grep 'Servers:' /tmp/srv.log | tail -5"
```
The `hardcopy` command dumps the screen's scrollback buffer to a file.
If too old, the server has scrolled them out — check during/right after the run.

## BPF XDP_EGRESS patch (must be re-applied if source is re-cloned)
File: `micro_kernel/eBPF/homa/main.c` lines 235-248
Fix: Move `c->type != DATA` check before `data_header` bounds check,
     route non-DATA packets through `xmit_packet()` instead of dropping.
After patching: `touch micro_kernel/eBPF/homa/main.c && make -j$(nproc)`

## Correct metric invocations
- Metrics 1: NO `--one-way` (32B echo per paper §4.2)
- Metrics 2-4, 7-12, 22: YES `--one-way` (large messages need small response)
- Metrics 2: `--client-max 1 --ports 1` (single-stream back-to-back)
- Metric 3: server `--ports 4` (or 5/7/10 — crashing has stopped happening
  after the XDP_EGRESS patch; throughput is identical ~13 Gbps regardless of
  port count), clients `--ports 1 --client-max 1`. With mk pinned to core 9 +
  server pinned to cores 0-7, server-side reads ~13 Gbps. Bottleneck = Homa
  grant dispatch (per-CPU XDP_GEN state), so adding ports does NOT help.
- Metric 4: servers default ports, client `--ports 7 --client-max 1` (sweet spot for 10-core)
- Metric 1-2: 2 nodes only
- Metric 5: server `--ports 7` (32B safe from buffer-pool crash), clients
  `--ports 1 --client-max 64`; with mk on core 9, server threads on cores 0-7,
  peak ~1040 K / steady ~800 K (best).
- Metric 6: client `--ports 7 --client-max 128 --server-nodes 7` (best new sweet spot);
  mk pinned to core 9 on every node, servers pinned to cores 0-7. Steady ~820 K,
  client-side ~1099 K.
- Metrics 13-21: TCP benchmarks, use `script -q -c` over SSH for visible output
- Metric 15: stagger clients 0.5s apart to avoid overwhelming server
- Metrics 19-20: KV latency beats paper targets (14 vs 17.2 µs P50, 16 vs 27.5 µs P99)

## Known issues
- `--workload 1000000` stalls — use `999999` (HOMA_MAX_MESSAGE_LENGTH off-by-one)
- Server `--ports > 4` crashes buffer pool (`nr_slabs_avail` assertion) — only
  triggers under heavy traffic with Homa grants. `--ports 5/7/10` for 32B RPCs
  (no grants) works fine; verify before relying on this note.
- Multi-client (>200 concurrent RPCs) overwhelms BPF grant mechanism
- **TCP benchmarks now work** — the earlier SIGABRT was fixed by the BPF XDP_EGRESS
  patch (it affected TCP egress paths too, not just Homa grants). Metrics 13-15 and
  18-21 confirmed working.
- **SMT ON breaks eTran entirely** — AF_XDP busy-polling gets 0 completions
  regardless of queue count or IRQ pinning. Paper also notes SMT degrades AF_XDP.
  SMT=off (via `nosmt` in GRUB) is mandatory.
- `perf` breaks Homa AF_XDP but works fine for TCP benchmarks (Metric 21 completed
  with 50.7B cycles under perf). The microkernel's polling on separate threads is
  not disrupted by perf on the application thread.
- TCP connection drop after ~9s: "Connection is closed by microkernel" from
  `lib/socket.cc:405`. The microkernel closes TCP state after idle. Benchmark
  produces valid data before the drop. Use `timeout 15` for clean runs.
- epoll_* and flexkvs output is hidden over SSH (C stdout buffering). Use
  `script -q -c 'command' /dev/null` to force line-buffered output.
- All-to-all `--both` segfaults on exit (shared memory cleanup race)
- 10-core SMT=off limits throughput to ~50-60% of paper (paper had 20 cores)
- flexkvs_server hardcodes port 11211; flexkvs_bench `--time`/`--warmup`/`--cooldown`
  are stored but never enforced — always wrap in `timeout`.
- **Micro_kernel threading model**: `ps -L` shows only 3 mk threads (main,
  `control_loop` pinned to `CP_CPU=19` per `micro_kernel/runtime/defs.h`,
  `monitor`). The single `control_loop` busy-polls poll_network/poll_lrpc over
  ALL queues — there are NOT `-q`-many mk threads. With `nosmt`, cores 10-19
  are offline SMT siblings of 0-9, so mk's internal pin to CP_CPU=19 silently
  fails and the control_loop is left unconstrained (migrates across 0-9).
  Pinning mk via `taskset -c 9` externally restores dedicated-core polling and
  improves mid-size-RPC throughput (metrics 5/6) by 5-25%.
- **Stale XDP program after kill -9**: if micro_kernel is SIGKILLed in D-state
  (stuck on bpf_map_update_elem), the eTran BPF XDP program remains attached to
  the NIC (`ip link show ens1f1np1 | grep xdp` displays `prog/xdp id NNN`).
  The next `micro_kernel` launch will silently fail (XDP "already attached") and
  you'll see `Outstanding client RPCs: N` without completions. Always clean with
  `sudo ip link set dev ens1f1np1 xdp off` after kill.
- **`screen -wipe` may hang**: on at least one node (node7 in our session),
  `sudo screen -wipe` hangs after a crashed micro_kernel leaves a stale `.lock`
  file in `/run/screen/S-root`. Use `sudo screen -ls` / kill by PID instead;
  skip `screen -wipe` in orchestration scripts.
- **D-state stuck mk on a node requires reboot**: a micro_kernel stuck in
  BPF (`bpf_map_update_elem`, wchan in `/proc/<pid>/wchan`) cannot be exited
  by SIGKILL — the BPF syscall is uninterruptible. Stays as Z/D until reboot.
  If the affected node is critical (e.g., the lone client for metric 4), swap
  it with another clean node (e.g. node8 or node9) for that metric instead of
  rebooting the whole cluster.

## What NOT to do
- Never use `--queues` on cp_node client — kills throughput (e.g. 1045→86 Kops)
- Never use `-b` (busy-poll) on micro_kernel — breaks Homa benchmark
- Never double `umem_num_frames` — doesn't help, causes overhead
- Never skip shm cleanup between metrics — causes silent failures
- Never use `nohup ... </dev/null` for micro_kernel — monitor thread exits on stdin EOF.
  Use `screen -dmS` instead (provides a proper pty).
- Never use `timeout` on the server or micro_kernel — wrap them in `screen` instead.
- Never assume `grep mlx5_comp` targets the right PCI device — there are 2 mlx5 NICs.
  Always verify the PCI slot: `0000:03:00.1` for `ens1f1np1`.
- Never run epoll_* or flexkvs_bench without `timeout` — they loop forever.

## Multi-node orchestration
```bash
for i in 1 2 3 4 5 6 7; do
  timeout 30 ssh node$i "cd /local/eTran/eTran/homa_app && timeout 28 \
    env ETRAN_PROTO=homa ./cp_node client ... 2>&1" > /tmp/m_$i.out &
  sleep 0.3
done
wait
```

## Hardware
- CloudLab xl170, 10-core E5-2640v4 × 1 socket, Mellanox ConnectX-4 Lx 25G
- Paper used 2 sockets (20 cores) + ConnectX-4 25G on same node type
- NIC: `ens1f1np1` (PCI 0000:03:00.1), NUMA node 0
- Second mlx5 device at PCI 0000:07:00.0 (unused, but its IRQs appear in
  `/proc/interrupts` and confuse `grep mlx5_comp`)
- SMT=off: 10 logical cores, NIC has 10 combined queues → `-q 10`
- C-states=off (`intel_idle.max_cstate=0`), ASPM=off — required for sub-15µs latency metrics

## Ansible playbook structure
- `Ansible/playbooks/eTran/setup/` — one-time: system deps, kernel build, install eTran
- `Ansible/playbooks/eTran/tuning/` — one-time (persists reboot): SMT off, mitigations off, C-states off, ASPM off, tuned
- `Ansible/playbooks/eTran/evaluation/` — per-session (run after EVERY reboot): ARP, hosts, NIC tuning, IRQ affinity, MTU, verify

## Ansible inventory
- `@server` = node0, `@clients` = node1–node9
- **NOTE:** `profile.py` at repo root is stale (shows `node_count=4`). The actual
  deployment has 10 nodes (node0–node9), making Metrics 7–12 testable.
- Paper PDF: `nsdi25-chen-zhongjie.pdf` in repo root

## Key source files
- `common/xskbp/xsk_buffer_pool.h` — buffer pool constants (umem_num_frames, buffers_per_slab)
- `micro_kernel/eBPF/homa/main.c:240` — XDP_EGRESS grant drop bug
- `common/tran_def/homa.h:8` — HOMA_MAX_MESSAGE_LENGTH = 1000000
- `micro_kernel/micro_kernel.cc:51` — default queues = 20
- `homa_app/cp_node.cc:1616` — default workload = "100"
- `tcp_app/epoll_client.cc` — TCP throughput client; `-s` toggles response mode (default short 100B)
- `tcp_app/epoll_server.cc` — TCP throughput server; `-s` toggles response mode
- `tcp_app/flexkvs_server.cc` — KV server, 3 positional args (CONFIG THREADS QUEUES), port 11211 hardcoded
- `tcp_app/flexkvs_bench.cc` — KV benchmark client; `--time`/`--warmup`/`--cooldown` stored but not enforced
- `lib/socket.cc:405` — TCP "Connection is closed by microkernel" idle-drop message
- `lib/eTran_common.cc` — `pre_main` constructor reads `ETRAN_PROTO` (required), `ETRAN_NR_APP_THREADS` + `ETRAN_NR_NIC_QUEUES` (required for TCP)
- `shared_lib/` — `libetran.so` built via `interpose.cc`; LD_PRELOAD intercepts socket/epoll/read/write
