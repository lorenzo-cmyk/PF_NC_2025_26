# eTran-Only Performance Metrics & Reproduction Targets (NSDI '25)

This document contains **ONLY** the performance metrics, benchmarks, and target values involving **eTran** (eTran - Homa, eTran - TCP, and eTran hooks/pacing configurations). Baselines and comparison stacks (Linux TCP/Homa, TAS) have been excluded.

An empty column/cell has been provided in each table for you to record your own measured values during reproduction.

---

## 1. Primary eTran Metrics and Reproduction Targets

| Networking Stack | Measurement Description | Measurement Unit | Expected Value | Measured Value |
| :--- | :--- | :--- | :--- | :--- |
| **eTran - Homa** | Median RTT latency for short messages (32B requests back-to-back, single client thread) | µs | **11.8** | **10.2** ✅ |
| **eTran - Homa** | Throughput for large messages (1MB requests back-to-back, single-threaded, client-max=1) | Gbps | **17.7** | **16.3** (client-max=1), **20.8** (client-max=2) |
| **eTran - Homa** | Multi-threaded server throughput (receiving concurrent 500KB RPCs from 7 ports) | Gbps | **23.0** | **18.5** (1 NIC) · ⬜ retry 7 NIC |
| **eTran - Homa** | Multi-threaded client throughput (sending concurrent 500KB RPCs to 7 servers) | Gbps | **22.7** | (needs 8 machines) |
| **eTran - Homa** | Client RPC rate for small messages (32B, 7 ports) | Mops | **2.9** | **0.45** (1 NIC) · ⬜ retry 7 NIC |
| **eTran - Homa** | Server RPC rate for small messages (32B) | Mops | **3.3** | |
| **eTran - Homa** | P99 tail latency slowdown in workloads dominated by short messages (W2, W3) | Slowdown Factor | `Linux - Homa (P99 Slowdown) / (3.9 ~ 7.5)` | |
| **eTran - Homa** | P50 median latency slowdown in workloads dominated by short messages (W2, W3) | Slowdown Factor | `Linux - Homa (P50 Slowdown) / (1.4 ~ 3.6)` | |
| **eTran - Homa** | RTT P50 slowdown for the shortest 10% of RPCs in Workload W4 (20 Gbps) | Slowdown Factor | `Linux - Homa (W4 P50 Slowdown) / 4.1` | |
| **eTran - Homa** | RTT P50 slowdown for the shortest 10% of RPCs in Workload W5 (20 Gbps) | Slowdown Factor | `Linux - Homa (W5 P50 Slowdown) / 3.9` | |
| **eTran - Homa** | RTT P99 slowdown for the shortest 10% of RPCs in Workload W4 (20 Gbps) | Slowdown Factor | `Linux - Homa (W4 P99 Slowdown) / 4.3` | |
| **eTran - Homa** | RTT P99 slowdown for the shortest 10% of RPCs in Workload W5 (20 Gbps) | Slowdown Factor | `Linux - Homa (W5 P99 Slowdown) / 2.9` | |
| **eTran - TCP** | Throughput with 1KB messages (64 outstanding messages, single-threaded) | Gbps | `4.8 * Linux - TCP (Throughput 1KB)` | |
| **eTran - TCP** | Throughput with 2KB messages (64 outstanding messages, single-threaded) | Gbps | `0.87 * TAS - TCP (Throughput 2KB)` | |
| **eTran - TCP** | Throughput with 1K persistent connections (64B requests, closed-loop) | Mops | `2.26 * Linux - TCP (Throughput 1K conn)` | |
| **eTran - TCP** | Throughput of short-lived connections with 16 messages per connection (1K concurrent flows) | Mops | `42.7 * Linux - TCP (Throughput 16 msg/conn)` | |
| **eTran - TCP** | Throughput of short-lived connections with 256 messages per connection (1K concurrent flows) | Mops | `5.4 * Linux - TCP (Throughput 256 msg/conn)` | |
| **eTran - TCP** | Throughput in Key-Value Store workload (100K keys, Zipf s=0.9, 9:1 GET:SET ratio) | Mops | `(2.4 ~ 4.8) * Linux - TCP (KV Throughput)` | |
| **eTran - TCP** | RTT P50 (median) latency in Key-Value Store workload (under-loaded server) | µs | **17.2** (equal to `Linux - TCP (KV Latency P50) / 3.7`) | |
| **eTran - TCP** | RTT P99 (tail) latency in Key-Value Store workload (under-loaded server) | µs | **27.5** (equal to `Linux - TCP (KV Latency P99) / 3.2`) | |
| **eTran - TCP** | Total CPU cycles spent per request (total kcycles, see breakdown below) | kcycles | **4.37** | |
| **eTran - Homa** | Total CPU cycles spent per request (total kcycles, see breakdown below) | kcycles | **5.48** | |
| **eTran (Pacing)** | Traffic shaping rate conformance deviation under pacing engine (1MB @ 8 Gbps) | % | **< 0.4** | **~1.5** (1MB, gap=1ms > RTT) |
| **eTran (Pacing)** | Aggregate throughput for multiple flows with an 8 Gbps target | Mbps | **7950 ~ 8050** | |
| **eTran - TCP** | Throughput penalty under 1% packet loss | % | **~8** (compared to `~3%` for Linux TCP) | |
| **eTran - TCP** | Throughput penalty under 5% packet loss | % | **~33** (compared to `~25%` for Linux TCP) | |
| **eTran - Homa** | Throughput penalty under 5% packet loss | % | **~90-100** (comparable with Linux Homa) | |

---

## 2. Detailed Breakdown of CPU Cycles per Single Request for eTran (Table 5)

Values represent **thousands of CPU cycles (kcycles)** consumed per request by each component under stress testing with a single NAPI context for eTran configurations.

| CPU Cycles Component | eTran - TCP (Expected) | eTran - TCP (Measured) | eTran - Homa (Expected) | eTran - Homa (Measured) |
| :--- | :---: | :---: | :---: | :---: |
| **Application** | 0.48 | | 0.95 | |
| **Socket / RPC** | 0.63 | | 0.98 | |
| **Data Copy** | 0.19 | | 0.32 | |
| **Sk_buff** | 0.15 | | 0.08 | |
| **TCP / Homa + IP** | 1.06 | | 1.47 | |
| **Lock / Unlock** | 0.18 | | 0.24 | |
| **NIC Driver** | 1.17 | | 0.83 | |
| **Memory Mgmt** | 0.05 | | 0.06 | |
| **Scheduling** | 0.25 | | 0.18 | |
| **Other** | 0.21 | | 0.38 | |
| **TOTAL (kcycles)** | **4.37** | | **5.48** | |

---

## 3. eTran Internal Data Path Microbenchmarks (Hooks and Maps Performance)

### 3.1 XDP_EGRESS Hook Performance (Table 3)
Evaluated on a single core sending 64B packets under stress testing.

| Datapath Configuration | Expected Egress Tpt (Mpps) | Measured Egress Tpt (Mpps) | Relative Throughput Target | Expected Throughput Loss | Measured Throughput Loss |
| :--- | :---: | :---: | :--- | :---: | :---: |
| **AF_XDP tx-only** (Baseline) | **11.55** | | *Baseline Value* | — | |
| **+ Empty XDP_EGRESS** | **10.79** | | `AF_XDP tx-only × 0.934` | 6.6% | |
| **+ Out-Of-Order (OOO) Completion** | **9.95** | | `AF_XDP tx-only * 0.861` | 13.9% | |
| **+ Array Lookup** | **9.71** | | `AF_XDP tx-only * 0.841` | 15.9% | |
| **+ Hashmap Lookup** | **9.10** | | `AF_XDP tx-only * 0.788` | 21.2% | |

### 3.2 XDP_GEN Hook Packet Generation Performance (Table 4)
Evaluated across two cores: one core generates ACK/credit packets using `XDP_GEN`, and the other core uses `AF_XDP` to drop received packets.

| Operation Benchmark | Expected Overall Tpt (Mpps) | Measured Overall Tpt (Mpps) | Expected Active CPU Cores | Measured Active CPU Cores | Expected Per-Core Tpt (Mpps) | Measured Per-Core Tpt (Mpps) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **rx-drop + XDP_GEN** | **6.03** | | 1.35 | | **4.47** | |

---

## 4. Minimum Required Physical Machines for Reproduction

All machines should be equipped with 25 Gbps ConnectX-4 NICs, connected to a 25 Gbps switch.

| Measure | Description | Min. Machines | Notes |
|:---|:---|:---:|:---|
| **1** | Homa microbenchmarks (all sub-tests) | **2** | Multi-thread tests (`--ports 7`) work on 2 machines when server uses `--ports 7 --queues 20` and client uses `--server-ports 7` |
| **2** | Homa cluster slowdown (W2–W5) | **10** | All nodes run both client+server via `--both` |
| **3** | TCP echo throughput | **2** | Paper uses 5 clients for aggregate throughput; 2 machines suffice for relative comparison |
| **4** | Key-Value Store (Zipf) | **2** | Paper uses 5 clients with 6K connections each; 2 machines test eTran performance at reduced scale |
| **5** | Rate limiting (pacing) | **2** | — |
| **6** | XDP_EGRESS overhead | **1** | Standalone, no microkernel |
| **7** | XDP_GEN packet generation | **1** | Standalone, no microkernel |
| **8** | CPU cycles (perf) | **2** | — |
| **9** | Retransmission (packet loss) | **2** | — |

> **Important**: Measures 3 and 4 can run on 2 machines, but the **absolute** throughput values will be lower than the paper due to the single client NIC limit. The **relative** gains (eTran vs Linux) should still be measurable.

---

## 5. Step-by-Step Reproduction Commands for eTran

Below are the exact commands to start the microkernel, server, and client for each of the 9 reproduction measurements.

### 5.1 Compilation Prerequisite
On all nodes, compile the eTran project first:
```sh
cd ~/eTran
./configure && make -C eTran
```

> **⚠️ Known bugs in micro_kernel and cp_node (affects all measures):**
> **micro_kernel:**
> 1. **`-p` flag is documented but non-functional**: The help text claims `[-p Transport protocol (tcp, homa)], default:tcp`, but `-p` is **not in the getopt string** and has no handler. Using it will print an error and exit.
> 2. **`-q` help default is wrong**: The help text says `default:1` for NIC queues, but the code actually defaults to **20**.
>
> **cp_node:**
> 1. **`--both` default is wrong**: The help text says "(default: 5)" but the actual default when the flag is omitted is **0** (no dual-role, no delay).
> 2. **`--ports` (client) help default is misleading**: The help displays the global initial value `0`, but the actual runtime default used when the flag is omitted is **1**.
> 3. **`--pin` (server) description is copy-pasted from client**: The server help says "client threads" but it pins **server threads**, and uses a different offset (+10).

---

### MEASURE 1: Homa Microbenchmarks
* **Setup**: 2 physical machines (`node0` as server, `node1` as client).

#### 1a. Server (single-thread) — for latency 32B + throughput 1MB:
```sh
cd ~/eTran/eTran/micro_kernel && sudo ./micro_kernel -i ens1f1np1 -q 20 -w 5 &
sleep 2
cd ~/eTran/eTran/homa_app && ETRAN_PROTO=homa ./cp_node server
```
> **⚠️ `ETRAN_PROTO=homa` is MANDATORY for the server too** — without it, the pre-main constructor crashes (segfault).

#### 1b. Server (multi-thread) — for 500KB server throughput + 32B RPC rate:
```sh
# Kill previous server first, then:
cd ~/eTran/eTran/micro_kernel && sudo ./micro_kernel -i ens1f1np1 -q 20 -w 5 &
sleep 2
cd ~/eTran/eTran/homa_app && ETRAN_PROTO=homa ./cp_node server --ports 7 --queues 20
```
> The server creates 7 listening threads on ports 4000–4006, handling each client port in parallel.

#### 2. On Client (`node1`):

* **Median Latency (32B, single-thread)**:
  ```sh
  cd ~/eTran/eTran/micro_kernel && sudo ./micro_kernel -i ens1f1np1 -q 20 -w 5 &
  sleep 2
  cd ~/eTran/eTran/homa_app
  ETRAN_PROTO=homa ./cp_node client --workload 32 --first-server 0 --one-way
  ```

* **Throughput (1MB, single-thread)** — use `--client-max 2` to saturate the pipeline:
  ```sh
  ETRAN_PROTO=homa ./cp_node client --workload 1000000 --first-server 0 --one-way --client-max 2
  ```

* **Server Throughput (7 ports, 500KB)** — requires multi-thread server (1b):
  ```sh
  ETRAN_PROTO=homa ./cp_node client --workload 500000 --ports 7 --queues 20 \
    --first-server 0 --one-way --server-ports 7 --client-max 14
  ```
  > `client_port_max = max(14/7, 1) = 2` per port → 14 outstanding total. Should saturate 25 Gbps link.

* **Client RPC Rate (7 ports, 32B)** — requires multi-thread server (1b):
  ```sh
  ETRAN_PROTO=homa ./cp_node client --workload 32 --ports 7 --queues 20 \
    --first-server 0 --one-way --server-ports 7 --client-max 35
  ```
  > `client_port_max = max(35/7, 1) = 5` per port → 35 outstanding total. Aiming for ~2.9 Mops at ~12 µs RTT.

---

### MEASURE 2: Homa Cluster Slowdown
* **Setup**: 10 physical machines (`node0` to `node9`), each running both client and server concurrently.

#### On each node (`node<N>` where `N` is 0 to 9):
```sh
cd ~/eTran/eTran/micro_kernel && sudo ./micro_kernel -i ens1f1np1 -q 20 -w 4 &   # Use -w 2/3/4/5 for W2/W3/W4/W5
sleep 2
cd ~/eTran/eTran/homa_app
ETRAN_PROTO=homa ./cp_node client --both 5 --id <N> --workload w4 --server-nodes 10 --queues 20 --first-server 0 --one-way
```
*To dump latency results, run inside the `./cp_node` interactive console:*
```sh
dump_times w4.txt
```

---

### MEASURE 3: TCP Echo Throughput
* **Setup**: 2 physical machines (`node0` as server, `node1` as client). The paper uses 5 clients for aggregate throughput; with 2 machines the absolute throughput will be lower but the relative eTran gain is still measurable.

#### 1. On Server (`node0`):
```sh
cd ~/eTran/eTran/micro_kernel && sudo ./micro_kernel -i ens1f1np1 -q 20 &
sleep 2
cd ~/eTran/eTran/tcp_app
LD_PRELOAD=../shared_lib/libetran.so ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=5 ETRAN_NR_NIC_QUEUES=20 ./epoll_server -t 5 -b 1024 -s
```

#### 2. On Client (`node1`):
* **Throughput (1KB messages)**:
  ```sh
  cd ~/eTran/eTran/micro_kernel && sudo ./micro_kernel -i ens1f1np1 -q 20 &
  sleep 2
  cd ~/eTran/eTran/tcp_app
  LD_PRELOAD=../shared_lib/libetran.so ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=5 ETRAN_NR_NIC_QUEUES=20 ./epoll_client -t 5 -f 100 -o 64 -b 1024 -s -i <IP_node0>
  ```
* **Throughput (2KB messages)**: change `-b 1024` to `-b 2048`.
  > **⚠️ Known bug (both epoll_server and epoll_client):** The `-s` flag **disables** short-response (100B replies), despite the help text claiming it "enables" it. This flag is required for correct throughput benchmarking (full-size echo).
  >
  > **⚠️ Known bug (epoll_server only):** The `-d` flag (dump_io_stats) is documented in the help text but is **missing from the getopt string** — using it will cause an error. Additionally, the `-q` flag is accepted but has no runtime effect.
  >
  > **⚠️ Known bug (epoll_client only):** The `-l` (max_buf_size) and `-q` (nr_queues) flags are accepted but have no runtime effect.

---

### MEASURE 4: Key-Value Store
* **Setup**: 2 physical machines (`node0` as server, `node1` as client). The paper uses 5 clients with 6K connections each (total 30K); with 2 machines run 1 client at 6K connections.
* **Paper reference**: 5 clients, 6K connections per client, 32 outstanding/conn, Zipf s=0.9, 100K keys, 32B keys, 64B values, 9:1 GET:SET.

#### 1. On Server (`node0`):
```sh
cd ~/eTran/eTran/micro_kernel && sudo ./micro_kernel -i ens1f1np1 -q 20 &
sleep 2
cd ~/eTran/eTran/tcp_app
# flexkvs_server takes 3 POSITIONAL arguments: CONFIG_PATH THREADS QUEUES
# (mtcp_init is behind #ifdef USE_MTCP, so the config path is stored but unused)
LD_PRELOAD=../shared_lib/libetran.so ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=5 ETRAN_NR_NIC_QUEUES=20 ./flexkvs_server /dev/null 5 20
```

#### 2. On Client (`node1`):
```sh
cd ~/eTran/eTran/micro_kernel && sudo ./micro_kernel -i ens1f1np1 -q 20 &
sleep 2
cd ~/eTran/eTran/tcp_app
# -t 5 threads, -C 1200 connections/thread = 6K total (6K per client as per paper)
LD_PRELOAD=../shared_lib/libetran.so ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=5 ETRAN_NR_NIC_QUEUES=20 ./flexkvs_bench -t 5 -C 1200 -p 32 -n 100000 -v 64 -z 0.9 <IP_node0>:11211
```
> **⚠️ Known bugs in flexkvs_bench:**
> 1. **`-n` help text is wrong**: The help says `[default 1000]`, but `init_settings()` actually defaults to **100000**. The command above correctly uses `-n 100000`.
> 2. **`-r` / `--trace` is broken**: Documented but missing a `case 'r':` handler — using it triggers `abort()`. Do not use.
> 3. **`-C` long option typo**: Help documents `--connns` (triple n), but the actual long option is `--conns` (double n). Use the short form `-C` instead.
> 4. **Hidden flags**: `-q` (queues) and `-d` (delay) are functional but undocumented.

---

### MEASURE 5: Precision of Rate Limiting (Pacing)
* **Setup**: 2 physical machines (`node0` as server, `node1` as client).

#### 1. On Server (`node0`):
```sh
cd ~/eTran/eTran/micro_kernel && sudo ./micro_kernel -i ens1f1np1 -q 20 -w 5 &
sleep 2
cd ~/eTran/eTran/homa_app && ETRAN_PROTO=homa ./cp_node server
```

#### 2. On Client (`node1`) with 8 Gbps pacing target:
```sh
cd ~/eTran/eTran/micro_kernel && sudo ./micro_kernel -i ens1f1np1 -q 20 -w 5 &
sleep 2
cd ~/eTran/eTran/homa_app
ETRAN_PROTO=homa ./cp_node client --workload 1000000 --first-server 0 --gbps 8.0
```

---

### MEASURE 6: Overhead of XDP_EGRESS
* **Setup**: Standalone on **1 physical machine** (No eTran microkernel needed).

```sh
cd ~/eTran/bench-afxdp
sudo taskset -c 2 ./xdpsock -i ens1f1np1 -q 2 -t -f 64 -B -N
```
> **⚠️ Known bugs in xdpsock:**
> 1. **CRASH**: `-I` / `--irq-string` has a conflicting definition: `long_options` says `no_argument` but the handler reads `optarg`. Using the long form `--irq-string` will dereference a NULL pointer and **crash**. Avoid this flag entirely.
> 2. **`-F` / `--force` vs `--frags`**: The help text documents `--frags`, but the actual long option accepted is `--force`. Use the short form `-F` instead.
> 3. **`-S` and `-N` documentation**: The help text shows `--xdp-skb=n` and `--xdp-native=n` implying they take an argument, but they do not. Just `-S` or `-N` suffices.

---

### MEASURE 7: Packet Generation with XDP_GEN
* **Setup**: Standalone on **1 physical machine**.

```sh
cd ~/eTran/bench-afxdp
sudo taskset -c 2,3 ./xdpsock -i ens1f1np1 -q 2 -l -B -N
```

---

### MEASURE 8: CPU Cycles per Request (Perf)
* **Setup**: 2 physical machines (`node0` as server, `node1` as client).

#### On Server (`node0`):
```sh
cd ~/eTran/eTran/micro_kernel
sudo perf record -g -e cycles:u ./micro_kernel -i ens1f1np1 -q 1
# Alternatively, attach dynamically to already running microkernel:
# sudo perf record -g -e cycles:u -p $(pgrep micro_kernel) -- sleep 30
sudo perf report
```

---

### MEASURE 9: Retransmission under Packet Loss
* **Setup**: 2 physical machines (`node0` as server, `node1` as client).

#### Add artificial packet loss on both nodes (`node0` and `node1`):
```sh
sudo tc qdisc add dev ens1f1np1 root netem loss 1%     # To introduce 1% loss
sudo tc qdisc change dev ens1f1np1 root netem loss 5%  # To switch to 5% loss
# To clean up / remove packet loss:
sudo tc qdisc del dev ens1f1np1 root
```

#### TCP Retransmission (100 concurrent flows):
* **On Server (`node0`)**:
  ```sh
  cd ~/eTran/eTran/micro_kernel && sudo ./micro_kernel -i ens1f1np1 -q 20 &
  sleep 2
  cd ~/eTran/eTran/tcp_app
  LD_PRELOAD=../shared_lib/libetran.so ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 ./epoll_server -b 1024 -s
  ```
* **On Client (`node1`)**:
  ```sh
  cd ~/eTran/eTran/micro_kernel && sudo ./micro_kernel -i ens1f1np1 -q 20 &
  sleep 2
  cd ~/eTran/eTran/tcp_app
  LD_PRELOAD=../shared_lib/libetran.so ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 ./epoll_client -f 100 -b 1024 -s -i <IP_node0>
  ```

#### Homa Retransmission (100 concurrent flows in both mode):
* **On `node0`**:
  ```sh
  cd ~/eTran/eTran/micro_kernel && sudo ./micro_kernel -i ens1f1np1 -q 20 -w 5 &
  sleep 2
  cd ~/eTran/eTran/homa_app
  ETRAN_PROTO=homa ./cp_node client --both 5 --id 0 --workload 1000 --ports 100 --queues 20 --server-nodes 2 --first-server 0
  ```
* **On `node1`**:
  ```sh
  cd ~/eTran/eTran/micro_kernel && sudo ./micro_kernel -i ens1f1np1 -q 20 -w 5 &
  sleep 2
  cd ~/eTran/eTran/homa_app
  ETRAN_PROTO=homa ./cp_node client --both 5 --id 1 --workload 1000 --ports 100 --queues 20 --server-nodes 2 --first-server 0
  ```


