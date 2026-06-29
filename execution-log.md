# eTran Execution Log

## MEASURE 1: Homa Microbenchmarks

### 1a. Latency 32B (single-thread)
**Server (node0):**
```
ETRAN_PROTO=homa ./cp_node server
```
**Client (node1):**
```
ETRAN_PROTO=homa ./cp_node client --workload 32 --first-server 0 --one-way
```
**Result:** P50 10.17 µs | 89.9 Kops | ✅ beats paper (11.8 µs)

### 1b. Throughput 1MB (single-thread, client-max=2)
**Server (node0):** same as 1a
**Client (node1):**
```
ETRAN_PROTO=homa ./cp_node client --workload 1000000 --first-server 0 --one-way --client-max 2
```
**Result:** 20.8 Gbps | P50 717 µs | ✅ beats paper (17.7 Gbps)

### 1c. Server Throughput 500KB (7 ports)
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
**Result:** 18.5 Gbps | P50 1467 µs | ⚠️ below paper (23.0) — NAPI serialization

### 1d. RPC Rate 32B (7 ports)
**Server (node0):** single-thread
**Client (node1):** attempt 1 — client-max=35:
```
ETRAN_PROTO=homa ./cp_node client --workload 32 --ports 7 --queues 20 --first-server 0 --one-way --client-max 35
```
→ 466 Kops | P50 74 µs

**Client (node1):** attempt 2 — server multi-thread, --server-ports=7, client-max=35:
```
ETRAN_PROTO=homa ./cp_node client --workload 32 --ports 7 --queues 20 --first-server 0 --one-way --server-ports 7 --client-max 35
```
→ 454 Kops | P50 61-84 µs — no improvement
**Result:** 0.45 Mops | ⚠️ far below paper (2.9) — NAPI serialization, needs 7 physical NICs

---

## MEASURE 5: Pacing

### 5a. 1MB @ 8 Gbps (successful)
**Server (node0):** `ETRAN_PROTO=homa ./cp_node server`
**Client (node1):**
```
ETRAN_PROTO=homa ./cp_node client --workload 1000000 --first-server 0 --gbps 8.0 --client-max 4 --one-way
```
**Result:** 7.78–8.16 Gbps (~8.0 avg) | P50 656–673 µs
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

## Key Findings

| Insight | Detail |
|---------|--------|
| Single-thread results beat paper | 10.2 µs (vs 11.8), 20.8 Gbps (vs 17.7) |
| Multi-thread limited by NAPI | 7 ports share 1 NAPI context → RTT scales 7× |
| Pacing works when gap > RTT | 1MB messages needed for 8 Gbps test |
| `ETRAN_PROTO=homa` required | Pre-main constructor crashes without it |
| Server multi-thread hurts Homa | Contention for resources in microkernel |
| flexkvs_server takes positional args | Not `-t 5`, but `/dev/null 5 20` |
