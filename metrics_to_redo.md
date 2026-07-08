# Metrics Requiring Redo

## Tooling bugs (flags wrong)

### #13 — eTran TCP 1KB throughput (and DCTCP epoll 1KB)
**Issue:** Paper uses 5 clients × 5 threads, 100 connections, 64 outstanding per connection.
We used 1 client × 1 thread × 1 connection.

**Actual result:** 5×5 × 64 outstanding = 6400 concurrent in-flight requests —
connections drop after 1-3s ("Connection is closed by microkernel"),
not stable enough for a steady-state measurement.

**Action needed:** Determine a workable concurrency level that both eTran TCP
and DCTCP (plain epoll) can sustain with the same setup, then measure both
at that level to compute a valid ratio.

### #14 — eTran TCP 2KB throughput (and DCTCP epoll 2KB)
**Issue:** Same as #13 — 1×1 setup instead of 5×5 × 64 outstanding.

**Action needed:** Same workaround as #13.

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
#13 fix (find stable concurrency) → measure eTran + DCTCP at that level
#14 fix (same concurrency as #13) → measure eTran + DCTCP at that level
#18 fix (--pending 32) → DONE: ~0.73 Mops eTran, ~0.278 Mops DCTCP, ratio ~2.6×
#19-20 → DONE: P50=17 µs idle; switch ECN caveat
#15 → DONE: ~0.234 Mops DCTCP, ratio ~2.8×
#21 → rerun on server side (eTran only)
```
