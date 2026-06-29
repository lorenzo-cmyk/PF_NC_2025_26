# eTran Execution Log

## Hardware
- **CPU**: 2× Intel Xeon E5-2640v4 @ 2.40 GHz (10 core, SMT-2)
- **NIC**: Mellanox ConnectX-4 25 Gbps (ens1f1np1)
- **Nodes**: node0 (server), node1 (client)
- **NIC tuning**: governor=performance, tx-frames=128, ring=2048

## Status Summary

| Measure | Description | Status | Result |
|:---|:---|:---|:---|
| 1a | Homa latency 32B | ✅ | 10.2 µs (beats paper 11.8) |
| 1b | Homa TP 1MB (cm=2) | ✅ | 20.8 Gbps (beats paper 17.7) |
| 1c | Homa TP 500KB 7p | ⚠️ | 18.5 Gbps — needs 7 NIC |
| 1d | Homa RPC rate 32B 7p | ⚠️ | 0.45 Mops — needs 7 NIC |
| 2 | Cluster slowdown | ❌ | needs 10 machines |
| 3 | TCP echo | ⬜ | not run |
| 4 | KV store | ⬜ | not run |
| 5 | Pacing 8 Gbps | ✅ | 8.0 Gbps ±1.5% (1MB) |
| 6 | XDP_EGRESS baseline | ✅ | 7.8 Mpps (paper 11.55) |
| 7 | XDP_GEN | ⬜ | not run |
| 8 | CPU cycles (perf) | ⏳ | about to run |
| 9 | Packet loss | ❌ | blocked: tc netem doesn't work with XDP/AF_XDP |

---

## MEASURE 1: Homa Microbenchmarks

### 1a. Latency 32B (single-thread) ✅
**Server (node0):**
```
ETRAN_PROTO=homa ./cp_node server
```
**Client (node1):**
```
ETRAN_PROTO=homa ./cp_node client --workload 32 --first-server 0 --one-way
```
**Result:** P50 10.17 µs | 89.9 Kops | ✅ beats paper (11.8 µs)

### 1b. Throughput 1MB (single-thread, client-max=2) ✅
**Server (node0):** same as 1a
**Client (node1):**
```
ETRAN_PROTO=homa ./cp_node client --workload 1000000 --first-server 0 --one-way --client-max 2
```
**Result:** 20.8 Gbps | P50 717 µs | ✅ beats paper (17.7 Gbps)

### 1c. Server Throughput 500KB (7 ports) ⚠️
**Server (node0):** same as 1a (single-thread server)
**Client (node1):** attempt 1 — client-max=14 with server multi-thread:
```
ETRAN_PROTO=homa ./cp_node client --workload 500000 --ports 7 --queues 20 --first-server 0 --one-way --server-ports 7 --client-max 14
```
→ UMEM overflow ("No buffer available"), client-max too high.

**Client (node1):** attempt 2 — server multi-thread, client-max=7:
```
ETRAN_PROTO=homa ./cp_node client --workload 500000 --ports 7 --queues 20 --first-server 0 --one-way --server-ports 7 --client-max 7
```
→ 13.5 Gbps, worse than single-thread server

**Client (node1):** attempt 3 — BACK to single-thread server, client-max=7:
```
ETRAN_PROTO=homa ./cp_node client --workload 500000 --ports 7 --queues 20 --first-server 0 --one-way --client-max 7
```
**Result:** 18.5 Gbps | P50 1467 µs | ⚠️ below paper (23.0)

### 1d. RPC Rate 32B (7 ports) ⚠️
**Server (node0):** single-thread
**Client (node1):** attempt 1 — client-max=35, single process:
```
ETRAN_PROTO=homa ./cp_node client --workload 32 --ports 7 --queues 20 --first-server 0 --one-way --client-max 35
```
→ 466 Kops | P50 74 µs

**Client (node1):** attempt 2 — server multi-thread, --server-ports=7, client-max=35:
```
ETRAN_PROTO=homa ./cp_node client --workload 32 --ports 7 --queues 20 --first-server 0 --one-way --server-ports 7 --client-max 35
```
→ 454 Kops | P50 61-84 µs — no improvement

**Client (node1):** attempt 3 — 7 separate cp_node processes, multi-thread server:
```
for i in $(seq 0 6); do
  ETRAN_PROTO=homa ./cp_node client --workload 32 --first-server 0 --one-way \
    --ports 1 --client-max 5 --first-port $((4000 + i)) --server-ports 1 \
    --client-first-port $((5000 + i*10)) &
done
```
→ 227 Kops total, Homa routes all RPCs to same server port regardless of --first-port

**Conclusion:** NAPI serialization bottleneck. 7 ports share 1 NAPI context → RTT scales 7×. Needs 7 physical NICs (7 separate machines).

---

## MEASURE 5: Pacing ✅

### 5a. 1MB @ 8 Gbps (successful)
**Server (node0):** `ETRAN_PROTO=homa ./cp_node server`
**Client (node1):**
```
ETRAN_PROTO=homa ./cp_node client --workload 1000000 --first-server 0 --gbps 8.0 --client-max 4 --one-way
```
**Result:** 7.78–8.16 Gbps (~8.0 avg) | P50 656–673 µs | deviation ~1.5%
**Lesson:** inter-packet gap (1ms) must exceed RTT (~670 µs) for pacing to control rate.

### 5b. 1KB @ 8 Gbps (failed — server bottleneck)
```
ETRAN_PROTO=homa ./cp_node client --workload 1000 --first-server 0 --gbps 8.0 --client-max 4 --one-way
```
→ 2.63 Gbps max — gap (1µs) < RTT (21µs), server is the bottleneck.

### 5c. 1KB @ 4 Gbps (failed — server bottleneck)
```
ETRAN_PROTO=homa ./cp_node client --workload 1000 --first-server 0 --gbps 4.0 --client-max 16 --one-way
```
→ 3.64 Gbps — RTT=31µs limits to ~4.1 Gbps max.

---

## MEASURE 6: XDP_EGRESS baseline ✅

### Baseline AF_XDP tx-only
```
cd ~/eTran/bench-afxdp
sudo taskset -c 0 ./xdpsock -i ens1f1np1 -q 0 -t -s 64 -B -N
```
**Result:** 7.8 Mpps (paper 11.55 Mpps)

### NIC tuning attempted:
- Governor: `ondemand` → `performance` — helped (~5.3 → 7.8)
- Coalescing: `adaptive-tx on, tx-frames 128` → `tx-frames 1` — hurt (7.8 → 4.0)
- Rebuild with EXTRA_CFLAGS="-O3" — broke (7.8 → 1.2)
- Ring buffer: 2048 → 8192 — no change
- **Best: original build × governor=performance = 7.8 Mpps**

Hook tests (Empty XDP_EGRESS, OOO, Array, Hashmap) require compiled eTran eBPF programs — not testable standalone.

Note: discrepancy (7.8 vs 11.55) likely from xdpsock build configuration and kernel version — same hardware, same kernel.

---

## MEASURE 9: Packet Loss ❌ BLOCKED

### Investigation
`tc qdisc netem loss` operates at kernel qdisc layer. eTran uses XDP/AF_XDP which bypasses the kernel networking stack entirely. Packets are taken at driver level before qdisc.

Paper likely used Mellanox 2410 switch SDK or a separate bridge node for packet loss injection. **Not reproducible with 2 directly-connected machines.**

---

## Key Lessons

| Category | Finding |
|----------|---------|
| **Single-thread** | 10.2 µs, 20.8 Gbps — both **beat the paper** |
| **Multi-thread** | 7 ports share 1 NAPI context → RTT ×7. **Needs 7 physical machines** |
| **Pacing** | Works correctly when inter-packet gap > RTT (1MB messages) |
| **`ETRAN_PROTO=homa`** | **Mandatory** for cp_node server AND client — pre-main crash without it |
| **cp_node server multi-thread** | Hurts Homa performance (contention), not needed for single-client tests |
| **flexkvs_server** | Positional args (CONFIG THREADS QUEUES), not `-t N` |
| **tc netem + eTran** | **Does not work** — XDP bypasses kernel qdisc |
| **NIC governor** | Must be `performance`, `ondemand` reduces throughput significantly |
| **xdpsock build** | Original repo binary best; `CFLAGS=` overrides include paths |
