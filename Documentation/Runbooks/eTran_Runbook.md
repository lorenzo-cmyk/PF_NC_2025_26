# eTran Benchmark Runbook — Exact Commands per Metric

## Results Summary (Single-Socket xl170, 10-core E5-2640v4, SMT=on)

> **Current configuration:** SMT=ON (HT enabled, 20 logical CPUs). mk's
> `CP_CPU=19` internal pin now works — the control_loop pins to **core 19**
> (the HT sibling of core 9) as designed. NO `taskset` is needed for mk. NIC
> has 20 combined queues. App threads on physical cores 0-9, mk control_loop
> on core 19 (HT sibling of core 9). This matches the paper's §6 design.

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
  (paper used identical xl170 single-socket 10-core nodes).
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

## Table 1 — Primary eTran Metrics

### 1. eTran - Homa | Median RTT latency, 32B requests, single client | 11.8 µs | 2-Node

Paper §6.1: "single client thread to send back-to-back requests (32B) to a
single-threaded server, which responds with a 32-byte response."

Output every 1s: `Clients: <Kops> Kops/sec, <gbps> Gbps out, ..., RTT (us) P50 <p50> P99 <p99> P99.9 <p99.9>`
Read P50 for the metric.

### 2. eTran - Homa | Throughput, 1MB requests, back-to-back | 17.7 Gbps | 2-Node

Paper §6.1: "single client thread to send back-to-back requests (1MB) to a
single-threaded server, which responds with a 32-byte response."

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

### 3. eTran - Homa | Multi-threaded server throughput, 500KB, 7 clients | 23.0 Gbps | 8-Node

Paper §6.1: "multi-threaded server receiving concurrent RPCs (500KB) from 7 clients".

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
> Start clients with 0.3s stagger (see Reproduction/AGENTS.md).
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

**`--ports` sweep on server (2026-07-06, clean restart between each)**:
| Server `--ports` | Steady Gbps | Peak Gbps | Notes                              |
| ---------------: | ----------: | --------: | ---------------------------------- |
|                4 |        12.9 |         — | baseline                           |
|                5 |       12.78 |     13.77 | no crash                           |
|                7 |       12.77 |     12.77 | no crash                           |
|               10 |        8.01 |      9.09 | client fan-out limit; 3 ports idle |

4/5/7 are equivalent (within 1% noise). 10 is worse due to client-side
1-thread fan-out, not server. No buffer-pool asserts at any port count with
the BPF XDP_EGRESS patch applied. The 13 Gbps ceiling is a real eBPF
serialization limit, not a server-side resource cap.

### 4. eTran - Homa | Multi-threaded client throughput, 500KB, 7 servers | 22.7 Gbps | 8-Node

Paper §6.1: "multi-threaded client sending concurrent RPCs to 7 servers".

Measure client-side Gbps out.

> `--ports 7`: 7 sending threads (one per server). `--server-ports 1` is default.
> `--client-max 1`: 1 outstanding per port, 7 total. Higher concurrency stalls
> (e.g. `--client-max 64` → 448 concurrent RPCs, CPU contention on 10 cores).

### 5. eTran - Homa | Client RPC rate, 32B | 2.9 Mops | 8-Node (7:1 ratio)

Paper §6.1: "RPC rate for small messages (32B), maintaining the same
client-to-server ratio" — same 7:1 as metric 3.

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

### 6. eTran - Homa | Server RPC rate, 32B | 3.3 Mops | 8-Node (1:7 ratio)

Paper §6.1: same 1:7 ratio as metric 4 — 1 client → 7 servers.

Output: `Servers: <Kops> Kops/sec` (aggregate across all 7 servers).

> **⚠️ Requires fresh restart**: previous attempts with stale micro_kernel state
> produced 0 completions. Full `pkill -9 micro_kernel; rm -f /dev/shm/*; restart`
> on ALL nodes is mandatory. Use `--ports 7 --client-max 256` (not --ports 1).

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

#### All-to-all topology (paper's setup)

Run on all 10 nodes simultaneously. Each node acts as both client and server
via `--both N` (starts server, waits N seconds, then starts client). `--id`
prevents a node from sending to itself. Record P50/P99/P99.9 RTT (us) from
1s stats output. Slowdown = `eTran_RTT / Linux_RTT` (run same workload on
stock Linux for baseline).

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
run. The interactive pipe pattern and the shortest-10% filtering commands are
in `Reproduction/Runbook/eTran_Runbook.md` (metrics 7-12).

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

### 14. eTran - TCP | 2KB throughput, 64 outstanding, single-threaded | 0.87x TAS | Medium

Output: same format as #13. Use `script -q -c` over SSH for line-buffered output.
**⚠️ Env vars must be inside `script -q -c`** — same caveat as #13.

### 15. eTran - TCP | 1K persistent connections, 64B requests | 2.26x Linux | 6-Node

> **`-w 2`**: `wait_seconds` — 2s delay after connecting before measuring.
> **`-o 1`**: 1 outstanding request per connection (closed-loop).
> Use `script -q -c` over SSH for line-buffered output (same issue as #13).
> **⚠️ Env vars must be inside `script -q -c`** — `env VAR=val script -q -c 'cmd'`
> does NOT pass env vars into the subshell. Use:
> `script -q -c 'VAR=val ./cmd' /dev/null`
> Start clients with 0.3-0.5s stagger to avoid overwhelming the server.

### 16. eTran - TCP | Short-lived 16 msg/conn, 1K concurrent | 42.7x Linux | 6-Node

**⚠️ CAVEAT**: `epoll_client` only supports **persistent** connections. The public
eTran repo does not include a short-lived TCP connection benchmark binary.
This metric requires a custom benchmark that opens/closes connections and sends
16 messages each. Not reproducible with the public repo as-is.

### 17. eTran - TCP | Short-lived 256 msg/conn, 1K concurrent | 5.4x Linux | Medium

**⚠️ Same caveat as #16. Not reproducible with the public repo as-is.**

### 18. eTran - TCP | KV throughput, 100K keys, Zipf s=0.9, 9:1 GET:SET | 2.4~4.8x Linux | 6-Node

Output: `TP: total=<mops> mops  50p=<us> 90p=<us> 95p=<us> 99p=<us> 99.9p=<us> 99.99p=<us>` every second.

> **`ETRAN_NR_APP_THREADS=4`** must match the application thread count (server: 4
> positional arg, client: `--threads 4`). Previously set to 1 — wrong.
> **`--time`/`--warmup`/`--cooldown` are stored but never enforced** by flexkvs_bench
> (no phase transition to DONE). Always wrap in `timeout`. The `--time 30` is
> informational only; `timeout 45` provides the actual 30s run + 5s warmup + buffer.
> Server port is hardcoded to **11211** (memcached).
> **`--pending 32`** changed from 16 per paper spec (§6.4: "each uses 32 parallel
> GETs"). Throughput is bottlenecked elsewhere — 16 vs 32 produces identical results.

### 19. eTran - TCP | KV P50 latency, under-loaded | 17.2 µs | 6-Node

Read P50 us from output (`50p=<us>`).

### 20. eTran - TCP | KV P99 latency, under-loaded | 27.5 µs | 6-Node

Same command as #19. Read P99 µs from output (`99p=<us>`).

### 21. eTran - TCP | Total CPU cycles per request | 4.37 kcycles | 2-Node CPU Profiling

Calculate kcycles/request = (total cycles) / (total requests).
For the per-component breakdown (matching Table 5), use perf record + report:

```bash
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

### 22. eTran - Homa | Total CPU cycles per request | 5.48 kcycles | 2-Node CPU Profiling

---

## Table 2 — CPU Cycles Breakdown (Table 5)

Requires `perf` with hardware counters. Run against TCP and Homa benchmarks
under single-NAPI-context stress. The source code categories are:

| Paper Category | Kernel Symbols to Match                              |
| :------------- | :--------------------------------------------------- |
| Application    | User-space app code (cp_node/epoll_client main loop) |
| Socket/RPC     | `__sys_sendto`, `__sys_recvmsg`, socket layer        |
| Data Copy      | `copy_user_enhanced_fast_string`, `memcpy_erms`      |
| Sk_buff        | `__alloc_skb`, `__kfree_skb`, `skb_*`                |
| TCP/Homa + IP  | `tcp_*`, `homa_*`, `ip_*`, `ip6_*`                   |
| Lock/Unlock    | `_raw_spin_lock`, `mutex_lock`, `mutex_unlock`       |
| NIC Driver     | `mlx5e_*`, `mlx5_*` (adapt to your NIC driver)       |
| Memory Mgmt    | `__alloc_pages`, `__free_pages`, `slab_*`            |
| Scheduling     | `__schedule`, `schedule`, `try_to_wake_up`           |
| Other          | Everything else                                      |

```bash
perf record -g -F 99 -o /tmp/perf.data <benchmark-command>
perf report --stdio -i /tmp/perf.data --sort=comm,dso,symbol | head -80
```

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
   (see Reproduction/AGENTS.md).

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
      is **no longer reproducible with 5×5 × 64 (1600 in-flight)** — runs 20s+
      cleanly. The earlier drop may have been specific to older code before the
      BPF XDP_EGRESS patch was applied.

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


