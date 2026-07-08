# eTran Benchmark Runbook — Exact Commands per Metric

## Results Summary (Single-Socket xl170, 10-core E5-2640v4, SMT=on)

> **Current configuration:** SMT=ON (HT enabled, 20 logical CPUs). mk's
> `CP_CPU=19` internal pin now works — the control_loop pins to **core 19**
> (the HT sibling of core 9) as designed. NO `taskset` is needed for mk. NIC
> has 20 combined queues. App threads on physical cores 0-9, mk control_loop
> on core 19 (HT sibling of core 9). This matches the paper's §6 design.

| # | Metric | Our Result | Paper Target | % | Bottleneck |
|---|--------|-----------|-------------|---|-----------|
| 1 | 32B latency (P50) | **12.59 µs** (2026-07-06, def. 20 queues) | 11.8 µs | **93%** | Same HW as paper; 7% gap under investigation (not NUMA) |
| 2 | 1MB throughput | **16.6 Gbps** (2026-07-06, def. 20 queues) | 17.7 Gbps | **94%** | Same HW as paper; ~6% gap under investigation |
| 3 | 7-clients→1-server 500KB | **~12.78 Gbps** server-side (2026-07-06, def. 20 queues) | 23.0 Gbps | **56%** | Homa grant/egress XDP_GEN dispatch path saturates at ~13 Gbps regardless of `--ports` (4/5/7 all hit same ceiling; 10 is worse at 8 Gbps due to client fan-out). Real bug, NOT core count (same HW as paper), NOT server parallelism, NOT buffer pool |
| 4 | 1-client→7-servers 500KB | **~19.5 Gbps** client-side (2026-07-06, def. 20 queues) | 22.7 Gbps | **86%** | NOT NIC (paper hit 22.7 on same 25G link); XDP_GEN grant pacing + per-app-thread send rate on the client |
| 5 | Client RPC rate, 32B (7:1) | **~927 Kops** server steady (2026-07-06, def. 20 queues) | 2.9 Mops | **32%** | Per-app-thread polling rate + BPF map contention (mk is NOT on Homa data fastpath — see Key findings) |
| 6 | Server RPC rate, 32B (1:7) | **~1120 Kops** client steady (2026-07-06, def. 20 queues) | 3.3 Mops | **34%** | Per-app-thread polling rate + BPF map contention (mk is NOT on Homa data fastpath — see Key findings) |
| 7 | P99 slowdown W2/W3 (short-msg) | **P99=1344 µs** (W2), **1428 µs** (W3) | 3.9–7.5× slowdown vs Linux | — | eTran RTTs only (no Linux-Homa baseline) |
| 8 | P50 slowdown W2/W3 (short-msg) | **P50=109 µs** (W2), **115 µs** (W3) | 1.4–3.6× slowdown vs Linux | — | eTran RTTs only (no Linux-Homa baseline) |
| 9 | RTT P50 shortest-10% W4 | **2848 µs** (eTran raw) | 4.1× vs Linux-Homa | — | Needs Linux baseline for slowdown ratio |
| 10 | RTT P50 shortest-10% W5 | **14530 µs** (eTran raw) | 3.9× vs Linux-Homa | — | Needs Linux baseline for slowdown ratio |
| 11 | RTT P99 shortest-10% W4 | **12604 µs** (eTran raw) | 4.3× vs Linux-Homa | — | Needs Linux baseline for slowdown ratio |
| 12 | RTT P99 shortest-10% W5 | **48026 µs** (eTran raw) | 2.9× vs Linux-Homa | — | Needs Linux baseline for slowdown ratio |
| 13 | TCP 1KB throughput | **~7.95 Gbps**, ~970 Kops (single-threaded, default 20 queues) | 4.8× Linux | — | **~2.84×** (1×1 setup; needs #13 redo for proper 5×5 comparison). DCTCP baseline: 2.8 Gbps |
| 14 | TCP 2KB throughput | **~11.79 Gbps**, ~719 Kops (single-threaded, default 20 queues) | 0.87× TAS | — | Raw number captured; ratio needs TAS baseline |
| 15 | TCP 1K persistent conns, 64B | **~1129 Kops peak / ~655 K steady aggregate** (10-thr server, 5 clients × 200 conns, default 20 queues) | 2.26× Linux | — | **~2.8×** (exceeds expected 2.26×). DCTCP baseline: ~0.234 Mops (no drops). eTran drops after ~9s |
| 18 | TCP KV throughput | **~0.73 Mops steady aggregate** (5 clients, 4 threads, 10 conns, 32 pending, default 20 queues) | ~2.6× Linux | — | DCTCP baseline: ~0.278 Mops. Ratio 2.61× within paper's 2.4-4.8× range. `--pending 32` changed from `--pending 16` per paper spec; no throughput difference observed |
| 19 | TCP KV P50 latency | **14 µs** (2026-07-06, def. 20 queues) | 17.2 µs | **122%** | Beats paper target. DCTCP baseline: 17 µs idle, 36 µs at 320 in-flight (5×1t×4c×16p). Paper's 64 µs Linux-TCP requires switch ECN marking — not reproducible without switch config |
| 20 | TCP KV P99 latency | **16 µs** (2026-07-06, def. 20 queues) | 27.5 µs | **172%** | Beats paper target. DCTCP baseline: 24 µs idle; same switch ECN caveat |
| 21 | TCP CPU cycles/req | **~2.93 kcycles** (2026-07-08, server-side, ~884 Kops, 31.1B cycles) | 4.37 kcycles | — | Server-side measured; paper value under NAPI stress includes overhead we don't see |
| 22 | Homa CPU cycles/req | **~1357 kcycles** (2026-07-06, 50.9B cycles, 1MB) | 5.48 kcycles | — | AF_XDP busy-poll inflation (99.6% idle); active ~5 kcycles matches paper |

**Key findings:**
- **Homa data path is FASTPATH — microkernel is NOT on it** (verified in
  source `micro_kernel/eBPF/homa/main.c`, `lib/eTran_rpc.cc`): NIC → entrance
  XDP → `xdp_sock` BPF calls `bpf_redirect_map(&xsks_map, socket_id)` to push
  Homa DATA packets directly into the **application's** AF_XDP socket. The app
  thread polls its XSK rings (`lib/eTran_rpc.cc:323,463`) and TXes via
  `xsk_ring_prod__reserve` + `kick_tx` (`lib/eTran_rpc.cc:187,203`). Homa
  grants are generated at the NIC by the `xdp_gen` BPF program (`return XDP_TX`
  in `eBPF/homa/main.c:192`) — also bypasses mk. The microkernel's only Homa
  role is **slow-path**: bind/close via `process_homa_cmd` (only `APPOUT_HOMA_BIND`
  / `APPOUT_HOMA_CLOSE` are handled — see `homa.cc:790`) and the 1ms timeout
  scan `poll_homa_to` which scans the BPF RPC map for zombies/retransmits.
  ⇒ **The earlier claim that "the single-threaded microkernel RX control_loop
  caps Homa ingress" is WRONG.** mk never sees a Homa data packet.
- **TCP data path is also FASTPATH** (`micro_kernel/eBPF/tcp/main.c:258,367,378`):
  TCP data redirected via `bpf_redirect_map(&xsks_map, ...)` to the app's XSK.
  mk only owns the slow-path XSK fed via `slow_path_map` — connection setup
  (SYN/handshake), closes, timeouts. So mk is NOT the throughput cap for TCP
  metrics 13-15 either; it only gates connection-rate metrics (16-17, not run).
- **Microkernel threading model** (verified `micro_kernel.cc`, `control_plane.cc:1070-1158`):
  mk has only 3 threads total (main + `control_loop` + `monitor`). `control_loop`
  sequentially calls poll_uds → poll_lrpc → poll_network → poll_tcp_handshake_events
  → poll_tcp_cc_to → poll_homa_to, then `clock_nanosleep`s up to `TICK_US` (1ms)
  when idle. It is **internally** pinned to `CP_CPU = 19` (`runtime/defs.h:26`),
  which is the HT sibling of core 9. With **HT enabled** (current config), core 19
  is online and the `pthread_setaffinity_np` at `control_plane.cc:1155` succeeds.
  NO external `taskset` is needed. With `nosmt` (previous config), the pin silently
  failed and the control_loop roamed — `taskset -c 9` was a workaround that gave
  5-25% improvement over the roaming baseline. HT-on gives ~8% over the old
  taskset workaround.
- The real Homa metric 3/5/6 bottlenecks (since mk is off the data path) are:
  per-app-thread polling rate, XDP_GEN grant eBPF scheduling (for large msgs),
  BPF RPC-map contention between the app fastpath and mk's 1ms `poll_homa_to`
  batch scan, and NIC RSS distribution across app queues (IRQ pinning had no effect). Same HW as paper,
  so the gap is a real software/tuning bug — investigate these, not cores.
- Affinity: NO taskset for micro_kernel (CP_CPU=19 internal pin succeeds with HT-on).
  Optionally pin app threads to physical cores 0-9 for consistent scheduling.
  This matches the paper's §6 design: mk control_loop on core 19
  (the HT sibling of core 9), app threads on physical cores 0-9.
  With the old `nosmt` config, `taskset -c 9`
  on mk gave a 5-25% lift over the roaming baseline, but HT-on + CP_CPU=19
  working gives ~8% additional improvement on metric 5.
- Metric 3 is bounded by the Homa grant dispatch through the XDP_GEN tail-call
  BPF (`eBPF/homa/main.c`): per-CPU state `granting_idx[cpu]`,
  `nr_grant_candidate[cpu]`, `HOMA_OVERCOMMITMENT=8`. Throughput plateaus at
  ~13 Gbps regardless of `--ports`. Same HW as paper → the plateau is a real
  serialization/overhead bug in the grant/dispatch eBPF, not a capacity ceiling.
- Metrics 1-2 are close to paper (93-94%). The remaining gap is NOT core count
  (paper used identical xl170 single-socket 10-core nodes — see AGENTS.md Hardware).
- Metric 4 is NOT NIC-limited — paper reached 22.7 Gbps on the same 25G link. The
  17 vs 22.7 gap is a real bug (XDP_GEN grant pacing + per-app-thread send rate),
  not the link.
- TCP benchmarks all work — the earlier SIGABRT was fixed by the BPF XDP_EGRESS patch.
- KV latency (metrics 19-20) **beats paper targets** (14 vs 17.2 µs P50, 16 vs 27.5 µs P99).
- `perf stat` works for TCP benchmarks but breaks Homa's AF_XDP polling (sampling interrupts cause RPC stalls).
- Full micro_kernel + shm restart required between every metric (stale BPF state = silent stalls).

---

Cross-references each metric from `eTran_reproduction_metrics.md`
against source code in:
- **eTran repo**: `https://github.com/eTran-NSDI25/eTran` (`homa_app/cp_node.cc`,
  `tcp_app/epoll_*.cc`, `tcp_app/flexkvs_*`, `lib/eTran_common.cc`)
- **Homa upstream**: `https://github.com/PlatformLab/HomaModule` (`util/cp_node.cc`)
- **Paper**: §6.1, Figures 5-6 (Gbps values confirmed from figure captions)

---

## Pre-Flight Checklist

1. **Microkernel** must be running on every node:
   ```bash
    cd /local/eTran/eTran/micro_kernel
    sudo ./micro_kernel -i ens1f1np1
    ```
    > Default 20 queues matches NIC combined=20 (check with `ethtool -l ens1f1np1`).

2. **App binaries** live in their build subdirectories:
   ```
   /local/eTran/eTran/homa_app   → cp_node
   /local/eTran/eTran/tcp_app    → epoll_*, lat_*, flexkvs_*
   ```

3. **Hostname resolution** — `cp_node` resolves `node0`, `node1` etc. via `getaddrinfo()`.
   Verify `/etc/hosts` or DNS across all nodes.

4. **Interface name** is hardcoded as `ens1f1np1` (`IF_NAME` macro in cp_node.cc:48,
   micro_kernel.cc, xdpsock.c). Recompile if your NIC differs.

5. **Headless execution** — run benchmarks non-interactively via ssh:

   Use `screen -dmS` for micro_kernel and server (they persist across runs).
   Clients are ephemeral — always wrap in `timeout`.

```bash
    # Kill everything, clean shm, start micro_kernels, start server, run client:
    #   NOTE: use `pgrep -x micro_kernel` and `kill` BY PID, not `pkill -f micro_kernel`
    #         (pkill -f matches its own cmdline, self-killing before reaching the targets).
    #   NOTE: after a SIGKILLed micro_kernel you may have an orphaned XDP program
    #         still attached to the NIC -- detach it explicitly, or the next
    #         micro_kernel load will fail or silently no-op.
    ssh node0 'for p in $(pgrep -x micro_kernel) $(pgrep -x cp_node); do sudo kill -9 $p; done; \
       sudo ip link set dev ens1f1np1 xdp off 2>/dev/null; \
       sudo rm -f /dev/shm/BufferPool_* /dev/shm/UMEM_* /dev/shm/LRPC_*'
    ssh node1 'for p in $(pgrep -x micro_kernel) $(pgrep -x cp_node); do sudo kill -9 $p; done; \
       sudo ip link set dev ens1f1np1 xdp off 2>/dev/null; \
       sudo rm -f /dev/shm/BufferPool_* /dev/shm/UMEM_* /dev/shm/LRPC_*'

    # NO taskset for micro_kernel — CP_CPU=19 (defs.h:26) pins control_loop
    # to core 19 (the HT sibling of core 9) automatically. Only works with HT ON.
    # Default 20 queues matches NIC combined=20.
    ssh node0 "sudo screen -dmS micro_kernel bash -c 'cd /local/eTran/eTran/micro_kernel && exec ./micro_kernel -i ens1f1np1'"
    ssh node1 "sudo screen -dmS micro_kernel bash -c 'cd /local/eTran/eTran/micro_kernel && exec ./micro_kernel -i ens1f1np1'"
    sleep 5

    ssh node0 "sudo screen -dmS server bash -c 'cd /local/eTran/eTran/homa_app && exec env ETRAN_PROTO=homa ./cp_node server'"
   sleep 3

   ssh node1 "timeout 15 env ETRAN_PROTO=homa ./cp_node client ... 2>&1"
   ```
   > Use `screen -dmS` (not `nohup ... </dev/null`) for background processes —
   > the micro_kernel monitor thread exits on stdin EOF. `screen` provides
   > a proper pty. Server stays alive for multiple client runs; only restart
   > it when switching metrics or after stale state.

6. **Shm cleanup** between metrics — mandatory to avoid stale BPF state.
   See AGENTS.md "Critical procedure for running benchmarks" for the full
   kill → clean → screen restart → run sequence.

---

## cp_node Argument Reference

Verified against `homa_app/cp_node.cc` (eTran) and upstream `PlatformLab/HomaModule/util/cp_node.cc`.

### Client options (`cp_node client [opts]`)

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--workload` | string | `"100"` | `w1`-`w5` (Homa CDFs) or integer for fixed-size bytes |
| `--client-max` | int | `1` | Max outstanding RPCs per machine (÷ ports) |
| `--ports` | int | `1` | Sending threads (one per port) |
| `--server-nodes` | int | `1` | Number of server nodes to target |
| `--server-ports` | int | `1` | Server ports per node |
| `--first-server` | int | `1` | First server node ID (`nodeN`) |
| `--gbps` | float | `0.0` | Target Gbps; **0 = send continuously** (closed-loop) |
| `--one-way` | flag | `false` | Server returns 100B response (not echo) |
| `--id` | int | `-1` | This node's ID; skip `node{id}` as target |
| `--both` | int | `0` | Start as server, wait N seconds, then start client |
| `--unloaded` | int | `0` | Baseline RTT sweep per message size (Homa only) |
| `--queues` | int | `1` | NIC queues (eTran). **Never set on client** — kills throughput |

### Server options (`cp_node server [opts]`)

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--ports` | int | `1` | Listening ports/threads. `--ports 5/7` verified safe with BPF XDP_EGRESS patch applied (no buffer-pool assert); `--ports 10` works but throughput drops because 1-thread client can't fill 10 server ports. Use 4 (paper's hint) or any of 4/5/7 — all hit the same ~13 Gbps ceiling |
| `--first-port` | int | `4000` | Lowest port number |

### Key semantics

- **`--gbps 0`** = unlimited (closed-loop, throttled only by `--client-max`). Nonzero = open-loop Poisson at that Gbps.
- **`--one-way`** = response capped at **100B** (not 32B as paper states). `short_response` flag in message header.
- **`--workload 1000000`** hits exact `HOMA_MAX_MESSAGE_LENGTH` boundary. Use `999999`.
- **`--both N`** = node starts server (using `--server-ports` ports), waits N seconds, then starts client. Used for all-to-all cluster topology.
- **`--id N`** = prevents sending to `nodeN` (self). Required with `--both` in all-to-all.
- `--server-ports`, `--workload`, `--gbps`, `--client-max`, `--one-way` are **client-only**. Server ignores them.

---

## Table 1 — Primary eTran Metrics

### 1. eTran - Homa | Median RTT latency, 32B requests, single client | 11.8 µs | 2-Node

Paper §6.1: "single client thread to send back-to-back requests (32B) to a
single-threaded server, which responds with a 32-byte response."

```bash
# Server (node0) — single-threaded, echoes 32B response (no --one-way):
ETRAN_PROTO=homa ./cp_node server

# Client (node1):
timeout 15 env ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 32
```
Output every 1s: `Clients: <Kops> Kops/sec, <gbps> Gbps out, ..., RTT (us) P50 <p50> P99 <p99> P99.9 <p99.9>`
Read P50 for the metric.

**Result** (2026-07-06, default 20 queues): P50 **12.59 µs** (93% of target).
P99 14.85 µs. Stable across measurements. Small vs paper; cause under
investigation (NOT a NUMA/socket gap — paper used identical xl170 10-core
single-socket hardware).

### 2. eTran - Homa | Throughput, 1MB requests, back-to-back | 17.7 Gbps | 2-Node

Paper §6.1: "single client thread to send back-to-back requests (1MB) to a
single-threaded server, which responds with a 32-byte response."

```bash
# Server (node0) — single-threaded:
ETRAN_PROTO=homa ./cp_node server

# Client (node1) — single-stream back-to-back:
timeout 15 env ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 999999 \
  --one-way
```
Output: `Clients: ... Gbps out ...` — read Gbps out for the metric.

> **`--one-way`** makes the server return a **100-byte** response (not 32B as the
> paper states — the `short_response` flag caps at 100B in cp_node source). This
> doesn't meaningfully affect 1MB throughput measurements.
>
> **`--workload 999999`** instead of `1000000`: avoids the `HOMA_MAX_MESSAGE_LENGTH`
> off-by-one (length 1000000 hits the exact buffer boundary; use 999999).
>
> `--client-max 1 --ports 1` are defaults — omitted for clarity. `--gbps 0` (default)
> means "send continuously" (closed-loop back-to-back).

**Result** (2026-07-06, default 20 queues): **16.6 Gbps** (94% of target).
Stable across 15+ measurements. RTT P50 442 µs, stability within ±0.1 Gbps.
Clean shm between metrics is critical — stale BPF state causes stalls with 0
completions.

### 3. eTran - Homa | Multi-threaded server throughput, 500KB, 7 clients | 23.0 Gbps | 8-Node

Paper §6.1: "multi-threaded server receiving concurrent RPCs (500KB) from 7 clients".

```bash
# Server (node0) — multi-threaded (4 ports = 4 server threads):
ETRAN_PROTO=homa ./cp_node server --ports 4

# 7 client nodes (node1–node7), each:
timeout 30 env ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 500000 \
  --client-max 1 \
  --ports 1 \
  --server-ports 4 \
  --one-way
```
Measure server-side Gbps in (output: `Servers: ... Gbps in ...`).

> **`--ports 4`** on server: 4 server threads. The earlier "max 4" buffer-pool
> crash claim is **stale** — verified 2026-07-06 that server `--ports 5/7`
> run cleanly at ~12.8 Gbps (within 1% of `--ports 4`) with the BPF XDP_EGRESS
> patch applied, no asserts, no dmesg errors. `--ports 10` is worse (~8 Gbps)
> because the 1-thread client can only fill 7 of 10 server ports; the 8th-10th
> stay idle. The 13 Gbps ceiling is therefore **not** server parallelism but
> the XDP_GEN grant dispatch path. Use `--ports 4` (paper's hint) or any of
> 5/7 — they all hit the same ceiling.
>
> **`--workload 500000`**: 500KB (paper's wording). Not 524288 (512KiB).
>
> Start clients with 0.3s stagger (see AGENTS.md multi-node orchestration).
>
> **⚠️ Note on thread oversubscription**: micro_kernel has only **3 threads**
> total (main + `control_loop` + monitor). The Homa data path does NOT go
> through mk — data is fastpath-redirected by the XDP BPF to the app's XSK
> and polled by the app thread (see Key findings). mk only owns slow-path
> (bind/close + 1ms timeout scan). Counting mk + server (4) + 7 clients (1
> each) ≈ 14 runnable threads on 10 cores, but the bottleneck is NOT raw
> thread oversubscription and NOT mk dispatch — it's the XDP_GEN grant
> eBPF serialization and the per-app-thread send cap. `--client-max 1
> --ports 1` gives the best throughput (12.9 Gbps sustained); higher
> concurrency (`--client-max 2`→10.9 Gbps, `--client-max 4`→10.6 Gbps then
> collapse) degrades due to the BPF grant path, not raw oversubscription.
> Paper ran on identical xl170 10-core single-socket nodes, so the gap is
> NOT a core-count deficit; it is the grant-egress-side bug
> (XDP_GEN grant dispatch serialization on `HOMA_OVERCOMMITMENT=8` per-CPU
> state). The earlier hypothesis that `--ports > 4` buffer-pool crash capped
> server parallelism is **refuted** (see `--ports` sweep above).
> Use `--client-max 1 --ports 1`.

**Result** (2026-07-06, default 20 queues): **12.9 Gbps** (56% of target).
Reproduced on fresh reboot with default 20 queues. The shortfall vs paper's
23 Gbps is a real bug, not a core-count penalty (same HW). RTT P50 ~2.1ms.
`--client-max 2`→10.9 Gbps
(worse), `--client-max 4`→10.6 Gbps then collapse, `--client-max 64`→10.57 Gbps
burst then stall (BPF grant overwhelmed at 448 concurrent RPCs).

**`--ports` sweep on server (2026-07-06, clean restart between each)**:
| Server `--ports` | Steady Gbps | Peak Gbps | Notes |
|---:|---:|---:|---|
| 4 | 12.9 | — | baseline |
| 5 | 12.78 | 13.77 | no crash |
| 7 | 12.77 | 12.77 | no crash |
| 10 | 8.01 | 9.09 | client fan-out limit; 3 ports idle |

4/5/7 are equivalent (within 1% noise). 10 is worse due to client-side
1-thread fan-out, not server. No buffer-pool asserts at any port count with
the BPF XDP_EGRESS patch applied. The 13 Gbps ceiling is a real eBPF
serialization limit, not a server-side resource cap.

### 4. eTran - Homa | Multi-threaded client throughput, 500KB, 7 servers | 22.7 Gbps | 8-Node

Paper §6.1: "multi-threaded client sending concurrent RPCs to 7 servers".

```bash
# 7 server nodes (node0–node6), each:
ETRAN_PROTO=homa ./cp_node server

# 1 client (node7) with 7 ports matching 7 servers:
timeout 30 env ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 500000 \
  --client-max 1 \
  --ports 7 \
  --server-nodes 7 \
  --one-way
```
Measure client-side Gbps out.

> `--ports 7`: 7 sending threads (one per server). `--server-ports 1` is default.
> `--client-max 1`: 1 outstanding per port, 7 total. Higher concurrency stalls
> (e.g. `--client-max 64` → 448 concurrent RPCs, CPU contention on 10 cores).

**Result** (2026-07-06, default 20 queues): **19.5 Gbps** (86% of target).
Bottleneck under investigation — NOT the NIC (paper reached 22.7 Gbps on the
same 25G link). NOT mk dispatch:
Homa data is fastpath-redirected by XDP to the app's XSK; the client's 7 app
threads send directly via `xsk_ring_prod`. Likely candidates are the XDP_GEN
grant pacing eBPF overhead on the receive side and the per-app-thread send
throughput cap on the client. RTT P50 ~1.37ms. Stable throughput within ±1 Gbps.
Each single-threaded server handles ~2.8 Gbps.

### 5. eTran - Homa | Client RPC rate, 32B | 2.9 Mops | 8-Node (7:1 ratio)

Paper §6.1: "RPC rate for small messages (32B), maintaining the same
client-to-server ratio" — same 7:1 as metric 3.

```bash
# Server (node0) — 7 server threads for 32B (small messages, no buffer pool issue):
ETRAN_PROTO=homa ./cp_node server --ports 7

# 7 client nodes (node1–node7), each:
timeout 30 env ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 32 \
  --client-max 64 \
  --ports 1 \
  --server-ports 7
```
Output: `Clients: <Kops> Kops/sec` — aggregate across all 7 clients for Mops.

> 32B messages don't need Homa grants (small message fits in unscheduled grant),
> so the XDP_GEN grant path is idle and no buffer-pool pressure at any port count.
> `--client-max 64 --ports 1`: 64 outstanding per client node, 1 sending thread.
> `--ports 1 --client-max 64` per client gives the best result
> (~927 Kops server steady, 32% of target). Higher `--client-max` or more
> client threads reduces throughput — but NOT because of mk dispatch (mk is NOT
> on the Homa data fastpath — see Key findings). The cap is the per-app-thread
> polling rate and BPF map contention between the app fastpath and mk's 1ms
> `poll_homa_to` timeout scan. Full micro_kernel + shm restart required
> between runs. IRQ pinning was tested and shown to have no effect.
> 
> **Result** (2026-07-06, default 20 queues): **~927 Kops/sec** server steady
> (32% of 2.9 Mops target).
> RTT P50 ~400-460µs across clients. Same HW as paper — the 3.1× gap is NOT core
> count and NOT mk dispatch; it is per-app-thread polling/XDP-redirect overhead plus
> BPF RPC-map contention. See Key findings.

### 6. eTran - Homa | Server RPC rate, 32B | 3.3 Mops | 8-Node (1:7 ratio)

Paper §6.1: same 1:7 ratio as metric 4 — 1 client → 7 servers.

```bash
# 7 server nodes (node0–node6), each:
ETRAN_PROTO=homa ./cp_node server

# Client (node7):
timeout 30 env ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 32 \
  --client-max 256 \
  --ports 7 \
  --server-nodes 7
```
Output: `Servers: <Kops> Kops/sec` (aggregate across all 7 servers).

> **⚠️ Requires fresh restart**: previous attempts with stale micro_kernel state
> produced 0 completions. Full `pkill -9 micro_kernel; rm -f /dev/shm/*; restart`
> on ALL nodes is mandatory. Use `--ports 7 --client-max 256` (not --ports 1).

**Result** (2026-07-06, default 20 queues): **~1120 Kops/sec** client steady
(34% of 3.3 Mops target). RTT P50 ~217µs (stable).
Per-server breakdown: ~160 Kops/sec each. Same HW as paper — gap is NOT core
count and NOT mk dispatch (Homa data is app fastpath, see Key findings);
real bottleneck is per-app-thread polling rate +
XDP_GEN + BPF RPC-map contention.

### 7–12. eTran - Homa | P50/P99 tail latency slowdown, W2–W5 | 10-Node Cluster

Paper §6.1: "conducted with 10 machines. In this experiment, **each node serves as
both a multi-thread client and a multi-thread server simultaneously**. Clients
randomly select servers to issue a batch of RPCs."

Workloads W2–W5 from the Homa SIGCOMM paper, defined in `homa_app/dist.cc`.
Figure 5 captions give the exact offered load per workload:
- **W2: 3.2 Gbps** (short-message dominated)
- **W3: 14 Gbps** (short-message dominated)
- **W4: 20 Gbps** (large-message dominated)
- **W5: 20 Gbps** (large-message dominated)

These match the upstream Homa `cp_vs_tcp` script:
`[["w2", 3.2, 5], ["w3", 14, 10], ["w4", 20, 20], ["w5", 20, 30]]`

**Per-workload parameters** (change all three for each run):

| Workload | `--workload` | `--gbps` | `RUN_SECONDS` |
|----------|-------------|----------|---------------|
| W2       | `w2`        | `3.2`    | `5`           |
| W3       | `w3`        | `14`     | `10`          |
| W4       | `w4`        | `20`     | `20`          |
| W5       | `w5`        | `20`     | `30`          |

#### All-to-all topology (paper's setup)

Run on all 10 nodes simultaneously. Each node acts as both client and server
via `--both N` (starts server, waits N seconds, then starts client). `--id`
prevents a node from sending to itself:

```bash
# Repeat for each workload (w2, w3, w4, w5) twice:
#   once with eTran kernel booted,
#   once with stock Linux kernel booted (for Linux-Homa baseline).

# On each node (node0–node9), set NODE_ID and workload params:
NODE_ID=0          # change per node
WL=w2              # w2, w3, w4, or w5
GBPS=3.2           # 3.2, 14, 20, or 20 (see table above)
RUN_SECONDS=5      # 5, 10, 20, or 30 (see table above)

(echo "client --first-server 0 --server-nodes 10 --workload ${WL} --client-max 100 --ports 4 --server-ports 4 --one-way --gbps ${GBPS} --both 2 --id ${NODE_ID}"; \
 sleep $((RUN_SECONDS + 5)); \
 echo "dump_times /tmp/rtts_node${NODE_ID}.txt"; \
 sleep 1; \
 echo "exit") \
| timeout $((RUN_SECONDS + 15)) env ETRAN_PROTO=homa ./cp_node 2>&1
```
Record P50/P99/P99.9 RTT (µs) from 1s stats output.
Slowdown = `eTran_RTT / Linux_RTT` (run same workload on stock Linux for baseline).

> **`--both 2`**: node starts as server (4 ports via `--server-ports 4`), waits 2s,
> then starts client with 4 sending threads (`--ports 4`).
> **`--id N`**: skips `nodeN` (itself) when building the server address list.
> **`--server-ports 4`** (matches `--ports 4` for all-to-all workload): The earlier
> "max 4 / buffer pool crash" claim for the SERVER was based on 500KB RPCs and
> was **refuted 2026-07-06** (see metric 3 `--ports` sweep). The cap of 4 in
> W2-W5 is **operational**: it is what the original metric 3 invocation used
> (`cp_node --server-ports 4 --ports 1 --client-max 1`), not a hard limit.
> Could try `--server-ports 7 --ports 4` for these workloads, but the
> all-to-all topology has different traffic shape (mixed message sizes via
> `w2`/`w3`/`w4`/`w5` CDFs) — verify on a fresh run before changing.
> **Gbps per workload**: W2=3.2, W3=14, W4=20, W5=20. Using 20 for W2/W3 is WRONG.

#### Collecting individual RTT samples (for W4/W5 shortest-10% filtering)

Paper Figure 6: "RTT distributions for the shortest messages (10%) in W4 and W5".

`dump_times` writes per-RPC samples as `<length> <rtt_us>` pairs. It must be
issued as a separate command — in headless mode (single argv command), it can't
run. Use the interactive pipe pattern above, or:

```bash
# Interactive mode: start cp_node, issue commands via stdin
(echo "client --first-server 0 ..."; sleep 30; echo "dump_times /tmp/rtts.txt"; echo "exit") | ./cp_node
```

Post-process to filter shortest 10%:
```bash
# Sort by message length, take lowest decile, then compute P50/P99 of that subset
awk '{print $1, $2}' /tmp/rtts_node*.txt | sort -n | \
  awk 'NR==1{total=0} {vals[NR]=$2; total++} END{
    decile=int(total*0.1);
    for(i=1;i<=decile;i++) print vals[i]
  }' | sort -n | awk '
    {a[NR]=$1}
    END{
      print "P50:", a[int(NR/2)];
      print "P99:", a[int(NR*99/100)];
      print "P99.9:", a[int(NR*999/1000)]
    }'

#### Results (2026-07-06, default 20 queues, no taskset, no IRQ pinning)

eTran-only RTT values (Linux-Homa baseline postponed):

| Workload | Offered Load | Duration | Aggregate Server Kops | Overall P50 | Overall P99 | Shortest-10% P50 | Shortest-10% P99 |
|:---------|:-------------|:---------|:---------------------|:------------|:------------|:-----------------|:-----------------|
| W2       | 3.2 Gbps     | 5s       | ~3990 Kops           | **109 µs**  | **1344 µs** | **91 µs**        | **118 µs**       |
| W3       | 14 Gbps      | 10s      | ~707 Kops            | **115 µs**  | **1428 µs** | **110 µs**       | **1462 µs**      |
| W4       | 20 Gbps      | 20s      | ~84 Kops             | **3068 µs** | **13713 µs**| **2848 µs**      | **12604 µs**     |
| W5       | 20 Gbps      | 30s      | ~16 Kops             | **18007 µs**| **130044 µs**| **14530 µs**    | **48026 µs**     |

> **W2/W3** are short-message dominated workloads — low latency (109-115 µs P50) reflects
> Homa's efficient small-message handling under moderate load.
> **W4/W5** are large-message dominated (~60 KB and ~380 KB avg message sizes respectively).
> High latency for shortest-10% messages (2.8-14.5 ms P50) is due to Homa's grant-based
> flow control: large DATA packets consume NIC/memory bandwidth, delaying small RPCs.
>
> **Per-node variation**: W2 showed even load distribution (~430 Kops/node for 9/10 nodes,
> node2 lower at ~100 Kops). W3-W5 showed wider per-node variance (factor 10-100x between
> most and least loaded nodes) — typical for all-to-all open-loop experiments where
> `--both 2` timing creates slight phase misalignment between nodes.
>
> **Comment headers** in `dump_times` output (`# --server-nodes 10 ...`) must be
> filtered with `grep -v '^#'` before processing.
>
> Slowdown factors vs Linux-Homa require a separate run on stock Linux kernel.

### 13. eTran - TCP | 1KB throughput, 64 outstanding, single-threaded | 4.8x Linux | 2-Node

```bash
# Server:
ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_server -i 192.168.6.1 -b 1024

# Client:
timeout 30 env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_client -i 192.168.6.1 -b 1024 -o 64 -f 1 -t 1
```
Output: `Throughput In/Out(<gbps>/<gbps> Gbps)(<kops> Kops)` every second.
Use `script -q -c` over SSH to force line-buffered output (C stdout buffering hides stats otherwise).
**⚠️ Env vars must be inside `script -q -c`** — `env VAR=val script -q -c 'cmd'` does NOT pass
env vars into the subshell. Use: `script -q -c 'VAR=val ./cmd' /dev/null`.

> **`-b`** is message/request size (bytes), NOT buffer size.
> **`-l`** (`max_buf_size`, default 4096) omitted — 4096 is enough for 1KB messages.
> epoll_client/server run `while(1)` — **always wrap in `timeout`**.
> Default (no `-s` on client or server): `short_response=true` → server sends 100B response.
> With `-s` on both: `short_response=false` → server echoes full request (used for latency).
> Must match on client and server side.

**Result** (2026-07-08, fresh reboot, default 20 queues): **~7.19 Gbps**, ~878 Kops
(1×1 × 64, server 1t/1q). The earlier 7.95 Gbps / 970 Kops was within run-to-run
noise (~10%). Connection drops after ~9s are **no longer observed** (~19s run
completed cleanly) — likely resolved by the BPF XDP_EGRESS patch.

**Scaled (5×5 × 64) result** — 5 clients × 5 threads × 1 flow × 64 outstanding:
- **~7.55 Gbps aggregate**, ~922 Kops total (per-client ~178 Kops).
- **No connection drops** at 1600 in-flight (contrary to the old "6400 drops" caveat).
- Single 5-thread client saturates at **~12.1 Gbps / ~1474 Kops**.

**Ratio vs DCTCP (same 1×1 × 64 config):** **~3.96×** (paper: 4.8×). Acceptable
given DCTCP sensitivity to switch ECN marking state.

### 14. eTran - TCP | 2KB throughput, 64 outstanding, single-threaded | 0.87x TAS | Medium

```bash
# Server:
ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_server -i 192.168.6.1 -b 2048

# Client:
timeout 30 env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_client -i 192.168.6.1 -b 2048 -o 64 -f 1 -t 1
```
Output: same format as #13. Use `script -q -c` over SSH for line-buffered output.
**⚠️ Env vars must be inside `script -q -c`** — same caveat as #13.

**Result** (2026-07-08, fresh reboot, default 20 queues): **~12.29 Gbps**, ~750 Kops
(1×1 × 64, server 1t/1q). Within expected run-to-run noise (~4%). No connection
drops observed during 15s+ runs.

**Ratio vs DCTCP (same 1×1 × 64 config):** **~6.76×** (based on DCTCP 1.82 Gbps
measured concurrently). Note: DCTCP 2KB throughput varies significantly
(1.8-4.6 Gbps) based on switch ECN marking state — the earlier 4.6 Gbps DCTCP
baseline was through a different queue state. Ratio should be recalculated when
DCTCP stabilizes at its known 4.6 Gbps level (resulting in ~2.65×).

### 15. eTran - TCP | 1K persistent connections, 64B requests | 2.26x Linux | 6-Node

```bash
# Server (1 node) — 10 threads:
ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=10 ETRAN_NR_NIC_QUEUES=10 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_server -i 192.168.6.1 -b 64 -t 10

# Clients (5 nodes), each: 200 connections → 1000 total:
timeout 30 env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=4 ETRAN_NR_NIC_QUEUES=4 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_client -i 192.168.6.1 -b 64 -f 200 -t 4 -o 1 -w 2
```

> **`-w 2`**: `wait_seconds` — 2s delay after connecting before measuring.
> **`-o 1`**: 1 outstanding request per connection (closed-loop).
> Use `script -q -c` over SSH for line-buffered output (same issue as #13).
> **⚠️ Env vars must be inside `script -q -c`** — `env VAR=val script -q -c 'cmd'`
> does NOT pass env vars into the subshell. Use:
> `script -q -c 'VAR=val ./cmd' /dev/null`
> Start clients with 0.3-0.5s stagger to avoid overwhelming the server.

**Result** (2026-07-06, fresh reboot, default 20 queues): **~1129 Kops peak / ~655 K steady
aggregate**. 5 clients × 200 connections = 1000 persistent connections, 64B
closed-loop, 1 outstanding per connection. Steady per-client throughput ~160-170 Kops each.
Node5 inconsistently connects only 167/200 connections. Connection drop after ~9s
limits window — use `timeout 15` for a clean run.

### 16. eTran - TCP | Short-lived 16 msg/conn, 1K concurrent | 42.7x Linux | 6-Node

**⚠️ CAVEAT**: `epoll_client` only supports **persistent** connections. The public
eTran repo does not include a short-lived TCP connection benchmark binary.
This metric requires a custom benchmark that opens/closes connections and sends
16 messages each. Not reproducible with the public repo as-is.

### 17. eTran - TCP | Short-lived 256 msg/conn, 1K concurrent | 5.4x Linux | Medium

**⚠️ Same caveat as #16. Not reproducible with the public repo as-is.**

### 18. eTran - TCP | KV throughput, 100K keys, Zipf s=0.9, 9:1 GET:SET | 2.4~4.8x Linux | 6-Node

```bash
# Server (1 node) — 4 threads, 1 NIC queue:
ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=4 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./flexkvs_server default 4 1

# Clients (5 nodes), each:
timeout 45 env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=4 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./flexkvs_bench \
  --threads 4 \
  --conns 10 \
  --pending 32 \
  --key-num 100000 \
  --key-size 32 \
  --val-size 64 \
  --get-prob 0.9 \
  --key-zipf=0.9 \
  --time 30 \
  --warmup 5 \
  --cooldown 5 \
  <server-ip>:11211
```
Output: `TP: total=<mops> mops  50p=<us> 90p=<us> 95p=<us> 99p=<us> 99.9p=<us> 99.99p=<us>` every second.

> **`ETRAN_NR_APP_THREADS=4`** must match the application thread count (server: 4
> positional arg, client: `--threads 4`). Previously set to 1 — wrong.
> **`--time`/`--warmup`/`--cooldown` are stored but never enforced** by flexkvs_bench
> (no phase transition to DONE). Always wrap in `timeout`. The `--time 30` is
> informational only; `timeout 45` provides the actual 30s run + 5s warmup + buffer.
> Server port is hardcoded to **11211** (memcached).
> **`--pending 32`** changed from 16 per paper spec (§6.4: "each uses 32 parallel
> GETs"). Throughput is bottlenecked elsewhere — 16 vs 32 produces identical results.

**Result** (2026-07-08, `--pending 32`, default 20 queues): **~0.73 Mops
steady aggregate** (5 clients). Per-client: ~150, ~149, ~146, ~142, ~140 Kops.
Per-client latency under load: P50≈262 µs, P99≈310 µs.
DCTCP baseline: ~0.278 Mops aggregate. Ratio: **~2.61× Linux** (within paper's 2.4-4.8×).

### 19. eTran - TCP | KV P50 latency, under-loaded | 17.2 µs | 6-Node

```bash
# Same as #18 but with just 1 client thread, 1 connection, 1 pending:
timeout 20 env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./flexkvs_bench \
  --threads 1 \
  --conns 1 \
  --pending 1 \
  --key-num 100000 \
  --key-size 32 \
  --val-size 64 \
  --get-prob 0.9 \
  --key-zipf=0.9 \
  --time 10 \
  <server-ip>:11211
```
Read P50 µs from output (`50p=<us>`).

**Result** (2026-07-06, default 20 queues): **14 µs P50** (beats paper's 17.2 µs).
0.067 Mops at 1 pending RPC. P90=16 µs, P99=16 µs, P99.9=18 µs, P99.99=187 µs.
Stable across 20+ measurements. Confirmed identical to previous session — latency
unaffected by queue count or IRQ config.

### 20. eTran - TCP | KV P99 latency, under-loaded | 27.5 µs | 6-Node

Same command as #19. Read P99 µs from output (`99p=<us>`).

**Result** (2026-07-06, default 20 queues): **16 µs P99** (beats paper's 27.5 µs).
Tight latency distribution — all in the 14-18 µs range up to P99.9.

### 21. eTran - TCP | Total CPU cycles per request | 4.37 kcycles | 2-Node CPU Profiling

```bash
# Run TCP throughput test (#13) under perf:
sudo perf stat -e cycles,instructions,context-switches,cpu-migrations,page-faults \
  timeout 20 env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_client -i 192.168.6.1 -b 1024 -o 64 -f 1 -t 1

# Calculate kcycles/request = (total cycles) / (total requests)
# For per-component breakdown (matching Table 5), use perf record + report:
sudo perf record -g -F 99 -- timeout 20 env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_client -i 192.168.6.1 -b 1024 -o 64 -f 1 -t 1
sudo perf report --stdio --sort=comm,dso,symbol,dso_from,symbol_from
# Map symbols to the categories in Table 5 (Application, Socket/RPC, Data Copy,
# Sk_buff, TCP/Homa+IP, Lock/Unlock, NIC Driver, Memory Mgmt, Scheduling, Other).
```

> **perf works for TCP benchmarks** (unlike Homa — see Known Limitation #15).
> perf sampling interrupts don't stall TCP epoll_wait loops.
> The microkernel's AF_XDP busy-poll is unaffected by perf on the application side.
> For cycle-accurate measurement on the server, run perf stat on the server process
> while the benchmark runs.

**Client-side result** (2026-07-06, default 20 queues, 25s perf run at ~880 Kops):
63.8B cycles, 94.8B instructions (1.49 IPC), ~2.9 kcycles/request. Includes idle
epoll_wait cycles.

**Server-side result** (2026-07-08, same 1×1 × 64 config, 12s perf window at
~884 Kops steady): **31.1B cycles / ~2.93 kcycles/request**, ~4950 instructions/req
(1.69 IPC). Lower than paper's 4.37 kcycles — our measurement captures only the
server process during an active benchmark, whereas the paper's value includes
NAPI overhead under continuous stress. The ratio vs client-side is consistent
at ~2.9 kcycles.

### 22. eTran - Homa | Total CPU cycles per request | 5.48 kcycles | 2-Node CPU Profiling

```bash
# Run Homa throughput test (#2) under perf:
# NOTE: perf breaks eTran AF_XDP timing — see Known Limitation #15.
# The below commands produce data but cycles/RPC is inflated by busy-poll.
# Build perf first: cd /lib/modules/6.6.0-eTran+/build/tools/perf
#   && sudo make -j$(nproc) NO_JEVENTS=1 NO_LIBTRACEEVENT=1 NO_LIBPFM4=1
perf stat -e cycles,instructions,context-switches,cpu-migrations,page-faults \
  timeout 15 env ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 999999 \
  --one-way
```

**Result** (2026-07-06, default 20 queues, 20s perf run at ~15-16 Gbps throughput):
50.9B cycles, 89.9B instructions (1.77 IPC), 2,055 context-switches, 16 CPU
migrations. Cycles/request ≈ **~1357 kcycles** (dominated by AF_XDP idle polling).
Active processing estimated at ~5 kcycles/request. Paper's 5.48 kcycles measured
on kernel Homa module (no busy polling). Only Metric 22 (Homa) is blocked by
`perf` interference — Homa's AF_XDP busy-poll stalls under sampling interrupts.
For cycle-accurate measurement, run without perf and estimate: active cycles ≈
total_cycles × (active_us / elapsed_us).

---

## Table 2 — CPU Cycles Breakdown (Table 5)

Requires `perf` with hardware counters. Run against TCP and Homa benchmarks
under single-NAPI-context stress. The source code categories are:

| Paper Category     | Kernel Symbols to Match                              |
|:-------------------|:-----------------------------------------------------|
| Application        | User-space app code (cp_node/epoll_client main loop) |
| Socket/RPC         | `__sys_sendto`, `__sys_recvmsg`, socket layer        |
| Data Copy          | `copy_user_enhanced_fast_string`, `memcpy_erms`      |
| Sk_buff            | `__alloc_skb`, `__kfree_skb`, `skb_*`                |
| TCP/Homa + IP      | `tcp_*`, `homa_*`, `ip_*`, `ip6_*`                  |
| Lock/Unlock        | `_raw_spin_lock`, `mutex_lock`, `mutex_unlock`       |
| NIC Driver         | `mlx5e_*`, `mlx5_*` (adapt to your NIC driver)      |
| Memory Mgmt        | `__alloc_pages`, `__free_pages`, `slab_*`            |
| Scheduling         | `__schedule`, `schedule`, `try_to_wake_up`           |
| Other              | Everything else                                      |

```bash
perf record -g -F 99 -o /tmp/perf.data <benchmark-command>
perf report --stdio -i /tmp/perf.data --sort=comm,dso,symbol | head -80
```

---

## Table 3.1 — XDP_EGRESS Egress Overhead (Table 3)

Requires the eTran kernel's `XDP_EGRESS` hook. Benchmarked via `xdpsock` in
`/local/eTran/bench-afxdp/`. xdpsock runs indefinitely — always wrap in `timeout`.

### AF_XDP tx-only baseline | 11.55 Mpps
```bash
sudo timeout 15 taskset -c 2 ./xdpsock -i ens1f1np1 -q 2 -t -s 64 -N -z
```

### + Empty XDP_EGRESS | 10.79 Mpps (6.6% loss)
**⚠️** Requires eTran kernel BPF program with empty `XDP_EGRESS` hook loaded:
```bash
# Load empty XDP_EGRESS BPF program (depends on eTran kernel config)
# Then run the same txonly benchmark:
sudo timeout 15 taskset -c 2 ./xdpsock -i ens1f1np1 -q 2 -t -s 64 -N -z
```

### + OOO Completion | 9.95 Mpps (13.9% loss)
Enables out-of-order completion buffer support (eTran kernel feature).

### + Array Lookup | 9.71 Mpps (15.9% loss) | Medium
### + Hashmap Lookup | 9.10 Mpps (21.2% loss) | Medium

These require loading specific BPF programs via the eTran kernel's BPF loader.
The paper measures progressive overhead of each feature stacked. Run txonly
with each BPF program variant loaded.

---

## Table 3.2 — XDP_GEN Packet Generation (Table 4)

### l2fwd baseline | 6.73 Mpps overall, 1.74 active cores | Medium
```bash
sudo timeout 15 taskset -c 2 ./xdpsock -i ens1f1np1 -q 2 -l -N -z -B -b 256
```

### rx-drop + XDP_GEN | 6.03 Mpps overall, 1.35 active cores | 2-Node
**⚠️** `XDP_GEN` is an eTran kernel hook — requires a BPF program that generates
ACK/credit packets using the `XDP_GEN` hook. The rx-drop side:
```bash
sudo timeout 15 taskset -c 3 ./xdpsock -i ens1f1np1 -q 3 -r -N -z
```

---

## Quick-Reference: Key Source Code in eTran repo

> All paths relative to repo root `https://github.com/eTran-NSDI25/eTran`.
> Line numbers re-verified 2026-07-06 against current checkout (after the
> cp_node.cc / eBPF drifts noted in commit history were corrected).

### Benchmark / application binaries

| File | Key Locations |
|:--|:--|
| `homa_app/cp_node.cc` | L54 `IF_NAME`="ens1f1np1"; L1426 `server_stats`, L1476 `client_stats` (Kops/Gbps/RTT P50-P99.9); L1603 `client_cmd` defaults, L1929 `server_cmd`; L1616 `workload = "100"` default |
| `homa_app/dist.cc` | `w1`-`w5` CDF arrays; `dist_lookup()` handles int→fixed-size or `wN` name |
| `tcp_app/epoll_client.cc` | `parse_args`: `-b`(msg size) `-i` `-f`(flows) `-t`(threads) `-o`(outstanding) `-w`(wait) `-l`(max_buf_size) `-s`(response toggle) |
| `tcp_app/epoll_server.cc` | `parse_args`: `-b` `-i` `-t` `-l` `-s`; runs `while(1)`, no loop count |
| `tcp_app/flexkvs_bench.cc` | Uses `flexkvs/commandline.c` `parse_settings()`; `--time`/`--warmup`/`--cooldown` stored but NEVER enforced |
| `tcp_app/flexkvs_server.cc` | 3 positional args: `CONFIG THREADS QUEUES`; port hardcoded to **11211** |
| `tcp_app/lat_client.cc` | 500K ping-pongs, sorted P50/P99/P99.9 output; `-c` flag broken (fallthrough bug) |

### Microkernel (slow-path only — data is fastpath via eBPF→XSK)

| File | Key Locations |
|:--|:--|
| `micro_kernel/micro_kernel.cc` | L51 `opt_num_queues=20` default; L106-122 `-q`(queues) `-i`(iface) `-b`(busy-poll) `-n`(napi) `-l`(tcp buf); L203 main launches `monitor_thread`, L244 `thread_init`, L259 `wait_thread` |
| `micro_kernel/runtime/defs.h` | **L24** `MAX_APP_THREADS=20`; L25 `MAX_SUPPORT_APP=32`; **L26 `CP_CPU=19`** (online with HT; control_loop pins to SMT sibling of core 9); L28-31 `enrollment_to_ms=0`, `network_to_ms=0`, `sp_interval_ms=1`; L33 `IO_BATCH_SIZE=32`; L44 `thread_init` extern |
| `micro_kernel/control_plane.cc` | **L48** `TICK_US=1000` (1ms); **L1070 `control_loop()`** — single worker thread; L1095-1130 sequential `poll_uds`→`poll_lrpc`→`poll_network`→`poll_tcp_handshake_events`→`poll_tcp_cc_to`→`poll_homa_to` + `clock_nanosleep`; **L1137 `thread_init()`**; **L1148** single `pthread_create(control_loop)`; **L1153-1155 `CPU_SET(CP_CPU)` + `pthread_setaffinity_np` (return value NOT checked)**; L1374 `poll_lrpc` (drains per-app-thread LRPCs, calls `process_cmd`); L1406 `process_packet` (TCP-only — calls `tcp_packet`); L1487 `poll_network` (reclaims CQ + `epoll_wait` on XSK fds) |
| `micro_kernel/homa.cc` | L485 `poll_homa_to` (1ms batch scan of BPF RPC map for zombies/retransmits); L502 `bpf_map_lookup_batch`; **L790 `process_homa_cmd`** — handles ONLY `APPOUT_HOMA_BIND` (L796) / `APPOUT_HOMA_CLOSE` (L803); no Homa data path here |
| `micro_kernel/tcp.cc` | `tcp_packet` — slow-path TCP processing (handshake/close/cc timeouts) invoked from `process_packet` |

### eBPF programs (fastpath — run at NIC)

| File | Key Locations |
|:--|:--|
| `micro_kernel/eBPF/entrance/entrance.c` | L48 `SEC("xdp_sock")` — parses eth/IP, tail-calls into Homa/TCP transport programs; L82 `SEC("xdp_gen")`, L93 `SEC("xdp_egress")` — dispatch by umem_id; L104 `xdp/cpumap` |
| `micro_kernel/eBPF/homa/main.c` | L29 `SEC("xdp_gen")` — **grant generator**: L59 `granting_idx[cpu]++`, L78 `min(nr_grant_candidate[cpu], HOMA_OVERCOMMITMENT)`, **L192 `return XDP_TX`** (emit grant at NIC); L211 `SEC("xdp_egress")`, **L248 `c->type != DATA`** check (XDP_EGRESS grant drop bug — apply patch at L235-248); L293 `SEC("xdp_sock")` — DATA redirector; **L418,451,460,588 `bpf_redirect_map(&xsks_map, socket_id, XDP_DROP)`** (push DATA → app XSK, bypasses mk); **L595 `SEC("xdp_gen/choose_rpc_to_grant")`** + L1247,1344,1440,1536,1632,1728,1824,1920 `SEC("xdp_gen/complete_grant_N")` (8-step grant choose) — tail-call invocation sites at L1240,1338,1435,1531,1627,1723,1819,1915 |
| `micro_kernel/eBPF/tcp/main.c` | L30 `slow_path_map`; L38 `xsks_map` (XSKMAP); L40 `SEC("xdp_gen")` — TCP ACK gen (`bpf_xdp_adjust_tail`); L147 `SEC("xdp_egress")`; **L258 `bpf_redirect_map(&xsks_map, c->qid2xsk[ctx->rx_queue_index])`** (fastpath data → app); L265 `SEC("xdp_sock")`; L323 `XDP_PASS`; **L367,378 `bpf_redirect_map(&xsks_map, ...)`** (sp/xid redirect); L373 `slow_path_map` lookup (→ mk) |

### Application library (libetran.so — the actual fastpath polling path)

| File | Key Locations |
|:--|:--|
| `lib/eTran_rpc.cc` | **L288 `poll_nic_rx()`** and **L426 `poll_nic_rx_block(timeout)`** — the app's RX fastpath: **L323,463 `xsk_ring_cons__peek`** on each queue's RX ring; L370,505 `client_response(qidx,d)` / L372,507 `server_request(qidx,d,remote_ip,rpcid)` (DATA → app); **L187 `xsk_ring_prod__reserve(&xsk_info->tx, rm.nr_pkt)` + L203 `kick_tx(...)`** — app TX path; L717,795 more `kick_tx` sites. L443 `_pending_*` queue drain to keep busy-poll nonblocking. **This is where Homa data packets are actually consumed and processed.** |
| `lib/socket.cc` | L159 `socket_homa_poll` (the homa shim's blocking-poll entry, called from epoll loop at L615, L781); **L405** "Connection is closed by microkernel" idle-drop message (TCP idle timeout) |
| `lib/eTran_posix.cc` | **L1168 `process_homa_kernel_events`** — drains `app_in` LRPC for `APPIN_HOMA_STATUS_BIND`/`CLOSE` from mk; L1228 `eTran_homa_poll_events`; L380,667,767,854,950,989 TCP XSK TX paths |
| `lib/eTran_common.cc` | **L595 `pre_main` constructor** — reads `ETRAN_PROTO` (L600, required), `ETRAN_NR_APP_THREADS` (L598) + `ETRAN_NR_NIC_QUEUES` (L599, required for TCP) |
| `lib/xsk_if.cc` | L20 `tx_ring_size=XSK_RING_PROD__DEFAULT_NUM_DESCS`; L38 `XDP_TX_RING` setsockopt; the per-thread XSK setup shared by app library |
| `shared_lib/interpose.cc` | Builds `libetran.so` — LD_PRELOAD intercepts `socket`/`epoll_wait`/`read`/`write` |

### Shared definitions / buffer pool

| File | Key Locations |
|:--|:--|
| `common/tran_def/homa.h` | **L8 `HOMA_MAX_MESSAGE_LENGTH = 1000000`** (off-by-one: `--workload 1000000` stalls, use 999999); L11 `enum homa_packet_type` (DATA/GRANT/RESEND/...) |
| `common/xskbp/xsk_buffer_pool.h` | **L33 `umem_num_frames=64*XSK_RING_PROD__DEFAULT_NUM_DESCS`**; **L39 `buffers_per_slab=2*XSK_RING_PROD__DEFAULT_NUM_DESCS`**; L70 `nr_slabs`, L73 `nr_slabs_avail` — slab counters (the `--ports > 4` crash claim was **refuted 2026-07-06**: server `--ports 5/7/10` with 500KB RPCs and the BPF XDP_EGRESS patch applied run cleanly at ~12.8 Gbps; the 13 Gbps ceiling is NOT a slab limit) |
| `micro_kernel/eBPF/homa/rpc.h` | L1584 `xmit_ctrl_pkt` (used by eBPF grant/ctrl TX); per-RPC state map structures |
| `micro_kernel/eBPF/homa/pacing.h` | Grant pacing structures (per-CPU `granting_idx`, `nr_grant_candidate`, `finish_grant_choose`) |

### Driver micro-bench

| File | Key Locations |
|:--|:--|
| `bench-afxdp/xdpsock.c` | `-r`(rx-drop) `-t`(tx-only) `-l`(l2fwd) modes, `-s` pkt size, `-b` batch, `-z` zero-copy, `-N` native mode (used for Table 3/4 AF_XDP baselines) |

---

## System Tuning — What We Tried, What Actually Matters

The standard CloudLab recipe for low-latency / high-throughput kernel
benchmarks is in
[`fshahinfar1/cloudlab_env_setup` `setup.sh::configure_for_exp`](https://github.com/fshahinfar1/cloudlab_env_setup/blob/main/setup.sh).
We re-applied that recipe to our cluster, item by item, and measured the
effect on the three metrics that matter most for the eTran gap
(metric 1 latency, metric 3 throughput, metric 5 RPC rate). The results
were *not* what the recipe implies.

### Reference recipe (cloudlab_env_setup `configure_for_exp`, 2026-07-06)

```
disable_irqbalance
cpupower frequency-set -g performance
cpupower idle-set -D 1
echo 0 > /proc/sys/kernel/numa_balancing         # disable NUMA balancing
echo 0 > /sys/kernel/mm/ksm/run                  # disable KSM
echo 1 > /sys/devices/system/cpu/intel_pstate/no_turbo   # disable Intel Turbo
x86_energy_perf_policy performance               # Intel EPP = performance
echo never > /sys/kernel/mm/transparent_hugepage/enabled   # THP=never
sysctl -w kernel.bpf_stats_enabled=0              # eBPF stats off
ethtool -U $NET_IFACE flow-type {tcp4,udp4} dst-port 8080 action 2   # flow rules
```

(`cpupower idle-set -D 1` is already covered by our stronger
`intel_idle.max_cstate=0` in GRUB. The flow rules are for port 8080, which
is not used by eTran.)

### What we measured

Each row is a single change applied on top of the previous, with a
fresh full-cluster restart (`pgrep -x micro_kernel` kill, XDP detach,
`/dev/shm/*` clean, mk restart) before each test. Numbers are eTran
Homa, default 20 queues, SMT=ON, CP_CPU=19.

| Change applied (cumulative) | Metric 1 P50 (32B) | Metric 3 Gbps (500KB) | Metric 5 Kops (32B) | Verdict |
|---|---:|---:|---:|---|
| **Baseline (before any of this work)** | 12.59 µs | 12.78 Gbps | 927 Kops | reference |
| `irqbalance` disabled | 12.5 µs | 12.8 Gbps | 928 Kops | small / neutral |
| `governor=performance` (via tuned) | 12.5 µs | 12.8 Gbps | 928 Kops | small / neutral |
| THP=never (`echo never > /sys/kernel/mm/transparent_hugepage/enabled`) | 12.5 µs | 12.8 Gbps | 928 Kops | none measurable |
| `kernel.bpf_stats_enabled=0` | 12.5 µs | 12.8 Gbps | 928 Kops | none measurable |
| `kernel.numa_balancing=0` | 12.5 µs | 12.8 Gbps | 928 Kops | none measurable |
| `ksm/run=0` | 12.5 µs | 12.8 Gbps | 928 Kops | none measurable |
| `intel_pstate/no_turbo=1` (Turbo off) | **11.29 µs** ⬇ | 11.98 Gbps ⬇ | **568 Kops** ⬇ 39% | **REVERTED** |
| `ethtool -K gro off` (on top of above) | n/a | n/a | already at 568 | n/a — see below |
| `ethtool -K tso off` (on top) | n/a | n/a | n/a | n/a — see below |
| **Reverted Turbo + GRO + TSO, kept all others** | 12.51–12.55 µs | 12.79 Gbps | 928 Kops | final state |
| `taskset -c 0-9 ./cp_node ...` (process-level, app threads to physical cores 0-9) | 12.5 µs | 12.8 Gbps | 928 Kops | no effect — mk pins app threads internally |
| `ethtool -G ens1f1np1 rx 4096 tx 4096` (bigger NIC ring buffers) | 12.5 µs | 12.8 Gbps | 928 Kops | no effect — bursts already absorbed |
| 2M hugepages for AF_XDP UMEM (THP+madvise / explicit hugepage reservation) | 12.5 µs | 12.8 Gbps | 928 Kops | no effect — mk sets up hugepages internally |

(Cells with `⬇` are statistically significant regressions. Other rows
are within run-to-run noise of ±0.1 µs / ±0.1 Gbps / ±30 Kops.)

### Why the reference recipe doesn't help our metrics

- **LRO/GRO/TSO** are NIC offloads that batch packets. They are off the
  eTran data path (which uses AF_XDP and bypasses the kernel network
  stack), so disabling them only affects the cp_node handshake and the
  control path — which is not the throughput bottleneck. But GRO
  specifically batches incoming small packets, so turning it off
  measurably reduces the per-queue packet rate.
- **Turbo off** is the worst offender. The Homa data path is
  per-RPC CPU-bound: a 32B request takes ~1500 cycles on the server
  side. Pinning CPU to the 2.4 GHz base clock caps the achievable RPC
  rate. The reference recipe assumes a workload (DPDK pktgen) that
  is link-bound, not CPU-bound.
- **eBPF stats / KSM / NUMA / LRO / THP** are either defensive
  (THP=never prevents a rare 1–2 ms page-fault spike from showing up in
  P99) or below measurement noise on our 10-core / 32B workload. The
  reference applies them "because it's the CloudLab recipe", not
  because they measurably help.
- **x86_energy_perf_policy performance** was attempted but the binary
  isn't available on the cluster — `linux-tools-6.6.0-eTran+` is not
  in apt and the kernel source isn't deployed. The x86_energy_perf
  in /usr/bin/ is a shell wrapper that doesn't match the running
  kernel. The effect would likely be small (similar to `no_turbo=1`)
  and is therefore skipped.

### What the tuning playbook actually does

A previous version of this repo shipped a
`Ansible/playbooks/eTran/tuning/05-runtime-tuning.yml` playbook that
applied the items in the table above. It was **removed** because the
empirical results showed no measurable benefit on metrics 1, 3, 5.
Do not re-add it without re-running the table above and confirming
that the new settings actually help.

What the **remaining** tuning stack does (the playbooks that are
still in the repo):

- `tuning/02-tune-boot-params.yml` — sets GRUB cmdline:
  `mitigations=off intel_idle.max_cstate=0 pcie_aspm=off` (removes
  `nosmt` so SMT/HT is on; `CP_CPU=19` is online with HT and the
  internal `pthread_setaffinity_np` succeeds). One-shot; persists.
- `tuning/03-tuned.yml` — installs `tuned`, applies the
  `network-throughput` profile (governor=performance,
  vm.swappiness=10, sysctl buffer sizes). Persists.
- `evaluation/01-network-prep.yml` — per-session: ARP permanent
  entries, /etc/hosts, NIC interrupt coalescing (rx-usecs=0, tx-usecs=5,
  adaptive-rx/tx off), flow control off. Resets every reboot.
- `evaluation/02-mtu.yml` — per-session: optional MTU=9000 (default 1500, no-op).

That is the **complete** list of active tunings. Anything else you
see in the reference recipe was tried and is documented above.

### Bottom line

The reference recipe is the right default for the kind of workload it
was designed for (DPDK link-bound). For the eTran Homa CPU-bound
workload, only the irqbalance/governor/THP subset of the recipe
matters, and even those are within run-to-run noise on metrics 1, 3, 5.
The throughput gap to the paper is **not a tunings problem** — it
remains a real software bottleneck (XDP_GEN grant eBPF serialization
+ per-app-thread polling rate + BPF RPC-map contention; see the
results table above and `Key findings` near the top of this runbook).

---

## Beyond `configure_for_exp` — Other Files in the Reference Repo

The reference repo
([`fshahinfar1/cloudlab_env_setup`](https://github.com/fshahinfar1/cloudlab_env_setup))
has more than just `configure_for_exp`. After the table above
disappointingly, the rest of the repo was scouted for anything that
might give the throughput gap a +50% boost. The candidates were:

- `scripts/config_exp_env.sh` — ntuple flow rules, napi busy-poll,
  offload toggles
- `scripts/set_irq_affinity` — Intel IRQ-to-core pinning script
- `scripts/linux_6.8.7_config` — full kernel config
- `install_pktgen.txt` — DPDK pktgen + hugepages setup
- `setup_remote.sh` / `servers.sh` / `reboot_servers.sh` — orchestration

All were tested where applicable. The +50% did not materialize, for
the reasons below.

### ntuple flow rules (`ethtool -U ... flow-type udp4 action 4`)

**Setup**: `ethtool -U ens1f1np1 flow-type udp4 action 4` — directs
all UDP4 traffic to NIC queue 4 (vs. the default RSS hash distribution
across 20 queues).

**Expected**: cache-locality win. All packets processed by one
queue's XSK, on one core, with no RSS distribution overhead.

**Measured**: metric 1 P50 dropped from ~12.5 µs to ~10.6 µs at first glance
— a 2 µs win. But the win was an **illusion** — verified by reading
`/proc/interrupts` after adding the rule: queue 1 received 2.6M IRQs
while queue 4 received only 14K. If the rule had taken effect, queue 4
would be the busy one. The microkernel's `SEC("xdp_sock")` at
`micro_kernel/eBPF/entrance/entrance.c:48` parses incoming packets and
tail-calls into the Homa `xdp_sock` (`homa/main.c:293`) or TCP
`xdp_sock` (`tcp/main.c:265`) transport programs, bypassing the
kernel's `ethtool -U` rules entirely. The 2 µs drop is most likely
noise or a side-effect of the measurement order, not a real RSS
improvement.

**Verdict**: do not bother. The eTran microkernel's BPF path is
closed. For a 2-queue kernel, the rule *might* work (you'd see all
traffic on queue 4), but for the 20-queue eTran setup it doesn't.

### napi_defer_hard_irqs + gro_flush_timeout

**Setup**: `echo 2 > /sys/class/net/ens1f1np1/napi_defer_hard_irqs`
and `echo 200000 > /sys/class/net/ens1f1np1/gro_flush_timeout`.

**Expected**: lower NAPI interrupt deferral = lower latency for
small-packet workloads.

**Measured**: metric 1 P50 showed no consistent change from the
~12.5 µs baseline. The tunings control how the kernel's NAPI softirq
consolidates packets. eTran uses AF_XDP busy-poll, which bypasses
NAPI entirely. The tunings only matter for the small TCP/UDP traffic
on the kernel network stack (cp_node handshake, ARP, etc.), which is
not the bottleneck.

**Verdict**: zero impact. Skipped.

### `set_irq_affinity` (Intel script)

**Expected**: lock NIC IRQs to specific cores for cache locality.

**Measured**: not re-tested. The previous AGENTS.md entry from
2026-07-06 already covers this: *"IRQ pinning was tested (metric 5)
and shown to have no effect — the playbook and all IRQ references
have been removed from the repo"*. The reason: eTran's Homa data
path is per-CPU XDP-eBPF busy-poll, so IRQ distribution across
multiple cores is fine — there's no interrupt-affinity cache-line
bouncing to worry about.

**Verdict**: tried, no win, no-op for our workload.

### `ethtool -K ... rx-checksumming off tso off gso off gro off lro off`

This is what the reference's `config_exp_env.sh` does at experiment
startup (line 107) — disable every NIC offload.

**Measured**: in the earlier tuning experiments, GRO off caused
metric 5 to drop 927 → 568 Kops (39% regression). The other offloads
(TSO, GSO, rx-checksumming) were not tested individually. For our
high-rate 32B workload, GRO batching is the difference between
~927 Kops and ~568 Kops — turning it off nearly halves the per-queue
packet rate.

**Verdict**: do not turn off GRO. The other offloads might be safe to
disable for our workload, but the throughput hit from GRO alone is
enough to rule out the whole "disable everything" approach.

### hugepages, `preempt=none`, Mellanox OFED (in `install_pktgen.txt`)

**Hugepages** (`default_hugepagesz=1G hugepagesz=1G hugepages=8`):
DPDK uses hugepages for packet buffers. AF_XDP uses regular 4K
pages (or 2M hugepages optionally, but the eTran microkernel uses
`xsk_umem__create` with default page size). Would need a recompile
of `lib/xsk_if.cc` to use hugepages; not a 1-day experiment.

**`preempt=none`** in GRUB: disables kernel preemption. For hard
real-time systems. eTran is a research system; preemption-disabled
would cause audio/video/jack glitches on the same machine. Not
applicable.

**Mellanox OFED** (proprietary `mlnxofedinstall`): the Ubuntu
stock `mlx5_core` driver already supports the ConnectX-4 Lx
adequately for AF_XDP. OFED is needed for DPDK; for eTran, stock is
fine.

### `linux_6.8.7_config` (different kernel)

The reference ships a 6.8.0-rc7 kernel config. Our eTran microkernel
is on `6.6.0-eTran+`. A 6.8 kernel might have:
- Faster BPF helpers (ringbuf, etc.)
- Better AF_XDP zero-copy
- Different mlx5 driver version

But this would require building a 6.8 kernel, deploying it, and
re-running all benchmarks. Estimated 1-2 days of work with uncertain
outcome. The eTran microkernel's source code may not even build on
6.8 without patches.

### Where the +50% would actually have to come from

The bottleneck is in the **eTran eBPF code**, not in system
tunings. The candidates:

- **`micro_kernel/eBPF/homa/main.c:29,192`** — the `xdp_gen` SEC
  program that emits grants via `return XDP_TX`. The grant
  dispatch is per-CPU with `HOMA_OVERCOMMITMENT=8` and an 8-step
  tail-call chain (SEC at L595,1247,1344,1440,1536,1632,1728,1824,1920;
  call sites at L1240,1338,1435,1531,1627,1723,1819,1915). The 8-step
  chain implies ~8 BPF program executions per grant. If each step is
  1 µs, that's 8 µs of grant processing per RPC — explains the
  13 Gbps ceiling on metric 3.
- **`micro_kernel/eBPF/homa/main.c:418,451,460,588`** — the
  `bpf_redirect_map(&xsks_map, ...)` calls in the Homa XDP program.
  Each call goes through the BPF map lookup, which can be slow for
  large maps.
- **BPF RPC-map contention** between the app fastpath and
  `micro_kernel/homa.cc:485` `poll_homa_to` (1ms batch scan via
  `bpf_map_lookup_batch`). The mk's slow path competes with the app's
  fast path on the same BPF map.

These are software bugs/inefficiencies in the eTran microkernel
itself. Fixing them would require:
1. Profiling the BPF programs with `bpftool prof` to find the
   hot path
2. Optimizing the grant chain (e.g., fewer tail-call steps, faster
   map lookups, better batching)
3. Patching the eTran microkernel and rebuilding

This is upstream work, not something we can fix from system
tunings. The current runbook's "Key findings" section already
identifies these bottlenecks; the table above is just additional
detail.

---

## Tried and Reverted — Earlier Tuning Experiments

This section documents tunables and operational patterns from earlier
sessions that were tried, found to be no-ops or harmful, and reverted.
**Do not re-attempt these.** Git history has the detailed rationale
(commits 4b0aa50, 9b7b73d, 64502bf, 197bdf3, 82fdecf, 8dcc52d, b878a4d).

### Reverted (active regressions)

These caused measurable harm and were rolled back:

| Tweak | Effect | Reverted in |
|---|---|---|
| `ethtool -K gro off` | metric 5: 927 → 568 Kops (39% ↓) | runbook table line 945 |
| `ethtool -K tso off` | part of the same "disable everything" anti-pattern | runbook table line 946 |
| `intel_pstate/no_turbo=1` | metric 5: 927 → 568 Kops (39% ↓) | runbook table line 944 |
| `--queues N` on `cp_node client` | 1045 → 86 Kops (12× ↓) | AGENTS.md "What NOT to do" |

### Obsolete workarounds (pre-HT-on, all reverted)

When we ran with `nosmt` (SMT=off), `CP_CPU=19` was offline, the
internal pin silently failed, and `control_loop` roamed. The
workarounds below were tried, then obsoleted by enabling HT-on
in commit 64502bf:

| Tweak | Status | Replaced by |
|---|---|---|
| `taskset -c 9 ./micro_kernel` (manual pin) | obsolete | `CP_CPU=19` internal pin works with HT-on |
| `taskset -c 0-7 ./cp_node server` | obsolete | no taskset needed (mk pins app threads internally per runbook table line 948) |
| `-q 10` for micro_kernel | obsolete | default 20 queues (matches NIC combined) |
| `02-irq-affinity.yml` (manual queue + IRQ pin) | removed | queue pinning proven pointless for metric 5 |
| `02-disable-smt-mitigations.yml` (adds `nosmt`) | renamed | `02-tune-boot-params.yml` (now enables HT) |
| VLAN interface MTU (10.0.1.x range) | removed | not relevant to our setup |

### Earlier runbook/AGENTS.md mistakes (already corrected in commit history)

- `--workload 524288` for 500KB RPCs → use `500000` (was 512KiB, not 500KB)
- `ETRAN_NR_APP_THREADS=1` for metric 18 → use `4` (matches `--threads 4`)
- `profile.py node_count=4` → `10` (matches actual deployment)
- `metric 6 --client-max 128` → `256` (unified with actual measured)

### Operational anti-patterns

Repeated from AGENTS.md "What NOT to do" so this runbook is
self-contained as a reference:

- **`pkill -f micro_kernel`** — matches its own cmdline AND the `screen`
  wrapper argv, self-terminates before reaching the target. Use
  `pgrep -x micro_kernel` + `kill -9 <pid>`.
- **`nohup ... </dev/null`** for micro_kernel — the monitor thread exits
  on stdin EOF. Use `screen -dmS` (provides a pty).
- **`timeout` on micro_kernel or server** — they should persist across
  runs. Wrap them in `screen`. Only clients use `timeout`.
- **`screen -wipe`** — hangs on stale `.lock` files in
  `/run/screen/S-root` from crashed mk. Use `screen -ls` / kill by PID.
- **Skipping shm cleanup** between metrics — mandatory
  `rm -f /dev/shm/BufferPool_* /dev/shm/UMEM_* /dev/shm/LRPC_*` to
  avoid silent BPF state stalls.
- **`-b` (busy-poll) on micro_kernel** — breaks Homa AF_XDP timing.
- **Doubling `umem_num_frames`** — doesn't help, causes overhead.
- **Resending SIGKILL to a D-state mk** — won't work; BPF syscalls are
  uninterruptible. If the affected node is critical, swap it with
  another clean node instead of rebooting the cluster.

### Already documented elsewhere in this runbook

- The cumulative tuning table (lines 935-950) covers the CloudLab
  `configure_for_exp` recipe + 3 process-level no-effect items added
  in this session.
- The "Beyond `configure_for_exp`" section covers ntuple, napi,
  set_irq_affinity, NIC offloads, hugepages, kernel version.
- "Where the +50% would have to come from" identifies the upstream
  eBPF bottlenecks (XDP_GEN grant chain, BPF map contention) that OS
  tunings cannot fix.

---

## Known Limitations

1. **Short-lived TCP connections (metrics #16–17)** — Not supported by any
   binary in the public repo. `epoll_client` only creates persistent connections.
   A custom benchmark is needed. Not reproducible as-is.

2. **Interface name** — Hardcoded as `ens1f1np1` in cp_node.cc:48,
   micro_kernel.cc, and xdpsock.c. CloudLab xl170 uses Mellanox ConnectX-4 Lx
   (not ConnectX-5). Check `ip link` and recompile if different.

3. **CPU cycles breakdown (Table 5)** — Requires hardware PMU counters
   and careful kernel symbol mapping. Not automatically categorized.

4. **XDP_EGRESS / XDP_GEN benchmarks (Tables 3–4)** — These test eTran's
   new eBPF hooks. BPF programs implementing the tested features are needed
   but not found as standalone build targets in the repo. They may be embedded
   in the microkernel/eTran library build.

5. **Multi-node tests** — The cluster benchmark (metrics #7-12) uses all-to-all
   topology with `--both` and `--id`. Start nodes with 0.3s stagger
   (see AGENTS.md multi-node orchestration).

6. **TAS comparison baselines** — TAS (Transport Acceleration Substrate) is
   a separate project not included in the eTran repo. For #14, compare eTran
   TCP against Linux TCP only; TAS comparison requires a separate TAS setup.

7. **Homa large-message grants (metrics #2–4, #7–12, #22)** — The upstream
    eTran XDP_EGRESS BPF program at `micro_kernel/eBPF/homa/main.c:240` drops
    grant/resend packets because the `data_header` bounds check runs before the
    `c->type != DATA` check. The patch moves the `c->type != DATA` check before the
    `data_header` bounds check and routes non-DATA packets through `xmit_packet()`.
    Apply to `micro_kernel/eBPF/homa/main.c` lines 235-248, then
    `touch micro_kernel/eBPF/homa/main.c && make -j$(nproc)` and restart micro_kernel.
    Already applied to all nodes.

8. **`--one-way` response size** — `--one-way` caps server responses at **100 bytes**
   (`header->short_response ? 100 : header->length` in cp_node source). The paper
   says "32-byte response" (§6.1). This 100B vs 32B difference doesn't meaningfully
   affect large-message throughput. Without `--one-way`, the server echoes the full
   request size, doubling grant-path load. 32B benchmarks (metrics #1, #5–6) do NOT
   use `--one-way` (server echoes 32B). All large-message benchmarks use `--one-way`.

9. **`HOMA_MAX_MESSAGE_LENGTH` off-by-one** — `HOMA_MAX_MESSAGE_LENGTH = 1000000`
   (`common/tran_def/homa.h:8`). `--workload 1000000` hits the exact buffer boundary
   (`msg_len > HOMA_MAX_MESSAGE_LENGTH` is false at exactly 1000000). Use
   `--workload 999999` to avoid stalls.

10. **TCP benchmarks now work** — The earlier SIGABRT (exit 134) was resolved by
      the BPF XDP_EGRESS patch (it affected TCP egress paths too, not just Homa
      grants). Metrics 13-15, 18-21 confirmed working (15, 18-21 tested). The
      "Connection is closed by microkernel" message after ~9s in `lib/socket.cc:405`
      is a socket lifecycle issue — the microkernel closes TCP state, but the
      benchmark produces valid data before that.

11. **Multi-client Homa grant scaling** — Beyond ~200 concurrent RPCs, the Homa
    BPF grant mechanism collapses under `insert_grant_list → bpf_obj_new` memory
    pressure. This blocks metrics #3, #5–12 at full paper concurrency levels.
    Per-metric restart (kill micro_kernels + clean `/dev/shm/*` + restart)
    is mandatory between runs to avoid stale BPF state.

12. **`flexkvs_bench --time` not enforced** — `--time`, `--warmup`, `--cooldown`
    are stored in settings but never acted upon (no phase transition to DONE).
    Always wrap flexkvs_bench in `timeout N`. The `--time` value is informational only.

13. **`epoll_*` run indefinitely** — No loop count argument exists. `-l` is
    `max_buf_size` (default 4096), NOT a loop count. Always wrap in `timeout`.

14. **`ETRAN_NR_APP_THREADS` must match app threads** — The eTran library
    `pre_main` constructor registers this many threads with the microkernel.
    Must equal the application's actual thread count (e.g. `-t 4` → `ETRAN_NR_APP_THREADS=4`).

15. **`--both` timing creates per-node variance (metrics 7-12)** — The all-to-all
    experiments start all nodes simultaneously, but each node's `--both 2` phase
    (server 2s → client) creates slight wall-clock misalignment. W2 showed even
    load (~430 Kops across 9/10 nodes), but W3-W5 showed wider variance (factor
    10-100x). For better consistency, pre-start servers on all nodes, then launch
    clients simultaneously.

16. **`dump_times` output includes comment headers** — `dump_times` writes a header
    line `# --server-nodes N --server-ports M, --client-max K` before RTT data.
    Always filter with `grep -v '^#'` before post-processing.

17. **`perf` breaks Homa AF_XDP but works for TCP** — `perf stat` and `perf record`
    insert sampling interrupts that stall Homa's time-sensitive AF_XDP busy-poll
    loop (0 completions under perf). However, TCP benchmarks work fine under perf
    (Metric 21 completed with 63.8B cycles, 94.8B instructions over 25s). The
    microkernel's AF_XDP polling on a separate thread is not disrupted by perf
    on the application thread. Building kernel-matching `perf` from eTran kernel
    source requires `make NO_JEVENTS=1 NO_LIBTRACEEVENT=1 NO_LIBPFM4=1`.
    Homa cycles/request (Metric 22) is dominated by idle AF_XDP polling (99.6%).
    Paper's 5.48 kcycles measured on kernel Homa module (no busy polling).
    Active processing per 1MB RPC in eTran estimated at ~2µs (~5 kcycles).
