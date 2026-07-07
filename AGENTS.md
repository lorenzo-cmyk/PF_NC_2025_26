# eTran Benchmark Session Notes

## Ansible evaluation pipeline (must run after EVERY reboot)

Reboot resets: ARP table, /etc/hosts, NIC coalescing, flow control, queue count, MTU.

```bash
# All ansible-playbook commands run from Ansible/ directory:
cd Ansible

# Required after every reboot:
.venv/bin/ansible-playbook playbooks/eTran/evaluation/01-network-prep.yml
.venv/bin/ansible-playbook playbooks/eTran/evaluation/04-verify-network.yml

# Optional: MTU (default 1500, skip for standard runs)
# .venv/bin/ansible-playbook playbooks/eTran/evaluation/03-mtu.yml --extra-vars 'mtu=9000'
```

## Critical procedure for running benchmarks

Every metric run follows this exact sequence:

```bash
# 1. Kill everything on all involved nodes
#    IMPORTANT: never use `pkill -f micro_kernel` -- with `-f` it matches
#    on the full command line, so it also hits the `screen` wrapper whose
#    argv contains "micro_kernel" (and historically self-terminated if the
#    pkill cmdline happened to contain the substring). Use `pgrep -x` to
#    match on the process name only.
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
#    NO taskset — CP_CPU=19 (defs.h:26) pins the control_loop to core 19
#    (the HT sibling of core 9) automatically. This only works with HT ON
#    (the intended design).
#    Default 20 queues matches NIC combined=20 (use `ethtool -l ens1f1np1` to check).
for n in node0 node1 node2 ...; do
  ssh $n "sudo screen -dmS micro_kernel bash -c \
    'cd /local/eTran/eTran/micro_kernel && exec ./micro_kernel -i ens1f1np1'"
done
sleep 5

# 4. Start server on node0 with screen (no timeout — stays alive for multiple runs)
#    Optionally pin app threads to physical cores 0-9 with taskset.
ssh node0 "sudo screen -dmS server bash -c \
  'cd /local/eTran/eTran/homa_app && exec env ETRAN_PROTO=homa ./cp_node server'"
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
  `tcp_app/`. Must set `ETRAN_NR_APP_THREADS=N ETRAN_NR_NIC_QUEUES=N` via `env`
  (N = number of app threads, both must match).
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
- Metric 3: server `--ports 4` (or 5/7 — verified equivalent at ~12.8 Gbps;
  10 is WORSE at 8 Gbps because the 1-thread client can only fill 7 of 10
  server ports). 500KB Homa grants at `--ports 5/7/10` do **NOT** crash the
  buffer pool with the BPF XDP_EGRESS patch applied (verified clean 2026-07-06).
  The earlier "max 4 ports" caveat is **stale** — the BPF patch fixed it.
  Clients `--ports 1 --client-max 1`. CP_CPU=19 internally pins mk
  to core 19 (HT sibling of core 9). Bottleneck = Homa grant dispatch
  (per-CPU XDP_GEN state), so adding server ports does NOT help.
- Metric 4: servers default ports, client `--ports 7 --client-max 1` (sweet spot for 10-core)
- Metric 1-2: 2 nodes only
- Metric 5: server `--ports 7`, clients `--ports 1 --client-max 64`; no taskset
  (CP_CPU=19 works with HT-on). Server steady ~927 Kops.
- Metric 6: client `--ports 7 --client-max 256 --server-nodes 7` (best new sweet spot;
  measured 2026-07-06 with default 20 queues); no taskset (CP_CPU=19 works).
  Client steady ~1120 Kops, servers ~160 Kops each.
- Metrics 7-12 (W2-W5 all-to-all): `--both 2 --id N` on all 10 nodes.
  Requires `micro_kernel` restart between each workload (4 total).
  Results (2026-07-06): W2 P50=109 µs P99=1344 µs (even load ~430 Kops/node);
  W3 P50=115 µs P99=1428 µs; W4 shortest-10% P50=2848 µs; W5 shortest-10% P50=14530 µs.
  Linux-Homa baseline postponed. `--server-ports 4` (operational, matches the
  metric 3 invocation — not a hard cap; could try 5/7, see metric 3 notes).
- Metrics 13-21: TCP benchmarks, use `script -q -c` over SSH for visible output
- Metric 15: stagger clients 0.5s apart to avoid overwhelming server
- Metrics 19-20: KV latency beats paper targets (14 vs 17.2 µs P50, 16 vs 27.5 µs P99)

## Known issues
- `--workload 1000000` stalls — use `999999` (HOMA_MAX_MESSAGE_LENGTH off-by-one)
- Server `--ports > 4` with 500KB Homa grants: **no longer crashes** with the BPF
  XDP_EGRESS patch applied (verified 2026-07-06: server `--ports 5/7/10` all run
  cleanly at ~12.8 Gbps for 32s, no asserts, no dmesg errors). The earlier
  "max 4 ports" claim was stale. The crash may still trigger on a fresh eTran
  clone without the patch — re-apply `micro_kernel/eBPF/homa/main.c:235-248`
  before trusting this note.
- Multi-client (>200 concurrent RPCs) overwhelms BPF grant mechanism
- **TCP benchmarks now work** — the earlier SIGABRT was fixed by the BPF XDP_EGRESS
  patch (it affected TCP egress paths too, not just Homa grants). Metrics 13-15 and
  18-21 confirmed working.
- **SMT ON works fine** — the earlier "SMT ON breaks eTran entirely" claim was
  false. With HT-on, eTran runs correctly: metric 1 (12.59 µs P50),
  metric 2 (16.6 Gbps), and metric 5 (~927 Kops server steady) all produce valid results.
  HT-on gives a ~8% improvement in metric 5 vs the old taskset-c9 workaround.
  IRQ pinning was tested (metric 5) and shown to have no effect — the playbook
  and all IRQ references have been removed from the repo.
- **CP_CPU=19 internal pin now works** — with HT enabled, core 19 (SMT sibling
  of core 9) is online. The `pthread_setaffinity_np` at `control_plane.cc:1155`
  succeeds for the first time, pinning the mk control_loop to its intended core.
  NO external `taskset` is needed. This matches the paper's design (§6: "dedicated
  core for control path/slow path").
- `perf` breaks Homa AF_XDP but works fine for TCP benchmarks (Metric 21 completed
  with 63.8B cycles under perf). The application thread's own AF_XDP busy-poll
  is what `perf` sampling interrupts stall; mk's slow-path control_loop is
  unaffected and is not the relevant target of perf interference.
- TCP connection drop after ~9s: "Connection is closed by microkernel" from
  `lib/socket.cc:405`. The microkernel closes TCP state after idle. Benchmark
  produces valid data before the drop. Use `timeout 15` for clean runs.
- epoll_* and flexkvs output is hidden over SSH (C stdout buffering). Use
  `script -q -c 'command' /dev/null` to force line-buffered output.
  **Env vars must be inside the `-c` argument** — `env VAR=val script -q -c 'cmd'`
  does NOT pass env vars into the subshell. Use: `script -q -c 'VAR=val ./cmd' /dev/null`.
- All-to-all `--both` segfaults on exit (shared memory cleanup race)
- Per-node variance in W2-W5: `--both 2` timing creates wall-clock misalignment
  between nodes. W2 even (9/10 nodes at ~430 Kops), W3-W5 show 10-100x variance.
  Pre-starting servers then launching clients simultaneously may improve consistency.
- `dump_times` output includes comment header lines (`# --server-nodes ...`).
  Always filter with `grep -v '^#'` before processing RTT data.
- Throughput gap vs paper (metrics 3/5/6 at 25-56%) is NOT a core-count
  deficit — paper used identical CloudLab xl170 single-socket 10-core nodes.
  And it is NOT a microkernel dispatch bottleneck: **the Homa data path is
  fastpath** — the `xdp_sock` BPF calls `bpf_redirect_map(&xsks_map, ...)` to
  push DATA packets directly into the application's AF_XDP socket
  (`micro_kernel/eBPF/homa/main.c`), and the app thread polls its XSK rings +
  TXes via `kick_tx` (`lib/eTran_rpc.cc`). Homa grants are generated at the NIC
  by the `xdp_gen` BPF (`XDP_TX` in `eBPF/homa/main.c:192`). The microkernel
  handles only slow-path: Homa bind/close (`process_homa_cmd` in `homa.cc:790`
  handles ONLY `APPOUT_HOMA_BIND`/`APPOUT_HOMA_CLOSE`) and the 1ms timeout
  scan `poll_homa_to`. TCP data is also fastpath-via-XSKMAP
  (`eBPF/tcp/main.c:258,367,378`); mk only owns TCP handshake/control.
  Real Homa bottlenecks to investigate: XDP_GEN grant eBPF serialization,
  per-app-thread polling rate, BPF RPC-map contention between the app
  fastpath and mk's 1ms `poll_homa_to` batch scan. IRQ pinning was tested
  (metric 5) and showed no effect. Server `--ports 4/5/7` all hit the same
  ~13 Gbps ceiling (verified 2026-07-06 — server parallelism is NOT the cap).
- flexkvs_server hardcodes port 11211; flexkvs_bench `--time`/`--warmup`/`--cooldown`
  are stored but never enforced — always wrap in `timeout`.
- **Micro_kernel threading model**: `ps -L` shows only 3 mk threads (main,
  `control_loop` pinned to `CP_CPU=19` per `micro_kernel/runtime/defs.h`,
  `monitor`). With `nosmt`, cores 10-19 are offline SMT siblings of 0-9, so
  mk's internal pin to CP_CPU=19 silently fails (the `pthread_setaffinity_np`
  return value is NOT checked — `control_plane.cc:1155`) and the control_loop
  is left unconstrained (migrates across 0-9). The control_loop sequentially
  calls poll_uds → poll_lrpc → poll_network → poll_tcp_handshake_events →
  poll_tcp_cc_to → poll_homa_to then `clock_nanosleep`s up to TICK_US (1ms).
  These poll_* functions are SLOW-PATH ONLY — mk never touches Homa data
  packets and never redirects TCP data either (data is XSKMAP-redirected by
  the eBPF to the app). With **HT enabled** (current config), CP_CPU=19
  (SMT sibling of core 9) is online and the internal pin succeeds.
  NO external `taskset` is needed. HT-on gives ~8% improvement in metric 5
  vs the old `taskset -c 9` workaround.
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
- NEVER commit unless explicitly told to. Even if changes look correct — only commit when the user says "commit" or "push".
- Never use `--queues` on cp_node client — kills throughput (e.g. 927→86 Kops)
- Never use `-b` (busy-poll) on micro_kernel — breaks Homa benchmark
- Never double `umem_num_frames` — doesn't help, causes overhead
- Never skip shm cleanup between metrics — causes silent failures
- Never use `nohup ... </dev/null` for micro_kernel — monitor thread exits on stdin EOF.
  Use `screen -dmS` instead (provides a proper pty).
- Never use `timeout` on the server or micro_kernel — wrap them in `screen` instead.
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
- Paper used the SAME xl170 nodes (single-socket 10-core E5-2640v4, ConnectX-4
  25G). The paper's §6 phrase "two 10-core Intel E5-2640v4 CPUs" is a
  typo (per the authors) — the CloudLab xl170 has a single 10-core CPU per
  node. Confirmed via `lscpu` on node0: `Socket(s): 1, Core(s) per socket: 10`.
  No core-count excuse for the throughput gap; treat gaps as real bugs to investigate.
- NIC: `ens1f1np1` (PCI 0000:03:00.1), NUMA node 0
- SMT=on (HT enabled, removed `nosmt` from GRUB): 20 logical CPUs online
  (cores 0-9 physical, 10-19 HT siblings). NIC has 20 combined queues.
  mk's `CP_CPU=19` (SMT sibling of core 9) is online and the internal
  `pthread_setaffinity_np` succeeds. This matches the paper's design (§6).
- C-states=off (`intel_idle.max_cstate=0`), ASPM=off — required for sub-15µs latency metrics
- CPU governor=`performance` (via tuned `network-throughput` profile).
  irqbalance systemd-disabled, `cpupower idle-set -D 1` (covered by
  `intel_idle.max_cstate=0` in GRUB).
  Reference: cloudlab_env_setup `configure_for_exp`.
- The full CloudLab `configure_for_exp` recipe was applied item-by-item and
  measured against metrics 1/3/5. Most items (eBPF stats off, KSM off, NUMA
  balancing off, LRO off) had **no measurable effect**. **Turbo off
  (`no_turbo=1`) and GRO/TSO off are NOT applied** — they cause a 39%
  regression on metric 5 (927 → 568 Kops) because Homa's per-RPC CPU
  processing is the bottleneck, not the link. The earlier
  `tuning/05-runtime-tuning.yml` playbook that applied these was
  **removed** — see the runbook section
  "System Tuning — What We Tried, What Actually Matters" for the full
  table and rationale, and **do not waste time re-adding it**.

## Ansible playbook structure
- `Ansible/playbooks/eTran/setup/` — one-time: system deps, kernel build, install eTran
- `Ansible/playbooks/eTran/tuning/` — one-time (persists reboot): mitigations off, C-states off, ASPM off, tuned
  (SMT is now ON — `nosmt` removed; playbook renamed `02-tune-boot-params.yml`).
  Note: a `05-runtime-tuning.yml` was tried and removed; see the
  "System Tuning" section in the runbook.
- `Ansible/playbooks/eTran/evaluation/` — per-session (run after EVERY reboot): ARP, hosts, NIC tuning, MTU, verify

## Ansible inventory
- `@server` = node0, `@clients` = node1–node9
- **NOTE:** `profile.py` now has `node_count=10` (was 4). Update for fresh
  CloudLab allocations if node count changes.
- Paper PDF: `nsdi25-chen-zhongjie.pdf` in repo root

## Key source files
> Paths relative to the eTran repo root (`https://github.com/eTran-NSDI25/eTran`).
> Line numbers verified against the source clone on 2026-07-06 (re-verified 2026-07-06 against current checkout; some eBPF/control-plane drifts noted in commit history).

### Fastpath (where data packets actually flow — bypasses microkernel)
- `micro_kernel/eBPF/entrance/entrance.c` — L48 `SEC("xdp_sock")`: parses eth/IP, tail-calls into Homa (`bpf_tail_call` at L74) / TCP (L71) transport programs; L82 `xdp_gen`, L93 `xdp_egress` dispatch by umem_id
- `micro_kernel/eBPF/homa/main.c` — L293 `SEC("xdp_sock")`: L418,451,460,588 `bpf_redirect_map(&xsks_map, socket_id, XDP_DROP)` pushes Homa DATA packets directly into the app's AF_XDP socket (does NOT go through microkernel)
- `micro_kernel/eBPF/homa/main.c` — L29 `SEC("xdp_gen")` emits grants at NIC (`L192 return XDP_TX`); per-CPU state L59 `granting_idx[cpu]++`, L78 `min(nr_grant_candidate[cpu], HOMA_OVERCOMMITMENT)` (HOMA_OVERCOMMITMENT=8). 8-step grant choose via tail-calls: SEC at L595,1247,1344,1440,1536,1632,1728,1824,1920 (`xdp_gen/{choose_rpc_to_grant,complete_grant_[1-8]}`); tail-call invocation sites at L1240,1338,1435,1531,1627,1723,1819,1915
- `micro_kernel/eBPF/homa/main.c:235-248` — **XDP_EGRESS grant drop bug** (order-of-checks bug — apply patch: move `c->type != DATA` check before `data_header` bounds check, route non-DATA through `xmit_packet()`)
- `micro_kernel/eBPF/tcp/main.c:258,367,378` — `bpf_redirect_map(&xsks_map, ...)` for TCP DATA; L373 `slow_path_map` lookup (the only path that reaches mk for handshake/control)
- `lib/eTran_rpc.cc:288,426` — `poll_nic_rx()` / `poll_nic_rx_block(timeout)`: the **app's** RX fastpath. L323,463 `xsk_ring_cons__peek` on each queue's RX ring; L370,505 `client_response` / L372,507 `server_request` (DATA consumed here, in user space)
- `lib/eTran_rpc.cc:187,203,717,795` — app TX fastpath: `xsk_ring_prod__reserve(&xsk_info->tx, ...)` + `kick_tx(...)`
- `lib/eTran_posix.cc:1168,1228` — `process_homa_kernel_events` / `eTran_homa_poll_events`: drains mk's slow-path LRPC responses (`APPIN_HOMA_STATUS_BIND`/`CLOSE`)
- `lib/xsk_if.cc` — per-thread XSK setup (`XDP_TX_RING` setsockopt at L38, ring mmap at L68)

### Microkernel slow-path (only bind/close/timers/handshake — NOT data dispatch)
- `micro_kernel/micro_kernel.cc:51` — `opt_num_queues=20` default
- `micro_kernel/micro_kernel.cc:244,259` — `thread_init()` / `wait_thread()`
- `micro_kernel/runtime/defs.h:26` — **`CP_CPU = 19`** (online with HT enabled; the control_loop pins to SMT sibling of core 9)
- `micro_kernel/control_plane.cc:48` — `TICK_US=1000` (1ms slow-path cadence)
- `micro_kernel/control_plane.cc:1070` — `control_loop()` (the single worker thread; L1095-1130 sequential `poll_uds`→`poll_lrpc`→`poll_network`→`poll_tcp_handshake_events`→`poll_tcp_cc_to`→`poll_homa_to` + `clock_nanosleep`)
- `micro_kernel/control_plane.cc:1137` — `thread_init()`; L1148 single `pthread_create(&micro_kernel_thread, control_loop)`; L1153-1155 `CPU_SET(CP_CPU)` + `pthread_setaffinity_np` (return value NOT checked)
- `micro_kernel/control_plane.cc:1406` — `process_packet` — **TCP-only**; L1444 calls `tcp_packet`. (No Homa branch — Homa never reaches here)
- `micro_kernel/homa.cc:790` — `process_homa_cmd` — handles ONLY `APPOUT_HOMA_BIND` (L796) / `APPOUT_HOMA_CLOSE` (L803)
- `micro_kernel/homa.cc:485` — `poll_homa_to` (1ms batch scan of the BPF RPC map for zombies/retransmits; L502 `bpf_map_lookup_batch`)

### Buffer pool / constants
- `common/xskbp/xsk_buffer_pool.h:33` — `umem_num_frames=64*XSK_RING_PROD__DEFAULT_NUM_DESCS`; L39 `buffers_per_slab=2*XSK_RING_PROD__DEFAULT_NUM_DESCS`; L70/L73 `nr_slabs` / `nr_slabs_avail` (slab counters — the `--ports > 4` crash hypothesis is **refuted 2026-07-06** with the BPF XDP_EGRESS patch; server runs cleanly at 5/7/10 ports)
- `common/tran_def/homa.h:8` — `HOMA_MAX_MESSAGE_LENGTH = 1000000` (off-by-one: `--workload 1000000` stalls, use `999999`)
- `common/tran_def/homa.h:11` — `enum homa_packet_type` (DATA/GRANT/RESEND/...)

### Benchmark binaries
- `homa_app/cp_node.cc` — L54 `IF_NAME`="ens1f1np1"; L1426 `server_stats`, L1476 `client_stats`; L1616 default `workload = "100"`; L1603 `client_cmd`, L1929 `server_cmd`
- `homa_app/dist.cc` — `w1`-`w5` CDF arrays; `dist_lookup()` handles `int`→fixed-size or `wN`
- `tcp_app/epoll_client.cc` — TCP throughput client; `-b`(msg) `-i` `-f`(flows) `-t`(threads) `-o`(outstanding) `-w`(wait) `-l`(max_buf) `-s`(response toggle; **note** `-s` means "send full echo", default is short 100B — counterintuitive)
- `tcp_app/epoll_server.cc` — TCP throughput server; same `-s` semantics
- `tcp_app/flexkvs_server.cc` — KV server, 3 positional args: `CONFIG THREADS QUEUES`, port 11211 hardcoded
- `tcp_app/flexkvs_bench.cc` — KV benchmark client; `--time`/`--warmup`/`--cooldown` stored but never enforced (always wrap in `timeout`)
- `lib/socket.cc:405` — TCP "Connection is closed by microkernel" idle-drop message (after ~9s)
- `lib/eTran_common.cc:595` — `pre_main` constructor: reads `ETRAN_PROTO` (L600, required), `ETRAN_NR_APP_THREADS` (L598) + `ETRAN_NR_NIC_QUEUES` (L599, required for TCP only)
- `shared_lib/interpose.cc` — builds `libetran.so`; LD_PRELOAD intercepts `socket`/`epoll_wait`/`read`/`write`
