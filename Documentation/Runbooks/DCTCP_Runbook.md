# DCTCP Benchmark Runbook — Exact Commands per Metric

> Two benchmark suites are used:
> - **HomaModule `cp_node`** (`/local/HomaModule/util/cp_node`) with `--protocol tcp`
>   for RPC-style metrics (latency, multi-node throughput, RPC rate).
> - **eTran `epoll_*`** (`/local/eTran/eTran/tcp_app/`) **without `LD_PRELOAD`**
>   for raw TCP streaming throughput (same binaries as eTran TCP metrics,
>   running on standard kernel TCP stack instead of AF_XDP).
>
> Pre-flight: ensure DCTCP is configured on all nodes (see `playbooks/DCTCP/setup/site.yml`).
> Network is assumed pre-configured by eTran's evaluation playbooks (ARP, `/etc/hosts`, NIC tuning).
>
> DCTCP uses the **standard Linux TCP stack** with DCTCP congestion control + ECN.
> No micro_kernel, no eTran XDP/BPF, no LD_PRELOAD needed.

## Results Summary

Hardware: CloudLab xl170, single-socket 10-core E5-2640v4, Mellanox ConnectX-4 Lx 25G, SMT=on.

> **Metric numbering is LOCAL to this runbook.** Mapping to
> `eTran_reproduction_metrics.md`: local #7→metric 13, #8→14, #13→15, #10→18,
> #11→19, #12→20, #9→21. Local #1–#6 are extra DCTCP baselines (TCP equivalents
> of the Homa metrics 1–6) with no separate row in the main metrics doc.

## Key Findings

- **Large-message throughput saturates the 25G link** (metrics 2-4): DCTCP over the
  mature Linux TCP stack fills the NIC for bulk transfers. The ~21.5-23.5 Gbps
  range equals or beats eTran Homa's best throughput (16.6 Gbps for 1MB, 12.9 Gbps
  for 500KB × 7). The standard kernel TCP stack is highly optimized for bulk data.
- **Small-message RPC rate is competitive** (metrics 5-6): ~866-1082 Kops/sec vs
  eTran Homa's ~927-1120 Kops/sec. DCTCP's RTT P50 (~64-75 µs) is far better than
  Homa's (~217-460 µs) for these workloads because there's no AF_XDP polling or
  BPF map contention.
- **TCP streaming throughput** (metrics 7-8): Using the same `epoll_client` binary
  as eTran TCP metrics, DCTCP achieves ~1.8-2.8 Gbps (1KB)
  and ~1.8-4.6 Gbps (2KB). This is **~2.6-3.95× lower** than eTran's AF_XDP-accelerated
  TCP (~7.2 Gbps / ~12.3 Gbps), confirming that eTran's AF_XDP data-path bypass
  provides significant throughput gains for small-to-medium messages — the kernel
  TCP stack's softirq processing and syscall overhead are the bottleneck.
  Switch ECN marking IS enabled on the SN2410, but DCTCP throughput still varies
  2-3× run-to-run (mechanism unresolved — see metric 7 note), so single-point
  ratios are unreliable.
- **CPU efficiency** (metric 9): DCTCP uses ~7.4 kcycles/request for 1KB messages,
  ~2.6× more than eTran's AF_XDP TCP (~2.9 kcycles). The kernel TCP stack spends
  ~12s sys vs ~0.8s user, showing the overhead is entirely in kernel TCP processing.

## Metric 1: DCTCP 32B Latency (Echo, Single Stream)

Output: `tcp_32 clients: ... RTT (us) P50 <p50> P99 <p99> P99.9 <p99.9>`

## Metric 2: DCTCP 1MB Throughput (Single Stream)

Output: `tcp_999999 clients: ... Gbps out ...` — read Gbps out.

> `--workload 999999` avoids `HOMA_MAX_MESSAGE_LENGTH` off-by-one (1M boundary).
> `--one-way` = 100B response (not an echo of 1MB). This is the Homa convention
> for throughput measurement — for TCP the response size has negligible impact on
> 1MB send throughput.

## Metric 3: DCTCP 500KB Throughput — 7 Clients → 1 Server

Start clients with 0.3s stagger (see Reproduction/AGENTS.md).

## Metric 5: DCTCP 32B RPC Rate — 7 Clients → 1 Server

Output: server-side `Kops/sec` from server screen log. Client-side per-client
Kops also available.

## Metric 6: DCTCP 32B RPC Rate — 1 Client → 7 Servers

Output: client-side `Kops/sec` (aggregate across all servers).

## Metric 7: DCTCP 1KB Throughput (epoll, Streaming)

Output: `Throughput In/Out(<gbps>/<gbps> Gbps)(<kops> Kops)`

> `-b 1024` = 1KB messages, `-o 64` = 64 outstanding, `-f 1` = 1 flow, `-t 1` = 1 thread.
> Default (`-s` omitted): `short_response=true` → server sends 100B response.
> **C buffering**: use `stdbuf -oL` or `script -q -c` over SSH (see pre-flight).
> The server's `-b` must match the client's `-b` (receive buffer size).

## Metric 9: DCTCP CPU Cycles per Request (epoll, 1KB)

Calculate: `cycles_per_request = total_cycles / (avg_Kops × active_seconds)`

## Metric 10: DCTCP KV Throughput (flexkvs, plain TCP)

> **`--pending 32`** matches the paper spec (§6.4: "each uses 32 parallel GETs").
> The eTran TCP run previously used `--pending 16`; changing to 32 had no
> throughput effect — the bottleneck is elsewhere (likely single-pending-RPC
> limit per connection × 10 connections = only 10 in-flight per client thread).

## Metric 11-12: DCTCP KV P50/P99 Latency (flexkvs, plain TCP, under-loaded)

**P50 latency vs concurrency sweep (5 clients, varying per-client pipeline):**

| Config     | Total in-flight | Mean P50  | Throughput |
| ---------- | --------------- | --------- | ---------- |
| 1t×1c×1p   | 5               | ~24 µs    | ~0.21 Mops |
| 1t×1c×4p   | 20              | ~22 µs    | ~0.21 Mops |
| 1t×1c×8p   | 40              | ~27 µs    | ~0.18 Mops |
| 1t×4c×8p   | 160             | ~41 µs    | ~0.39 Mops |
| 1t×4c×16p  | 320             | **36 µs** | ~0.45 Mops |
| 4t×10c×32p | 6400            | ~740 µs   | ~0.27 Mops |

> **Paper discrepancy**: The paper reports Linux-TCP KV latency as 64.2 µs P50.
> Our DCTCP P50 caps at ~47 µs regardless of client concurrency.
> NOTE (corrected 2026-07-18): an earlier version of this note claimed switch
> ECN marking was "not configured in our cluster" — that was wrong: ECN marking
> IS enabled on the SN2410 (exact threshold/mode not yet recorded here —
> document it next session). The earlier theory ("70KB standing queue adds
> ~22 µs to the under-loaded P50") was also flawed: the under-loaded test
> (1 thread × 1 conn × 1 pending) never builds a queue, so marking cannot
> affect it. The paper's higher 64.2 µs P50 more plausibly reflects
> base-latency/kernel-path differences on their testbed. Marking only matters
> under load (see the concurrency sweep above), where the comparison is
> threshold-dependent.

## Metric 13: DCTCP 1K Persistent Connections, 64B Closed-Loop (epoll, plain TCP)

> Unlike eTran TCP metric 15 (which could drop connections after ~9s in older code —
> no longer reproducible post-BPF XDP_EGRESS patch), the DCTCP baseline ran
> cleanly for the full 20s window.
> The 2.8× ratio is consistent with the eTran TCP throughput advantage seen in
> other metrics (metric 13: ~3.95× at 1KB, metric 18: ~2.62× at KV).

