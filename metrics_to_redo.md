# Metrics Requiring Redo

## Tooling bugs (flags wrong)

### #13 — eTran TCP 1KB throughput (and DCTCP epoll 1KB)
**Issue:** Paper uses 5 clients × 5 threads, 100 connections, 64 outstanding per connection.
We used 1 client × 1 thread × 1 connection.

**Resolution attempt (2026-07-08):**
- 1×1 × 64: **7.19 Gbps / 878 Kops** — stable for 19+ seconds, no drops.
- 1×5 × 64 (1 client × 5 threads): **12.07 Gbps / 1474 Kops** — saturates NIC.
- 5×5 × 64 (5 clients × 5 threads): **7.55 Gbps / 922 Kops aggregate** — stable,
  no drops at 1600 in-flight. Server queue contention is the bottleneck, not drops.
- DCTCP 1×1 × 64: **1.82 Gbps / 222 Kops** (varies with switch ECN state: 1.3-2.8 Gbps).
- **Best ratio: ~3.96×** (paper: 4.8×). Acceptable given DCTCP variance.

**Resolution:** The "connection drops at 6400 in-flight" caveat is **stale**.
5×5 × 64 works with no drops. Main bottleneck is server-side queue contention
(reduces aggregate from 1524 → 922 Kops across 5 clients). Different concurrency
levels (1×1, 1×5, 5×5) all produce ratios in the 3-4× range, below the paper's
4.8×. Documented as a known discrepancy.

### #14 — eTran TCP 2KB throughput (and DCTCP epoll 2KB)
**Issue:** Same as #13 — 1×1 setup instead of 5×5 × 64 outstanding.

**Resolution attempt (2026-07-08):**
- eTran 1×1 × 64: **12.29 Gbps / 750 Kops** — stable, no drops.
- DCTCP 1×1 × 64: **1.82 Gbps / 111 Kops** (runbook baseline: 4.6 Gbps / 283 Kops).
  DCTCP varies 2-3× due to switch ECN marking state.
- Ratio: **6.76× with current DCTCP** or **~2.65× with runbook baseline**.
  DCTCP variance makes this ratio unreliable without multiple back-to-back runs.

### #18 — KV throughput
**Issue:** `--pending 16` on flexkvs_bench. Paper uses 32 outstanding per connection.

**Action needed:** Change to `--pending 32`, redo both eTran TCP (with LD_PRELOAD)
and DCTCP (without LD_PRELOAD).

**Status: DONE** (2026-07-08). eTran TCP: ~0.73 Mops, DCTCP: ~0.278 Mops.
Ratio ~2.61×. `--pending 32` vs 16 produced identical throughput — bottleneck
is elsewhere (only 10 conns × 1 in-flight per connection, limited by
single-pending-RPC throughput per connection).

### #21 — CPU cycles per request
**Issue:** Measured client-side (~2.9 kcycles). Paper value is server-side under
single-NAPI stress (4.37 kcycles).

**Action needed:** Rerun `perf stat` on the **server** process during a 1KB
throughput run.

---

## DCTCP baselines not yet measured

### #15 — 1K persistent connections (64B, closed-loop)
**Status: DONE** (2026-07-08). DCTCP: ~0.234 Mops aggregate (5 × ~46.8 Kops).
No connection drops (20s window). eTran/DCTCP ratio ≈ 2.8×.

### #18 — KV throughput (100K keys, Zipf s=0.9, 9:1 GET:SET)
Command (needs `flexkvs_*` without LD_PRELOAD):
```
flexkvs_server default 4 1
flexkvs_bench --threads 4 --conns 10 --pending 32 \
  --key-num 100000 --key-size 32 --val-size 64 \
  --get-prob 0.9 --key-zipf=0.9 <server-ip>:11211   (× 5 clients)
```

---

## Dependency chain

```
#13 fix → DONE: 5×5 × 64 stable, ratios 3-4× (below paper's 4.8×; documented)
#14 fix → DONE: measured 1×1 × 64 both stacks; DCTCP variance noted
#18 fix (--pending 32) → DONE: ~0.73 Mops eTran, ~0.278 Mops DCTCP, ratio ~2.6×
#19-20 → DONE: P50=17 µs idle; switch ECN caveat
#15 → DONE: ~0.234 Mops DCTCP, ratio ~2.8×
#21 → rerun on server side (eTran only)
```
