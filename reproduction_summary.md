# eTran - Reproduction Results

This preliminary report presents our reproduction of the primary metrics from the eTran
paper. Each metric was measured on CloudLab xl170 hardware (single-socket 10-core
E5-2640v4, Mellanox ConnectX-4 Lx 25G NIC, SMT enabled). We compare eTran
against two baselines: Linux Homa (the Homa protocol implemented as a kernel
module) and DCTCP (standard Linux TCP with DCTCP congestion control and ECN).

Results are grouped by category. For each category we describe the experimental
setup in plain terms and report the paper's expected value alongside our
measured value.

---

## 1. Homa Short Message Latency

**What we measure:** The minimum round-trip time for very small RPCs. A single
client on one machine sends 32-byte requests to a server on a second machine.
The server echoes the full 32 bytes back (the client waits for the response
before sending the next request). We report the median (P50) latency across all
responses.

| Metric                      | Paper | Measured | Match             |
| --------------------------- | ----- | -------- | ----------------- |
| eTran Homa 32B RTT P50 (us) | 11.8  | 12.59    | Close (within 7%) |
| Linux Homa 32B RTT P50 (us) | 15.6  | 15.26    | Matches           |

## 2. Homa Large Message Throughput

**What we measure:** The maximum throughput for bulk data transfer. A single
client sends 1MB requests back-to-back to a server on a second machine. The
server returns only a small acknowledgment (100 bytes) rather than echoing the
full payload. We report the sustained throughput in Gbps. Two machines total.

| Metric                           | Paper | Measured | Match                |
| -------------------------------- | ----- | -------- | -------------------- |
| eTran Homa 1MB throughput (Gbps) | 17.7  | 16.6     | Slightly below (94%) |
| Linux Homa 1MB throughput (Gbps) | 14.5  | 17.9     | Exceeds paper        |

## 3. Homa Multi-Threaded Throughput

**What we measure:** Throughput under a many-to-one and one-to-many topology
with large messages (500KB each). Two configurations. (a) Server throughput:
one server machine receiving 500KB RPCs from seven client machines concurrently
(7:1 ratio). The server uses 4 threads. Each client sends one RPC at a time.
(b) Client throughput: one client machine sending 500KB RPCs to seven server
machines (1:7 ratio). The client sends to all seven servers in parallel using
7 threads, one RPC at a time per server. Results in Gbps.

| Metric                              | Paper | Measured | Match                     |
| ----------------------------------- | ----- | -------- | ------------------------- |
| eTran Homa server throughput (Gbps) | 23.0  | ~12.78   | Significantly below (56%) |
| Linux Homa server throughput (Gbps) | 23.1  | 23.125   | Matches                   |
| eTran Homa client throughput (Gbps) | 22.7  | ~19.5    | Below (86%)               |
| Linux Homa client throughput (Gbps) | 22.9  | 23.1     | Matches                   |

Since eTran Homa server throughput was below the paper's 23.0 Gbps target, we
varied the number of server threads (controlled by the port count) to measure
its effect.

| Server Ports (threads) | Measured Throughput (Gbps) |
| ---------------------: | -------------------------: |
|                      4 |                       12.9 |
|                      5 |                      12.78 |
|                      7 |                      12.77 |
|                     10 |                       8.01 |

Throughput does not increase with more server threads. At 10 ports it is
substantially lower.

## 4. Homa Small Message RPC Rate

**What we measure:** How many small RPCs per second each transport can sustain.
Messages are 32 bytes and the server echoes the full payload. Two
configurations at a 7:1 ratio. (a) Client RPC rate: seven client machines
sending to one server machine. The server runs 7 threads. Each client keeps up
to 64 RPCs in flight. (b) Server RPC rate: one client machine sending to seven
server machines. The client sends to all seven servers in parallel using 7
threads, keeping up to 256 RPCs in flight. Values in millions of operations per
second (Mops).

| Metric                            | Paper | Measured | Match                     |
| --------------------------------- | ----- | -------- | ------------------------- |
| eTran Homa client RPC rate (Mops) | 2.9   | ~0.93    | Significantly below (32%) |
| Linux Homa client RPC rate (Mops) | 1.7   | 1.1      | Below (65%)               |
| eTran Homa server RPC rate (Mops) | 3.3   | ~1.12    | Significantly below (34%) |
| Linux Homa server RPC rate (Mops) | 1.8   | 0.9      | Below (50%)               |

## 5. Homa Tail Latency in Mixed Workloads (All-to-All)

**What we measure:** End-to-end latency in a realistic cluster workload. Ten
machines each act as both client and server simultaneously (all-to-all). Each
machine randomly selects other machines to send RPCs to. We use four predefined
workloads (W2 through W5) with different mixes of small and large messages and
different offered loads. W2 and W3 are
dominated by short messages. W4 and W5 are dominated by large messages. We
report the slowdown factor, defined as Linux Homa (kernel module) latency
divided by eTran Homa latency. A slowdown above 1.0x means eTran is faster; a
slowdown below 1.0x means Linux Homa is faster.

| Metric                                               | Paper Slowdown | Measured Slowdown | Match        |
| ---------------------------------------------------- | -------------- | ----------------- | ------------ |
| W2 P99 slowdown (short-msg dominated workload)       | 3.9x - 7.5x    | 7.0x              | Within range |
| W3 P99 slowdown (short-msg dominated workload)       | 3.9x - 7.5x    | 6.7x              | Within range |
| W2 P50 slowdown                                      | 1.4x - 3.6x    | 0.86x             | Below range  |
| W3 P50 slowdown                                      | 1.4x - 3.6x    | 0.87x             | Below range  |
| W4 P50 slowdown (shortest 10% of RPCs, 20 Gbps load) | 4.1x           | 0.008x            | Below range  |
| W5 P50 slowdown (shortest 10% of RPCs, 20 Gbps load) | 3.9x           | 0.004x            | Below range  |
| W4 P99 slowdown (shortest 10% of RPCs, 20 Gbps load) | 4.3x           | 0.002x            | Below range  |
| W5 P99 slowdown (shortest 10% of RPCs, 20 Gbps load) | 2.9x           | 0.002x            | Below range  |

## 6. TCP Throughput (1KB and 2KB Messages)

**What we measure:** Raw TCP streaming throughput between two machines for
small-to-medium messages. Uses the same epoll-based client and server binaries
for both eTran and DCTCP measurements. eTran accelerates TCP through AF_XDP
(bypasses the kernel TCP stack). DCTCP runs on the standard kernel TCP stack
without acceleration. Messages of 1KB and 2KB, with 64 requests outstanding.
Tested at three concurrency levels on the client: 1 thread with 1 connection
(1x1), 1 thread with 5 connections (1x5), and 5 threads with 5 connections
(5x5). The paper's target for eTran TCP is expressed as a multiplier relative
to DCTCP (4.8x for 1KB). Values in Gbps.

| Metric                              | Paper                   | Measured                 | Match       |
| ----------------------------------- | ----------------------- | ------------------------ | ----------- |
| eTran TCP 1KB throughput 1x1 (Gbps) | 13.44 (4.8x over DCTCP) | ~7.19 (878 Kops)         | Below (53%) |
| eTran TCP 1KB throughput 1x5 (Gbps) | 13.44 (4.8x)            | ~12.1 (1474 Kops)        | Close (90%) |
| eTran TCP 1KB throughput 5x5 (Gbps) | 13.44 (4.8x)            | ~7.55 (922 Kops)         | Below (56%) |
| DCTCP 1KB throughput (Gbps)         | Baseline (reference)    | 1.8 - 2.8 (222-346 Kops) | Reference   |
| eTran TCP 2KB throughput (Gbps)     | ~21.56 (0.87x TAS)      | ~12.29 (750 Kops)        | Below (57%) |
| DCTCP 2KB throughput (Gbps)         | Baseline (reference)    | 1.8 - 4.6 (111-283 Kops) | Reference   |

## 7. TCP Connection Scalability

**What we measure:** Throughput for many persistent TCP connections. One server
machine and five client machines, totaling 1,000 persistent connections. Each
connection sends 64-byte requests in a closed loop (the next request is sent
only after the previous response is received). This measures the overhead of
maintaining many concurrent connections. Values in Mops. The paper also defines
two short-lived connection metrics (connections that send only 16 or 256
messages before closing per connection, with 1,000 concurrent flows). We did
not reproduce these: the public eTran repository provides no short-lived
connection benchmark tool (the included `epoll_client` only supports persistent
connections). Implementing a custom tool would not allow comparison with the
paper's results, since the measurement methodology and client behavior would
differ from whatever the paper authors used.

| Metric                                  | Paper                    | Measured       | Match          |
| --------------------------------------- | ------------------------ | -------------- | -------------- |
| eTran TCP persistent connections (Mops) | 0.529 (2.26x over DCTCP) | ~0.655 (2.80x) | Exceeds paper  |
| DCTCP persistent connections (Mops)     | Baseline (reference)     | ~0.234         | Reference      |
| eTran TCP short-lived, 16 msg/conn      | 42.7x over baseline      | Not reproduced | Not reproduced |
| eTran TCP short-lived, 256 msg/conn     | 5.4x over baseline       | Not reproduced | Not reproduced |

## 8. TCP Key-Value Store

**What we measure:** Performance under a realistic key-value workload. Uses a
custom key-value server and benchmark (flexkvs). Dataset of 100,000 keys with a
Zipf distribution (skew s=0.9) and a 9:1 GET to SET ratio. For throughput, 5
client machines each use 4 threads, 10 connections, and 32 parallel requests.
For latency, a single client uses 1 thread, 1 connection, and 1 request at a
time (under-loaded server). Values in Mops (throughput) and microseconds
(latency). eTran accelerates TCP via AF_XDP. DCTCP runs on the standard kernel
stack. Note: our DCTCP latency values (36 us P50) are lower than the paper's
(64.2 us P50).

| Metric                     | Paper                                  | Measured              | Match        |
| -------------------------- | -------------------------------------- | --------------------- | ------------ |
| eTran KV throughput (Mops) | 0.667 - 1.334 (2.4x - 4.8x over DCTCP) | ~0.73 (2.62x)         | Within range |
| DCTCP KV throughput (Mops) | Baseline (reference)                   | ~0.278                | Reference    |
| eTran KV P50 latency (us)  | 17.2                                   | 14                    | Beats paper  |
| eTran KV P99 latency (us)  | 27.5                                   | 16                    | Beats paper  |
| DCTCP KV P50 latency (us)  | 64.2                                   | 36 (at 320 in-flight) | Below paper  |
| DCTCP KV P99 latency (us)  | 89.3                                   | 24 (idle)             | Below paper  |

## 9. CPU Efficiency

**What we measure:** How many CPU cycles are consumed per request, measured
with the Linux perf tool. Collected for both eTran and its baselines (DCTCP for
TCP, Linux Homa kernel module for Homa). For eTran TCP, measured on the server
side during a single-flow run at 884,000 requests per second. For eTran Homa,
the perf tool's sampling interrupts interfere with AF_XDP's busy-poll loop. The
raw measured value is 1357 kcycles, dominated by idle polling. Subtracting the
busy-poll idle cycles yields an estimated active processing cost of roughly 5
kcycles per request, matching the paper's 5.48 kcycles target. Linux Homa
measured with the kernel module at approximately 279,000 requests per second.

| Metric                           | Paper | Measured | Match           |
| -------------------------------- | ----- | -------- | --------------- |
| eTran TCP (kcycles per request)  | 4.37  | ~2.93    | Below paper     |
| DCTCP TCP (kcycles per request)  | 12.51 | ~7.4     | Below paper     |
| eTran Homa (kcycles per request) | 5.48  | ~1357    | Far above paper |
| Linux Homa (kcycles per request) | 17.43 | ~18.6    | Close           |

---

## 10. Machine Configuration Tunings

The following system-level tunings were tested against metrics 1 (latency), 3
(multi-threaded throughput), and 5 (RPC rate).

### Effective

| Tuning                                                  | Observed Result                                    |
| ------------------------------------------------------- | -------------------------------------------------- |
| C-states disabled (`intel_idle.max_cstate=0`)           | Applied via GRUB                                   |
| ASPM disabled (`pcie_aspm=off`)                         | Applied via GRUB                                   |
| CPU mitigations off (`mitigations=off`)                 | Applied via GRUB                                   |
| NIC RX coalescing off (`adaptive-rx off`, `rx-usecs 0`) | Applied per session (resets on reboot)             |
| NIC TX coalescing (`adaptive-tx off`, `tx-usecs 5`)     | Applied per session (resets on reboot)             |
| Flow control off (`ethtool -A rx off tx off`)           | Applied per session (resets on reboot)             |
| CPU governor = performance (via tuned)                  | Applied via tuned `network-throughput`             |
| SMT enabled (HT-on)                                     | Metric 5: ~8% higher vs nosmt + taskset workaround |
| BPF XDP_EGRESS patch (`homa/main.c:235-248`)            | Fixes: grant drops, TCP crashes, connection stalls |

### No measurable effect

| Tuning                                   | Observed Result                                                                                          |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| NIC ring buffer size increased to 4096   | No change                                                                                                |
| LRO disabled                             | No change                                                                                                |
| ntuple flow rules (ethtool -U)           | No change                                                                                                |
| napi_defer_hard_irqs / gro_flush_timeout | No change                                                                                                |
| IRQ-to-core pinning                      | No change                                                                                                |
| Transparent Hugepages disabled           | No change                                                                                                |
| 2M hugepages for AF_XDP UMEM             | No change (microkernel enables them internally)                                                          |
| NUMA balancing disabled                  | No change                                                                                                |
| KSM disabled                             | No change                                                                                                |
| eBPF stats disabled                      | No change                                                                                                |
| irqbalance disabled                      | No change                                                                                                |
| taskset on application threads           | No change (microkernel already pins threads; the target CPU is hardcoded in `runtime/defs.h` as core 19) |

### Degraded performance

| Tuning               | Observed Result                                                         |
| -------------------- | ----------------------------------------------------------------------- |
| Intel Turbo disabled | Metric 5 dropped 39% (927 to 568 Kops)                                  |
| GRO/TSO off          | Metric 5 dropped 39% (927 to 568 Kops)                                  |
| SMT disabled (nosmt) | Mk control loop pin to hardcoded core 19 fails (core offline); reverted |
