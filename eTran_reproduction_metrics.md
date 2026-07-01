# eTran Paper Metrics & Reproduction Targets (NSDI '25)

This document collects the metrics, baseline configurations, expected performance values, and relative benchmark ratios presented in the **eTran: Extensible Kernel Transport with eBPF** paper (NSDI '25).

Use these target values and formulas to verify and reproduce the evaluations described in the paper. An empty column/cell has been provided in each table for you to record your own measured values.

---

## 1. Primary Metrics and Baseline Comparisons

| Networking Stack | Measurement Description | Measurement Unit | Expected Value | Measured Value | Reproduction Priority |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **eTran - Homa** | Median RTT latency for short messages (32B requests back-to-back, single client thread) | µs | **11.8** | | **High (2-Node Micro)** |
| **Linux - Homa** | Median RTT latency for short messages (32B requests back-to-back, single client thread) | µs | **15.6** | | **High (2-Node Micro)** |
| **eTran - Homa** | Throughput for large messages (1MB requests back-to-back) | Gbps | **17.7** | | **High (2-Node Micro)** |
| **Linux - Homa** | Throughput for large messages (1MB requests back-to-back) | Gbps | **14.5** | | **High (2-Node Micro)** |
| **eTran - Homa** | Multi-threaded server throughput (receiving concurrent 500KB RPCs from 7 clients) | Gbps | **23.0** | | Medium |
| **Linux - Homa** | Multi-threaded server throughput (receiving concurrent 500KB RPCs from 7 clients) | Gbps | **23.1** | | Medium |
| **eTran - Homa** | Multi-threaded client throughput (sending concurrent 500KB RPCs to 7 servers) | Gbps | **22.7** | | Medium |
| **Linux - Homa** | Multi-threaded client throughput (sending concurrent 500KB RPCs to 7 servers) | Gbps | **22.9** | | Medium |
| **eTran - Homa** | Client RPC rate for small messages (32B) | Mops | **2.9** | | Medium |
| **Linux - Homa** | Client RPC rate for small messages (32B) | Mops | **1.7** | | Medium |
| **eTran - Homa** | Server RPC rate for small messages (32B) | Mops | **3.3** | | Medium |
| **Linux - Homa** | Server RPC rate for small messages (32B) | Mops | **1.8** | | Medium |
| **eTran - Homa** | P99 tail latency slowdown in workloads dominated by short messages (W2, W3) | Slowdown Factor | `Linux - Homa (P99 Slowdown) / (3.9 ~ 7.5)` | | **High (10-Node Cluster)** |
| **eTran - Homa** | P50 median latency slowdown in workloads dominated by short messages (W2, W3) | Slowdown Factor | `Linux - Homa (P50 Slowdown) / (1.4 ~ 3.6)` | | **High (10-Node Cluster)** |
| **eTran - Homa** | RTT P50 slowdown for the shortest 10% of RPCs in Workload W4 (20 Gbps) | Slowdown Factor | `Linux - Homa (W4 P50 Slowdown) / 4.1` | | **High (10-Node Cluster)** |
| **eTran - Homa** | RTT P50 slowdown for the shortest 10% of RPCs in Workload W5 (20 Gbps) | Slowdown Factor | `Linux - Homa (W5 P50 Slowdown) / 3.9` | | **High (10-Node Cluster)** |
| **eTran - Homa** | RTT P99 slowdown for the shortest 10% of RPCs in Workload W4 (20 Gbps) | Slowdown Factor | `Linux - Homa (W4 P99 Slowdown) / 4.3` | | **High (10-Node Cluster)** |
| **eTran - Homa** | RTT P99 slowdown for the shortest 10% of RPCs in Workload W5 (20 Gbps) | Slowdown Factor | `Linux - Homa (W5 P99 Slowdown) / 2.9` | | **High (10-Node Cluster)** |
| **eTran - TCP** | Throughput with 1KB messages (64 outstanding messages, single-threaded) | Gbps | `4.8 * Linux - TCP (Throughput 1KB)` | | **High (2-Node Micro)** |
| **TAS - TCP** | Throughput with 1KB messages (64 outstanding messages, single-threaded) | Gbps | `7.7 * Linux - TCP (Throughput 1KB)` | | Medium |
| **Linux - TCP** | Throughput with 1KB messages (64 outstanding messages, single-threaded) | Gbps | *Reference Value (Baseline)* | | **High (2-Node Micro)** |
| **eTran - TCP** | Throughput with 2KB messages (64 outstanding messages, single-threaded) | Gbps | `0.87 * TAS - TCP (Throughput 2KB)` | | Medium |
| **TAS - TCP** | Throughput with 2KB messages (64 outstanding messages, single-threaded) | Gbps | *Reference Value (Baseline)* | | Medium |
| **eTran - TCP** | Throughput with 1K persistent connections (64B requests, closed-loop) | Mops | `2.26 * Linux - TCP (Throughput 1K conn)` | | **High (6-Node Connection Scalability)** |
| **TAS - TCP** | Throughput with 1K persistent connections (64B requests, closed-loop) | Mops | `4.1 * Linux - TCP (Throughput 1K conn)` | | Medium |
| **Linux - TCP** | Throughput with 1K persistent connections (64B requests, closed-loop) | Mops | *Reference Value (Baseline)* | | **High (6-Node Connection Scalability)** |
| **eTran - TCP** | Throughput of short-lived connections with 16 messages per connection (1K concurrent flows) | Mops | `42.7 * Linux - TCP (Throughput 16 msg/conn)` | | **High (6-Node Connection Scalability)** |
| **eTran - TCP** | Throughput of short-lived connections with 256 messages per connection (1K concurrent flows) | Mops | `5.4 * Linux - TCP (Throughput 256 msg/conn)` | | Medium |
| **Linux - TCP** | Throughput of short-lived connections (1K concurrent flows) | Mops | *Reference Value (Baseline)* | | **High (6-Node Connection Scalability)** |
| **eTran - TCP** | Throughput in Key-Value Store workload (100K keys, Zipf s=0.9, 9:1 GET:SET ratio) | Mops | `(2.4 ~ 4.8) * Linux - TCP (KV Throughput)` | | **High (6-Node KV)** |
| **TAS - TCP** | Throughput in Key-Value Store workload (100K keys, Zipf s=0.9, 9:1 GET:SET ratio) | Mops | `(3.9 ~ 7.9) * Linux - TCP (KV Throughput)` | | Medium |
| **Linux - TCP** | Throughput in Key-Value Store workload (100K keys, Zipf s=0.9, 9:1 GET:SET ratio) | Mops | *Reference Value (Baseline)* | | **High (6-Node KV)** |
| **eTran - TCP** | RTT P50 (median) latency in Key-Value Store workload (under-loaded server) | µs | **17.2** (equal to `Linux - TCP (KV Latency P50) / 3.7`) | | **High (6-Node KV)** |
| **Linux - TCP** | RTT P50 (median) latency in Key-Value Store workload (under-loaded server) | µs | **64.2** | | **High (6-Node KV)** |
| **eTran - TCP** | RTT P99 (tail) latency in Key-Value Store workload (under-loaded server) | µs | **27.5** (equal to `Linux - TCP (KV Latency P99) / 3.2`) | | **High (6-Node KV)** |
| **Linux - TCP** | RTT P99 (tail) latency in Key-Value Store workload (under-loaded server) | µs | **89.3** | | **High (6-Node KV)** |
| **eTran - TCP** | Total CPU cycles spent per request (total kcycles, see breakdown below) | kcycles | **4.37** | | **High (2-Node CPU Profiling)** |
| **Linux - TCP** | Total CPU cycles spent per request (total kcycles, see breakdown below) | kcycles | **12.51** | | **High (2-Node CPU Profiling)** |
| **eTran - Homa** | Total CPU cycles spent per request (total kcycles, see breakdown below) | kcycles | **5.48** | | **High (2-Node CPU Profiling)** |
| **Linux - Homa** | Total CPU cycles spent per request (total kcycles, see breakdown below) | kcycles | **17.43** | | **High (2-Node CPU Profiling)** |
| **eTran (Pacing)** | Traffic shaping rate conformance deviation under pacing engine (1MB @ 8 Gbps) | % | **< 0.4** | | Low |
| **eTran (Pacing)** | Aggregate throughput for multiple flows with an 8 Gbps target | Mbps | **7950 ~ 8050** | | Low |
| **eTran - TCP** | Throughput penalty under 1% packet loss | % | **~8** | | Low |
| **eTran - TCP** | Throughput penalty under 5% packet loss | % | **~33** | | Low |
| **eTran - Homa** | Throughput penalty under 5% packet loss | % | **~90-100** | | Low |

---

## 2. Detailed Breakdown of CPU Cycles per Single Request (Table 5)

Values represent **thousands of CPU cycles (kcycles)** consumed per request by each component under stress testing with a single NAPI context.

| CPU Cycles Component | eTran - TCP (Expected) | eTran - TCP (Measured) | Linux - TCP (Expected) | Linux - TCP (Measured) | eTran - Homa (Expected) | eTran - Homa (Measured) | Linux - Homa (Expected) | Linux - Homa (Measured) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Application** | 0.48 | | 0.53 | | 0.95 | | 1.04 | |
| **Socket / RPC** | 0.63 | | 3.50 | | 0.98 | | 3.38 | |
| **Data Copy** | 0.19 | | 0.57 | | 0.32 | | 1.30 | |
| **Sk_buff** | 0.15 | | 0.47 | | 0.08 | | 0.39 | |
| **TCP / Homa + IP** | 1.06 | | 2.12 | | 1.47 | | 3.36 | |
| **Lock / Unlock** | 0.18 | | 0.45 | | 0.24 | | 2.68 | |
| **NIC Driver** | 1.17 | | 1.54 | | 0.83 | | 1.81 | |
| **Memory Mgmt** | 0.05 | | 0.32 | | 0.06 | | 1.04 | |
| **Scheduling** | 0.25 | | 1.19 | | 0.18 | | 1.02 | |
| **Other** | 0.21 | | 1.82 | | 0.38 | | 1.41 | |
| **TOTAL (kcycles)** | **4.37** | | **12.51** | | **5.48** | | **17.43** | |

---

## 3. Data Path Microbenchmarks (Hooks and Maps Performance)

### 3.1 XDP_EGRESS Egress Overhead & Features (Table 3)
Evaluated on a single core sending 64B packets under stress testing.

| Datapath Configuration | Expected Egress Tpt (Mpps) | Measured Egress Tpt (Mpps) | Relative Throughput Target | Expected Throughput Loss | Measured Throughput Loss | Reproduction Priority |
| :--- | :---: | :---: | :--- | :---: | :---: | :--- |
| **AF_XDP tx-only** (Baseline) | **11.55** | | *Baseline Value* | - | | **High (2-Node Driver Micro)** |
| **+ Empty XDP_EGRESS** | **10.79** | | `AF_XDP tx-only * 0.934` | 6.6% | | **High (2-Node Driver Micro)** |
| **+ Out-Of-Order (OOO) Completion** | **9.95** | | `AF_XDP tx-only * 0.861` | 13.9% | | **High (2-Node Driver Micro)** |
| **+ Array Lookup** | **9.71** | | `AF_XDP tx-only * 0.841` | 15.9% | | Medium |
| **+ Hashmap Lookup** | **9.10** | | `AF_XDP tx-only * 0.788` | 21.2% | | Medium |

### 3.2 XDP_GEN Packet Generation Performance (Table 4)
Evaluated across two cores: one core generates ACK/credit packets using `XDP_GEN`, and the other core uses `AF_XDP` to drop received packets.

| Operation Benchmark | Expected Overall Tpt (Mpps) | Measured Overall Tpt (Mpps) | Expected Active CPU Cores | Measured Active CPU Cores | Expected Per-Core Tpt (Mpps) | Measured Per-Core Tpt (Mpps) | Reproduction Priority |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **l2fwd** (Baseline) | **6.73** | | 1.74 | | **3.87** | | Medium |
| **rx-drop + XDP_GEN** | **6.03** | | 1.35 | | **4.47** | | **High (2-Node Driver Micro)** |

