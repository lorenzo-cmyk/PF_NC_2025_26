# **Replicating: "eTran: extensible kernel transport with eBPF"**

**Team Members:**

- Pierluigi Grossi, 10618314@polimi.it.
- Matteo Franken, 10831046@polimi.it.
- Lorenzo Chiroli, 10797603@polimi.it.

**Source Paper:** Zhongjie Chen, Qingkai Meng, ChonLam Lao, Yifan Liu, Fengyuan Ren, Minlan Yu,
and Yang Zhou: eTran: Extensible Kernel Transport with eBPF. In "22nd USENIX
Symposium on Networked Systems Design and Implementation (NSDI 25)", pages
407-425, Philadelphia, PA, 2025. USENIX Association.

_Paper URL_: <https://www.usenix.org/conference/nsdi25/presentation/chen-zhongjie>

**Project:** The repository contains the CloudLab profile used to set up the cluster, Ansible 
playbooks for configuring it, and runbooks documenting the procedures used to run the experiments 
and collect measurements.

_Project URL_: <https://github.com/lorenzo-cmyk/PF_NC_2025_26>

---

# **1. Introduction**

### **1. Motivation and Intuition**

The central contribution of eTran is a safe and extensible kernel transport framework that combines the protection of kernel networking with the development speed and performance techniques usually associated with user-space transports.

* **Limits of the native kernel stack (Linux TCP):** Modifying the Linux transport stack takes years. DCTCP took four years to enter the mainline kernel, MPTCP took almost a decade, and Homa, proposed in 2018, remains an external module. The traditional data path also has high costs due to socket and file system abstractions, heavy `sk_buff` structures, and repeated context switches for I/O system calls.
* **Risks of Kernel Bypass (User Space/DPDK):** Moving transport into user space enables fast evolution, but it removes kernel isolation and protection. A bug, crash, or malicious behavior in an application can alter acknowledgments, sequence numbers, or timers. It can also compromise the correctness of other tenants and prevent the kernel from enforcing global security policies, firewalling, and telemetry.
* **The eBPF solution and recent enablers:** eTran keeps transport state inside protected eBPF maps in the kernel, separate from application memory, with program safety checked by the statically verified eBPF verifier. Recent eBPF advances in the Linux kernel make this approach feasible today: `dynptr` in version 5.19, dynamic memory allocation in version 6.1, `rbtree` support in version 6.3, and new `kfuncs` allow eBPF programs to manage complex data structures that were previously impractical.

### **2. Limits of Standard eBPF and Linux Kernel Patches**

Native eBPF/XDP was designed for ingress inspection and lacks the capabilities required by a complete transport stack. To overcome these limitations, the authors extended the Linux kernel with approximately 2,500 lines of C code and introduced four main changes:

1. **New `XDP_EGRESS` Hook (Egress Handling and Isolation):** AF_XDP already supports egress: an application can transmit packets by placing descriptors on the TX ring. However, the stock AF_XDP path has no hook that invokes an eBPF program when a packet is added to the TX ring, so a kernel transport cannot validate or shape outgoing traffic through eBPF unless it can intercept it. The alternative of crafting the full TCP, Homa, IP, and Ethernet headers in userspace before transmission would mean trusting the application to produce correct packets, which contradicts the isolation goal of the framework. The `XDP_EGRESS` hook closes this gap. It is placed in the vendor-agnostic AF_XDP function `xsk_tx_peek_desc`, where the eBPF program intercepts every packet transmitted by AF_XDP, fills in the TCP, Homa, IP, and Ethernet headers, checks windows and rates, and applies pacing through `XDP_REDIRECT`. It adds an `umem_id` field to the packet context so that eTran can verify that the application's memory pool ID matches the pool registered for the connection, blocking spoofing attempts and unauthorized access.
2. **New `XDP_GEN` Hook (In-Kernel ACK/Credit Generation):** This hook is placed in `xdp_do_flush`, which runs at the end of a NAPI cycle. It avoids the cost of dynamic allocation: when the ingress path requires an ACK or credit, it pushes the metadata into a per-CPU queue. `XDP_GEN` retrieves the metadata, uses buffers pre-allocated through `page_pool`, and transmits control packets in high-speed batches.
3. **New `BPF_MAP_TYPE_PKT_QUEUE` Map and BPF Timers (Pacing):** This map stores pointers to deferred packets such as `xdp_frame` objects. It is integrated with BPF timers extended with two asynchronous execution modes: per-CPU execution through `NETTX_SOFTIRQ` for rate-based pacing, as used by TCP, and a global kernel thread for complex global scheduling, such as Homa credit management.
4. **Out-of-Order Completion Support for AF_XDP:** AF_XDP natively requires buffers to be recycled in order. Since eBPF pacing holds and delays some packets, the authors modified AF_XDP memory management and the network card driver, including approximately 20 lines of code in the Mellanox `mlx5` driver, to support asynchronous and out-of-order buffer completion and recycling.

### **3. Practical Architecture and Execution Flow**

eTran is organized into three components:

* **Control Path Daemon (Root User-Space Process):** A centralized manager with `root` privileges (the `micro_kernel` process) creates AF_XDP sockets, allocates UMEM, loads eBPF programs into the kernel, and manages connection handshakes such as the TCP SYN and ACK exchange. It runs floating-point congestion control by updating eBPF maps through shared `BPF_F_MMAPABLE` memory and handles retransmissions after severe timeouts.
* **Kernel Data Path (eBPF):** The transport engine runs inside the kernel. It performs high-speed I/O in the softirq and NAPI contexts while keeping connection state, timers, windows, and sequence numbers in protected BPF maps.
* **User Transport Library (`LD_PRELOAD` or RPC API):** An unprivileged library that is the application's only way onto the eBPF data path, since direct access requires `root` privileges and queue multiplexing and eTran deliberately does not trust applications with it. The library exposes a **Virtual AF_XDP Socket** and translates application calls into operations on shared AF_XDP ring buffers, so the application never touches kernel state directly. It can be linked at compile time, exposing both an RPC API and a new Socket API, or injected dynamically into an existing binary via `LD_PRELOAD`; the latter is possible because the Socket API is POSIX-compliant, making it a drop-in replacement for the standard socket interface.

![eTran Architecture](Figures/eTran_Architecture.png)

#### **Practical Connection Lifecycle:**
1. **Setup and Handshake (Control Plane):** The application triggers a connection request: for example, it calls `socket()` or `connect()` through the Socket API, or it uses the RPC API directly. Either way, the library intercepts or translates the call and sends a request through **LRPC** to the root daemon. All privileged setup happens here, on the daemon's side: it creates the AF_XDP socket (which requires `root`/`CAP_NET_RAW`), allocates the UMEM as shared memory (`/dev/shm`), binds the socket to a NIC queue, and loads the eBPF programs. It then passes the already-configured socket file descriptor to the application through a Unix socket (`SCM_RIGHTS` fd passing), so that the unprivileged application can `mmap` the rings and the UMEM pages into its address space. The daemon also manages the network SYN/ACK handshake and installs the control information in the kernel's eBPF maps.
2. **Data Transfer (Direct Data Plane - Daemon Bypassed):** After setup, the daemon is out of the data path. During `write()`, the application copies data into the shared UMEM pages and submits descriptors on the TX ring. The `XDP_EGRESS` hook validates each packet (checking the `umem_id` against the pool registered for the connection), applies headers and pacing through the BPF maps, and transmits the packets. During `read()`, the `XDP` hook validates incoming packets, updates BPF state, and places them in the AF_XDP receive ring, where the application reads them directly.
3. **Trust Boundary and Crash Isolation:** The application only ever touches its own UMEM buffers and ring descriptors. It cannot load eBPF programs, read the stateful BPF maps (windows, sequence numbers, timers), or access other tenants' data. If the application crashes or misbehaves, it can at worst corrupt its own buffers: the kernel's network state remains protected and intact.

### **4. Case Studies and Validation**

As discussed, eTran is not a single protocol but an extension framework: its in-kernel primitives (`XDP_EGRESS`, `XDP_GEN`, `PKT_QUEUE`, BPF timers) span the full transport stack, from header generation to congestion control, flow control, and scheduling.

To demonstrate the feasibility of the platform, the authors implemented two proof-of-concept transports that cover opposite datacenter transport paradigms:

1. **TCP with DCTCP:** Built on classic **POSIX-like stream APIs**, it implements a connection-oriented, sender-driven transport with rate-based pacing.
2. **Homa:** In addition to POSIX-like APIs, the authors developed **RPC message APIs** and implemented Homa as a connectionless, receiver-driven transport with credit- and priority-based scheduling using SRPT.

---

# **2. Selected Results**

The selected results compare the eTran transports with their Linux counterparts: eTran-Homa vs. Linux-Homa (the Homa kernel module) and eTran-DCTCP vs. Linux-DCTCP (standard Linux TCP with `tcp_dctcp` and ECN). Each pair implements the same protocol, so protocol design cannot explain differences between the two stacks; any gap reflects the data path alone (eTran's eBPF machinery versus the kernel's).

| Paper metric | What is measured                                                                                                                                                                                                                                                                                                                                                                                       | Why it matters                                                                                    |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| 1            | A single client sends a 32B request to one server and waits for the echoed response before sending the next request. The round-trip time (RTT) P50 and P99 are recorded.                                                                                                                                                                                                                               | Measures the latency cost of the data path for a small request with no request-level concurrency. |
| 2            | A single client sends 1MB messages to one server back-to-back over a single stream. Sustained throughput is recorded.                                                                                                                                                                                                                                                                                  | Tests bulk data movement without contention from concurrent flows.                                |
| 3-4          | 500KB messages are sent concurrently either from 7 clients to 1 server (many-to-one) or from 1 client to 7 servers (one-to-many). Aggregate throughput is recorded.                                                                                                                                                                                                                                    | Tests scaling when several flows share a receiver or a sender.                                    |
| 5-6          | 32B RPCs (Remote Procedure Calls) are sent either from 7 clients to 1 server or from 1 client to 7 servers, with multiple requests outstanding (i.e., sent but not yet answered). The aggregate RPC rate is recorded in Kops or Mops.                                                                                                                                                                  | Measures small-message processing capacity and contention.                                        |
| 7-12         | Ten nodes act as both clients and servers in the W2-W5 all-to-all workloads shipped with the eTran benchmark suite, a fork of the original Homa benchmarking suite that generates test traffic using different statistical distributions. W2 and W3 emphasize short messages, while W4 and W5 emphasize large messages at higher offered loads. Overall and shortest-10% RTT P50 and P99 are recorded. | Tests incast, contention, and tail behavior under mixed message sizes.                            |
| 13-14        | A TCP client and server exchange 1KB or 2KB messages with 64 requests outstanding. Stream throughput is recorded.                                                                                                                                                                                                                                                                                      | Stream throughput under the same TCP/DCTCP protocol: any gap isolates the eBPF path.              |
| 15           | Five clients maintain 200 persistent TCP connections each, for 1,000 connections in total. Each connection sends 64B requests with one request outstanding (the next one is sent only after the response). Aggregate request rate is recorded.                                                                                                                                                         | Tests connection management and small-request processing at high concurrency.                     |
| 18           | Five clients run the `flexkvs` key-value workload over 100,000 keys, with 32B keys and 64B values, a 90% GET and 10% SET mix, and key popularity following a Zipf distribution with skew 0.9, so that most requests hit a few hot keys. Each client uses multiple connections with several requests outstanding. Throughput is recorded.                                                               | Tests the transports in an application-style workload dominated by reads to a few hot keys.       |
| 19-20        | A single client runs the same `flexkvs` key-value workload as metric 18, with one thread, one connection, and one request outstanding. Request-latency P50 and P99 are recorded.                                                                                                                                                                                                                       | Measures application responsiveness without saturation from competing requests.                   |
| 21-22        | CPU cycles per request are measured on the benchmark processes: metric 21 reuses the TCP `epoll` benchmark of metric 13 (1KB messages), and metric 22 reuses the Homa `cp_node` benchmark of metric 1 (32B RPCs).                                                                                                                                                                                      | Estimates the processing cost of each transport path.                                             |

# **3. Environment Setup**

The reproduction was conducted on a ten-node allocation at the CloudLab Utah site, the same testbed used for the original experiments. The evaluation therefore used the same `xl170` node type, Mellanox 2410 switch fabric, and official paper artifact as the authors, with all nodes connected directly to a single switch. The hardware, software, and runtime configuration are described below.

### **Hardware Environment**

The cluster was provisioned at the CloudLab Utah site and contained ten physical nodes connected through the same rack switch:

* **Cluster:** Ten `xl170` nodes in one rack on the CloudLab Utah site.
* **CPU:** Single-socket Intel Xeon E5-2640 v4 at 2.40 GHz, with 10 physical cores and 20 logical CPUs per node.
* **Memory:** 64 GB ECC DDR4 RAM per node.
* **Storage:** A 16 GB CloudLab blockstore mounted at `/mydata` on each node.
* **Network Card:** Mellanox ConnectX-4 Lx 25 GbE NIC using the `mlx5` driver.
* **Network Switch:** Mellanox 2410 25 GbE rack switch.

### **Software Environment**

The software environment was built from the official projects:

* **Operating System:** Ubuntu 22.04 LTS.
* **eTran:** the custom `6.6.0-eTran+` kernel (with the `XDP_EGRESS`, `XDP_GEN`, `BPF_MAP_TYPE_PKT_QUEUE`, and AF_XDP out-of-order completion patches), `micro_kernel`, `libetran.so`, and the Homa and TCP applications.
* **Linux-Homa:** `PlatformLab/HomaModule`, providing the `cp_node` benchmark utility and the Homa kernel module, run on a separate Linux `v6.17.8` kernel.
* **Linux-DCTCP:** the eTran kernel with standard Linux TCP configured for DCTCP and ECN, using the HomaModule `cp_node` utility.
* **Repositories (pinned revisions):**
  * `eTran` (`https://github.com/eTran-NSDI25/eTran`): `f26ef186`
  * `eTran-linux` (`https://github.com/eTran-NSDI25/eTran-linux`): `3e960974`
  * `HomaModule` (`https://github.com/PlatformLab/HomaModule`): `9edb9589`
* **Compiler and libraries:** GCC/G++ 11.4.0, Clang/LLVM, `libbpf`, `libelf`, and the other dependencies installed from the Ubuntu 22.04 repositories, using the versions shipped by the distribution rather than pinned by the project.

### **Configuration Parameters**

The main system and network parameters were kept consistent across the benchmarks:

* **Switch configuration:** The Mellanox 2410 was used with its default configuration, including a 70 KB ECN marking threshold and jumbo frames disabled, so the MTU was kept at 1500 bytes. CloudLab's documentation states that the switch is not exposed as a managed component, so its configuration could not be changed.
* **NIC tuning:** RX and TX flow control were disabled, adaptive coalescing was turned off, and GRO and TSO remained enabled (disabling the offloads was found to hurt performance on this hardware).
* **Kernel tuning:** Hyper-Threading (SMT) was enabled, kernel mitigations were disabled, CPU C-states were disabled, and PCIe ASPM was disabled. The `network-throughput` profile from `tuned` was enabled.
* **eTran queues and CPU placement:** The `micro_kernel` used its default 20 NIC queues, with the control loop internally pinned to CPU 19 via `CP_CPU` and no external `taskset`. For eTran TCP, `ETRAN_NR_APP_THREADS` and `ETRAN_NR_NIC_QUEUES` were both set to the application thread count.
* **Network preparation:** Static ARP entries were installed for all nodes because eTran does not implement ARP in its data path; `/etc/hosts` entries let each node reference the others by hostname without DNS, as the benchmarks expect. The benchmark interface was `ens1f1np1`, with addresses in the `192.168.6.0/24` network.
* **Stack-specific parameters:** The Linux-DCTCP baseline used `tcp_dctcp` as the congestion-control algorithm, enabled ECN with `net.ipv4.tcp_ecn=1`, and enabled TCP timestamps. The Linux-Homa evaluation installed the `homa` qdisc on the benchmark interface and set `net.homa.max_gso_size=100000` and `net.homa.hijack_tcp=0`.

# **4. Experiment Results**

This section reports only the values measured on the reproduction cluster. The comparison with the paper's reported results is deferred to Section 5.

### **4.1 Execution Procedure**

The same basic procedure was used for each workload: stale processes and eTran shared-memory objects were cleaned up, the stack-specific setup was re-applied after each reboot, servers and the eTran `micro_kernel` were started in `screen` sessions, clients were launched with workload-specific timeouts and a 0.3 second stagger for multi-client tests, and the output was collected and read for the relevant metric.

Run durations were workload-specific: 15 seconds for single-stream and small-message tests, 30 seconds for concurrent Homa tests, 20 to 45 seconds for TCP key-value tests, and 5, 10, 20, or 30 seconds for the all-to-all workloads depending on the offered load.

### **4.2 Measurement Method**

The benchmark programs reported the primary measurements directly. RTT distributions came from client output, with P50 and P99 denoting the median and 99th percentile of the observed RTTs. Throughput was read in Gbps from client output or server logs, RPC rates and `flexkvs` throughput were reported as aggregate operations per second, and `perf stat` collected the cycles and instructions used for the CPU-cycle metrics.

Ranges reflect either different configurations or run-to-run variation, and peak/steady-state pairs are separate phases or load points; no confidence intervals were computed.

### **4.3 Homa Measurements**

Metrics 1-6 report latency, throughput, and RPC rate for eTran-Homa and Linux-Homa.

| Metric | Workload                                   |        eTran-Homa |     Linux-Homa |
| ------ | ------------------------------------------ | ----------------: | -------------: |
| 1      | 32B single-stream RTT, P50 / P99 (us)      | **12.59 / 14.85** | 15.26 / ~25-35 |
| 2      | 1MB single-stream throughput (Gbps)        |          **16.6** |         ~10-11 |
| 3      | 500KB, 7 clients to 1 server (Gbps)        |       ~12.78-12.9 |        **~23** |
| 4      | 500KB, 1 client to 7 servers (Gbps)        |             ~19.5 |      **~23.1** |
| 5      | 32B RPC rate, 7 clients to 1 server (Kops) |              ~927 |      **~1100** |
| 6      | 32B RPC rate, 1 client to 7 servers (Kops) |         **~1120** |           ~900 |

These rows correspond to metrics 7-12 and report RTT P50/P99 in microseconds. Because each workload mixes short and large messages, the `shortest-10%` columns compute the same percentiles over only the 10% smallest messages, isolating the latency seen by small, latency-sensitive messages instead of hiding it behind large transfers.

| Workload | eTran-Homa overall | Linux-Homa overall | eTran-Homa shortest-10% | Linux-Homa shortest-10% |
| -------- | -----------------: | -----------------: | ----------------------: | ----------------------: |
| W2       |     109 / **1344** |      **94** / 9453 |                91 / 118 |             **19 / 21** |
| W3       |     115 / **1428** |     **100** / 9511 |              110 / 1462 |             **20 / 22** |
| W4       |   3068 / **13713** |   **128** / 224000 |            2848 / 12604 |             **22 / 24** |
| W5       | 18007 / **130044** |  **1135** / 404000 |           14530 / 48026 |             **61 / 84** |

Bold marks the better value; where P50 and P99 favor different stacks, each percentile is bolded independently.

The W4 and W5 eTran runs used a 20 Gbps offered load that exceeded the measured drain rate, so queues grew continuously and these rows describe the overloaded local system rather than steady-state latency.

### **4.4 DCTCP Measurements**

Metrics 13-15 and 18-20 report streaming throughput, connection scalability, key-value workload performance, and request latency for eTran-DCTCP and Linux-DCTCP.

| Metric | Workload                                                             |     eTran-DCTCP |       Linux-DCTCP |
| ------ | -------------------------------------------------------------------- | --------------: | ----------------: |
| 13     | TCP stream, 1KB messages, 64 outstanding (Gbps / Kops)               |  **7.19 / 878** | 1.8-2.8 / 222-346 |
| 14     | TCP stream, 2KB messages, 64 outstanding (Gbps / Kops)               | **12.29 / 750** | 1.8-4.6 / 111-283 |
| 15     | 1,000 persistent TCP connections, 64B requests, one in flight (Kops) |        **~655** |              ~234 |
| 18     | `flexkvs` key-value workload, 100K keys, 90% GET / 10% SET (Kops)    |        **~730** |              ~278 |
| 19     | `flexkvs` request latency P50, single client, one in flight (us)     |          **14** |                17 |
| 20     | `flexkvs` request latency P99, single client, one in flight (us)     |          **16** |                24 |

Linux-DCTCP is reported as a range because its values varied 2-3x between runs.

### **4.5 CPU Measurements**

Metrics 21-22 estimate the per-request CPU cost of the TCP and Homa transports, collected with `perf stat`.

| Metric | Workload                                                 |     eTran | Linux |
| ------ | -------------------------------------------------------- | --------: | ----: |
| 21     | TCP CPU cycles per request, 1KB stream (kcycles)         | **~2.93** |  ~7.4 |
| 22     | Homa CPU cycles per request, active processing (kcycles) |    **~5** | ~18.6 |

For metric 22, the raw eTran figure was ~1357 kcycles including AF_XDP busy-polling, and the workloads differed (1MB for eTran, 32B for Linux-Homa).

### **4.6 Key Takeaways**

**eTran strengths (DCTCP):** eTran-DCTCP outperformed Linux-DCTCP on every measured TCP workload: streaming throughput, persistent connections, request latency, and the key-value application.

**eTran weaknesses (some Homa workloads):** Concurrent fan-in throughput was well below both Linux stacks, the shortest-10% messages in all-to-all traffic saw much higher latency, and the offered load of the W4/W5 workloads could not be drained, leaving those runs overloaded rather than in steady state. Its single-stream RPC latency, however, was the lowest of the measured set.

# **5. Reproducibility Assessment of the Paper**

The local measurements do not reproduce the reported evaluation as a whole: a few results are close, especially single-stream latency and some TCP workloads, but the main Homa scalability results show substantial gaps, and several experiments could not be reproduced with the available artifact. The comparison below uses the measurements from Section 4 and the values reported by the authors.

### **5.1 Homa Results**

| Metric | Workload                                   | Measured (eTran-Homa) | Paper (eTran) | Delta |
| ------ | ------------------------------------------ | --------------------: | ------------: | ----: |
| 1      | 32B RTT P50 (us)                           |                 12.59 |          11.8 | -6.7% |
| 2      | 1MB throughput (Gbps)                      |                  16.6 |          17.7 | -6.2% |
| 3      | 500KB, 7 clients to 1 server (Gbps)        |                 ~12.8 |          23.0 |  -44% |
| 4      | 500KB, 1 client to 7 servers (Gbps)        |                 ~19.5 |          22.7 |  -14% |
| 5      | 32B RPC rate, 7 clients to 1 server (Kops) |                  ~927 |          2900 |  -68% |
| 6      | 32B RPC rate, 1 client to 7 servers (Kops) |                 ~1120 |          3300 |  -66% |
| 22     | Homa CPU per request, active (kcycles)     |                    ~5 |          5.48 |   +9% |

Delta is relative to the paper value: positive means better, negative means worse.

### **5.2 TCP and DCTCP Results**

The TCP results were more favorable, but they still do not establish a complete reproduction of the reported evaluation:

| Metric | Workload                             |      Measured |    Paper |          Delta |
| ------ | ------------------------------------ | ------------: | -------: | -------------: |
| 13     | 1KB stream, 64 outstanding (ratio)   |         3.95x |     4.8x |           -18% |
| 15     | 1,000 persistent connections (ratio) |         ~2.8x |    2.26x |           +24% |
| 18     | `flexkvs` throughput (ratio)         |         ~2.6x | 2.4-4.8x |       in range |
| 19     | `flexkvs` latency P50 (us)           |            14 |     17.2 |           +19% |
| 20     | `flexkvs` latency P99 (us)           |            16 |     27.5 |           +42% |

Ratios are shown because the paper reports ratios for these metrics; they are eTran-DCTCP over Linux-DCTCP.

### **5.3 Reproducibility Assessment**

The reproduction therefore failed in the broad sense: it did not reproduce the complete performance profile across the Homa and TCP metric suite. The failure was not uniform. Single-stream latency, several TCP workloads, and the low-load key-value measurements were close to or better than the reported local values, but eTran-Homa did not sustain the expected performance under concurrent fan-in, small-message RPC load, or high offered load.

The evaluation was also incomplete. The public artifact did not contain the short-lived TCP benchmark required for metrics 16-17, and the standalone BPF programs needed for the XDP_EGRESS and XDP_GEN microbenchmarks were unavailable. The Homa CPU comparison used different workloads for eTran-Homa and Linux-Homa, and the W4/W5 eTran measurements were overloaded. These limitations prevent a complete one-to-one reproduction, even though the available benchmark suite was sufficient to expose the main performance bottlenecks in the local system.

Overall, the artifact was usable for building and running the principal eTran, Linux-Homa, and Linux-DCTCP workloads, but it was not sufficient to reproduce the entire evaluation. The reproduction should therefore be classified as partial and, for the paper's overall claims, unsuccessful.

### **5.4 Investigation of the Reproduction Gap**

The authors provide the main benchmark utilities, but one required utility is missing: the public eTran repository does not include the short-lived TCP connection benchmark used for metrics 16-17. The available `epoll_client` supports persistent connections only. The authors also do not provide per-metric example commands or scripts showing how to reproduce the reported measurements. The execution details had to be reconstructed from the available documentation and source code, including the command-line flags, process startup order, client and server roles, runtime, warm-up behavior, and output aggregation. Different choices in any of these details can change the workload that is actually measured, even when the same benchmark utility and message size are used.

As a result, it is possible that some of the local measurements do not exercise exactly the same workloads as the authors' measurements. The discrepancy cannot be resolved from the artifact alone. The authors were contacted for clarification, but no response was received.

### **5.5 Kernel Compatibility of the Stated Linux-Homa Baseline**

The stated Linux-Homa baseline contains a separate compatibility problem. The paper identifies HomaModule commit `8321cde` from March 2023 and Linux `6.6.0`. Source-level analysis shows that this combination cannot compile unmodified.

HomaModule commit `8321cde` still initializes the `.sendpage` field in both `struct proto_ops` and `struct proto`, and defines its Homa ioctl handler with the pre-6.5 signature using `unsigned long arg`. Linux 6.5 removed `sendpage` from both protocol structures and changed the `struct proto` ioctl argument to `int *karg`. The old Homa source therefore does not match the Linux 6.6 kernel APIs.

The same commit uses `kthread_complete_and_exit`, which is available by Linux 5.17. Together with the pre-6.5 socket APIs and the commit's `linux_6.0` branch, this identifies the source as a Linux 6.0-era implementation and, in any case, rules out Linux 6.5 and later. Later HomaModule fixes, including commit `df0daa5a9`, updated the ioctl and `sendpage` interfaces, but introduced `#include <net/rps.h>`. That header is absent from Linux 6.6, 6.7, and 6.8, and is available starting with Linux 6.9. The later fix therefore does not provide a Linux 6.6 solution either.

The reproduction used a functional compatibility path instead: the Ansible pipeline built mainline Linux `v6.17.8` and HomaModule `main` at commit `9edb9589`. This allowed Linux-Homa to run, but it is not the Linux 6.6 and `8321cde` combination stated for the baseline. The contradiction is therefore a reproducibility problem in the published setup, not merely a performance difference observed during the experiments.

### **5.6 Hardware Specification Discrepancy**

The paper describes the `xl170` instance as having two CPUs with 10 cores each. The provisioned `xl170` nodes instead had one Intel Xeon E5-2640 v4 CPU with 10 physical cores and 20 logical CPUs with Hyper-Threading enabled. The other listed hardware characteristics matched the evaluation environment, including memory, the ConnectX-4 Lx NIC, the 25 GbE network, and the Mellanox 2410 switch.

This is a minor hardware discrepancy, but it reduces the available physical-core capacity compared with the hardware configuration described in the paper. It may affect highly concurrent workloads, although it does not account for the separate kernel compatibility problem or the missing reproduction instructions.

# 6. Further Exploration

In this project you are required to also explore a research question of your own. Either:

1. Take the same test with different input workload or a variation of a test that is not present in the paper and comment the results you obtain
1. Implement a new feature on top of the system you evaluated and show a figure showing the performance

Discuss which approach you take, and what you explored. Explain what was your
motivation and importance of your question.

## 6.1. Methodology and Result

Report the experiment you designed for answering the question and share the
result you got.

Include:

- Graph(s) or table(s)
- How the experiment was conducted (share the details)
- What did you discover?


# 7. Conclusion

Conclude the report by mentioning the takeaways of experiments you did


---

# Appendix

You are asked to write this report using Markdown. You can find a cheat sheet
of Markdown syntax at this [link](https://rust-lang.github.io/mdBook/format/markdown.html).

For generating a PDF file from your report you can use a tool of your choice.
*md2pdf* is one such tool. See this [link](https://pypi.org/project/md2pdf/)
for more information about it. You can also use an online editor such as [this](https://www.md2pdf.io/).

