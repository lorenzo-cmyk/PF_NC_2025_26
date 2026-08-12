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

## **1. Introduction**

#### **1. Motivation and Intuition**

The central contribution of eTran is a safe and extensible kernel transport framework that combines the protection of kernel networking with the development speed and performance techniques usually associated with user-space transports.

* **Limits of the native kernel stack (Linux TCP):** Modifying the Linux transport stack takes years. DCTCP took four years to enter the mainline kernel, MPTCP took almost a decade, and Homa, proposed in 2018, remains an external module. The traditional data path also has high costs due to socket and file system abstractions, heavy `sk_buff` structures, and repeated context switches for I/O system calls.
* **Risks of Kernel Bypass (User Space/DPDK):** Moving transport into user space enables fast evolution, but it removes kernel isolation and protection. A bug, crash, or malicious behavior in an application can alter acknowledgments, sequence numbers, or timers. It can also compromise the correctness of other tenants and prevent the kernel from enforcing global security policies, firewalling, and telemetry.
* **The eBPF solution and recent enablers:** eTran keeps transport state inside protected eBPF maps in the kernel, separate from application memory, with program safety checked by the statically verified eBPF verifier. Recent eBPF advances in the Linux kernel make this approach feasible today: `dynptr` in version 5.19, dynamic memory allocation in version 6.1, `rbtree` support in version 6.3, and new `kfuncs` allow eBPF programs to manage complex data structures that were previously impractical.

#### **2. Limits of Standard eBPF and Linux Kernel Patches**

Native eBPF/XDP was designed for ingress inspection and lacks the capabilities required by a complete transport stack. To overcome these limitations, the authors extended the Linux kernel with approximately 2,500 lines of C code and introduced four main changes:

1. **New `XDP_EGRESS` Hook (Egress Handling and Isolation):** AF_XDP already supports egress: an application can transmit packets by placing descriptors on the TX ring. However, the stock AF_XDP path has no hook that invokes an eBPF program when a packet is added to the TX ring, so a kernel transport cannot validate or shape outgoing traffic through eBPF unless it can intercept it. The alternative of crafting the full TCP, Homa, IP, and Ethernet headers in userspace before transmission would mean trusting the application to produce correct packets, which contradicts the isolation goal of the framework. The `XDP_EGRESS` hook closes this gap. It is placed in the vendor-agnostic AF_XDP function `xsk_tx_peek_desc`, where the eBPF program intercepts every packet transmitted by AF_XDP, fills in the TCP, Homa, IP, and Ethernet headers, checks windows and rates, and applies pacing through `XDP_REDIRECT`. It adds an `umem_id` field to the packet context so that eTran can verify that the application's memory pool ID matches the pool registered for the connection, blocking spoofing attempts and unauthorized access.
2. **New `XDP_GEN` Hook (In-Kernel ACK/Credit Generation):** This hook is placed in `xdp_do_flush`, which runs at the end of a NAPI cycle. It avoids the cost of dynamic allocation: when the ingress path requires an ACK or credit, it pushes the metadata into a per-CPU queue. `XDP_GEN` retrieves the metadata, uses buffers pre-allocated through `page_pool`, and transmits control packets in high-speed batches.
3. **New `BPF_MAP_TYPE_PKT_QUEUE` Map and BPF Timers (Pacing):** This map stores pointers to deferred packets such as `xdp_frame` objects. It is integrated with BPF timers extended with two asynchronous execution modes: per-CPU execution through `NETTX_SOFTIRQ` for rate-based pacing, as used by TCP, and a global kernel thread for complex global scheduling, such as Homa credit management.
4. **Out-of-Order Completion Support for AF_XDP:** AF_XDP natively requires buffers to be recycled in order. Since eBPF pacing holds and delays some packets, the authors modified AF_XDP memory management and the network card driver, including approximately 20 lines of code in the Mellanox `mlx5` driver, to support asynchronous and out-of-order buffer completion and recycling.

#### **3. Practical Architecture and Execution Flow**

eTran is organized into three components:

* **Control Path Daemon (Root User-Space Process):** A centralized manager with `root` privileges (the `micro_kernel` process) creates AF_XDP sockets, allocates UMEM, loads eBPF programs into the kernel, and manages connection handshakes such as the TCP SYN and ACK exchange. It runs floating-point congestion control by updating eBPF maps through shared `BPF_F_MMAPABLE` memory and handles retransmissions after severe timeouts.
* **Kernel Data Path (eBPF):** The transport engine runs inside the kernel. It performs high-speed I/O in the softirq and NAPI contexts while keeping connection state, timers, windows, and sequence numbers in protected BPF maps.
* **User Transport Library (`LD_PRELOAD` or RPC API):** An unprivileged library that is the application's only way onto the eBPF data path, since direct access requires `root` privileges and queue multiplexing and eTran deliberately does not trust applications with it. The library exposes a **Virtual AF_XDP Socket** and translates application calls into operations on shared AF_XDP ring buffers, so the application never touches kernel state directly. It can be linked at compile time, exposing both an RPC API and a new Socket API, or injected dynamically into an existing binary via `LD_PRELOAD`; the latter is possible because the Socket API is POSIX-compliant, making it a drop-in replacement for the standard socket interface.

<img src="Figures/eTran_Architecture.png" alt="eTran Architecture" style="height: 5cm; width: auto;">

##### **Practical Connection Lifecycle:**
1. **Setup and Handshake (Control Plane):** The application triggers a connection request: for example, it calls `socket()` or `connect()` through the Socket API, or it uses the RPC API directly. Either way, the library intercepts or translates the call and sends a request through **LRPC** to the root daemon. All privileged setup happens here, on the daemon's side: it creates the AF_XDP socket (which requires `root`/`CAP_NET_RAW`), allocates the UMEM as shared memory (`/dev/shm`), binds the socket to a NIC queue, and loads the eBPF programs. It then passes the already-configured socket file descriptor to the application through a Unix socket (`SCM_RIGHTS` fd passing), so that the unprivileged application can `mmap` the rings and the UMEM pages into its address space. The daemon also manages the network SYN/ACK handshake and installs the control information in the kernel's eBPF maps.
2. **Data Transfer (Direct Data Plane - Daemon Bypassed):** After setup, the daemon is out of the data path. During `write()`, the application copies data into the shared UMEM pages and submits descriptors on the TX ring. The `XDP_EGRESS` hook validates each packet (checking the `umem_id` against the pool registered for the connection), applies headers and pacing through the BPF maps, and transmits the packets. During `read()`, the `XDP` hook validates incoming packets, updates BPF state, and places them in the AF_XDP receive ring, where the application reads them directly.
3. **Trust Boundary and Crash Isolation:** The application only ever touches its own UMEM buffers and ring descriptors. It cannot load eBPF programs, read the stateful BPF maps (windows, sequence numbers, timers), or access other tenants' data. If the application crashes or misbehaves, it can at worst corrupt its own buffers: the kernel's network state remains protected and intact.

#### **4. Case Studies and Validation**

As discussed, eTran is not a single protocol but an extension framework: its in-kernel primitives (`XDP_EGRESS`, `XDP_GEN`, `PKT_QUEUE`, BPF timers) span the full transport stack, from header generation to congestion control, flow control, and scheduling.

To demonstrate the feasibility of the platform, the authors implemented two proof-of-concept transports that cover opposite datacenter transport paradigms:

1. **TCP with DCTCP:** Built on classic **POSIX-like stream APIs**, it implements a connection-oriented, sender-driven transport with rate-based pacing.
2. **Homa:** In addition to POSIX-like APIs, the authors developed **RPC message APIs** and implemented Homa as a connectionless, receiver-driven transport with credit- and priority-based scheduling using SRPT.


## **2. Selected Results**

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

## **3. Environment Setup**

The reproduction was conducted on a ten-node allocation at the CloudLab Utah site, the same testbed used for the original experiments. The evaluation therefore used the same `xl170` node type, Mellanox 2410 switch fabric, and official paper artifact as the authors, with all nodes connected directly to a single switch. The hardware, software, and runtime configuration are described below.

#### **Hardware Environment**

The cluster was provisioned at the CloudLab Utah site and contained ten physical nodes connected through the same rack switch:

* **Cluster:** Ten `xl170` nodes in one rack on the CloudLab Utah site.
* **CPU:** Single-socket Intel Xeon E5-2640 v4 at 2.40 GHz, with 10 physical cores and 20 logical CPUs per node.
* **Memory:** 64 GB ECC DDR4 RAM per node.
* **Storage:** A 16 GB CloudLab blockstore mounted at `/mydata` on each node.
* **Network Card:** Mellanox ConnectX-4 Lx 25 GbE NIC using the `mlx5` driver.
* **Network Switch:** Mellanox 2410 25 GbE rack switch.

#### **Software Environment**

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

#### **Configuration Parameters**

The main system and network parameters were kept consistent across the benchmarks:

* **Switch configuration:** The Mellanox 2410 was used with its default configuration, including a 70 KB ECN marking threshold and jumbo frames disabled, so the MTU was kept at 1500 bytes. CloudLab's documentation states that the switch is not exposed as a managed component, so its configuration could not be changed.
* **NIC tuning:** RX and TX flow control were disabled, adaptive coalescing was turned off, and GRO and TSO remained enabled (disabling the offloads was found to hurt performance on this hardware).
* **Kernel tuning:** Hyper-Threading (SMT) was enabled, kernel mitigations were disabled, CPU C-states were disabled, and PCIe ASPM was disabled. The `network-throughput` profile from `tuned` was enabled.
* **eTran queues and CPU placement:** The `micro_kernel` used its default 20 NIC queues, with the control loop internally pinned to CPU 19 via `CP_CPU` and no external `taskset`.
* **Network preparation:** Static ARP entries were installed for all nodes because eTran does not implement ARP in its data path; `/etc/hosts` entries let each node reference the others by hostname without DNS, as the benchmarks expect. The benchmark interface was `ens1f1np1`, with addresses in the `192.168.6.0/24` network.
* **Stack-specific parameters:** The Linux-DCTCP baseline used `tcp_dctcp` as the congestion-control algorithm, enabled ECN with `net.ipv4.tcp_ecn=1`, and enabled TCP timestamps. The Linux-Homa evaluation installed the `homa` qdisc on the benchmark interface and set `net.homa.max_gso_size=100000` and `net.homa.hijack_tcp=0`.

## **4. Experiment Results**

This section reports only the values measured on the reproduction cluster. The comparison with the paper's reported results is deferred to Section 5.

#### **4.1 Execution Procedure**

The same basic procedure was used for each workload: stale processes and eTran shared-memory objects were cleaned up, the stack-specific setup was re-applied after each reboot, servers and the eTran `micro_kernel` were started in `screen` sessions, clients were launched with workload-specific timeouts and a 0.3 second stagger for multi-client tests, and the output was collected and read for the relevant metric.

Run durations were workload-specific: 15 seconds for single-stream and small-message tests, 30 seconds for concurrent Homa tests, 20 to 45 seconds for TCP key-value tests, and 5, 10, 20, or 30 seconds for the all-to-all workloads depending on the offered load.

#### **4.2 Measurement Method**

The benchmark programs reported the primary measurements directly. RTT distributions came from client output, with P50 and P99 denoting the median and 99th percentile of the observed RTTs. Throughput was read in Gbps from client output or server logs, RPC rates and `flexkvs` throughput were reported as aggregate operations per second, and `perf stat` collected the cycles and instructions used for the CPU-cycle metrics.

Ranges reflect either different configurations or run-to-run variation, and peak/steady-state pairs are separate phases or load points; no confidence intervals were computed.

#### **4.3 Homa Measurements**

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

#### **4.4 DCTCP Measurements**

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

#### **4.5 CPU Measurements**

Metrics 21-22 estimate the per-request CPU cost of the TCP and Homa transports, collected with `perf stat`.

| Metric | Workload                                                 |     eTran | Linux |
| ------ | -------------------------------------------------------- | --------: | ----: |
| 21     | TCP CPU cycles per request, 1KB stream (kcycles)         | **~2.93** |  ~7.4 |
| 22     | Homa CPU cycles per request, active processing (kcycles) |    **~5** | ~18.6 |

For metric 22, the raw eTran figure was ~1357 kcycles including AF_XDP busy-polling, and the workloads differed (1MB for eTran, 32B for Linux-Homa).

#### **4.6 Key Takeaways**

**eTran strengths (DCTCP):** eTran-DCTCP outperformed Linux-DCTCP on every measured TCP workload: streaming throughput, persistent connections, request latency, and the key-value application.

**eTran weaknesses (some Homa workloads):** Concurrent fan-in throughput was well below both Linux stacks, the shortest-10% messages in all-to-all traffic saw much higher latency, and the offered load of the W4/W5 workloads could not be drained, leaving those runs overloaded rather than in steady state. Its single-stream RPC latency, however, was the lowest of the measured set.

## **5. Reproducibility Assessment of the Paper**

The local measurements do not reproduce the reported evaluation as a whole: a few results are close, especially single-stream latency and some TCP workloads, but the main Homa scalability results show substantial gaps, and several experiments could not be reproduced with the available artifact. The comparison below uses the measurements from Section 4 and the values reported by the authors.

#### **5.1 Homa Results**

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

Metrics 7-12 cover the all-to-all workloads; the paper frames the comparison as the Linux-Homa over eTran-Homa latency slowdown:

| Workload                      | Measured |    Paper |    Delta |
| ----------------------------- | -------: | -------: | -------: |
| W2, P99 slowdown              |     7.0x | 3.9-7.5x | in range |
| W2, P50 slowdown              |    0.86x | 1.4-3.6x |    below |
| W3, P99 slowdown              |     6.7x | 3.9-7.5x | in range |
| W3, P50 slowdown              |    0.87x | 1.4-3.6x |    below |
| W4, shortest-10% P50 slowdown |   0.008x |     4.1x |    below |
| W4, shortest-10% P99 slowdown |   0.002x |     4.3x |    below |
| W5, shortest-10% P50 slowdown |   0.004x |     3.9x |    below |
| W5, shortest-10% P99 slowdown |   0.002x |     2.9x |    below |

#### **5.2 TCP and DCTCP Results**

The TCP results were more favorable, but they still do not establish a complete reproduction of the reported evaluation:

| Metric | Workload                             | Measured |    Paper |    Delta |
| ------ | ------------------------------------ | -------: | -------: | -------: |
| 13     | 1KB stream, 64 outstanding (ratio)   |    3.95x |     4.8x |     -18% |
| 15     | 1,000 persistent connections (ratio) |    ~2.8x |    2.26x |     +24% |
| 18     | `flexkvs` throughput (ratio)         |    ~2.6x | 2.4-4.8x | in range |
| 19     | `flexkvs` latency P50 (us)           |       14 |     17.2 |     +19% |
| 20     | `flexkvs` latency P99 (us)           |       16 |     27.5 |     +42% |
| 21     | TCP CPU per request (kcycles)        |    ~2.93 |     4.37 |     +33% |

Ratios are shown because the paper reports ratios for these metrics; they are eTran-DCTCP over Linux-DCTCP.

#### **5.3 Reproducibility Assessment**

**Reproduction outcome:** The reproduction failed in the broad sense: it did not reproduce the complete performance profile. The failure was not uniform: single-stream latency, several TCP workloads, and the low-load key-value measurements were close to or better than the reported values, but eTran-Homa did not sustain the expected performance under concurrent fan-in, small-message RPC load, or high offered load. The evaluation was also incomplete: the artifact lacks the short-lived TCP benchmark (metrics 16-17) and the standalone BPF programs for the XDP microbenchmarks, and the W4/W5 eTran runs were overloaded.

**Artifact documentation:** The authors provide the main benchmark utilities, but no per-metric example commands or scripts; the execution details had to be reconstructed from the documentation and source code, and different choices change the workload that is actually measured. The discrepancy cannot be resolved from the artifact alone; the authors were contacted for clarification, but no response was received.

**Baseline compatibility:** The stated Linux-Homa baseline adds a compatibility problem: the paper identifies HomaModule commit `8321cde` (March 2023) with Linux `6.6.0`, a combination that cannot compile unmodified. Commit `8321cde` still uses the `.sendpage` field and the pre-6.5 ioctl signature (`unsigned long arg`), both removed in Linux 6.5; later fixes (commit `df0daa5a9`) introduced `#include <net/rps.h>`, a header absent until Linux 6.9. The reproduction therefore used mainline Linux `v6.17.8` with HomaModule `main` at commit `9edb9589`, a functional path that is not the stated baseline.

**Hardware:** The paper describes the `xl170` as having two CPUs with 10 cores each; the provisioned nodes instead had a single Intel Xeon E5-2640 v4 with 10 cores and 20 logical CPUs, so the paper's two-CPU description appears to be a typo.

**Overall:** The artifact was usable for building and running the principal workloads, but not for reproducing the entire evaluation; the reproduction is therefore partial and, for the paper's overall claims, unsuccessful.

## 6. Further Exploration

We chose the first approach: exploring how OS-level tuning impacts the eTran Homa path on the CloudLab cluster[cite: 1]. The standard tuning recipe targets DPDK link-bound workloads, but eTran's Homa path is CPU-bound per RPC[cite: 1]. We aimed to determine if the throughput gap observed during reproduction could be closed through system tuning[cite: 1].

### 6.1. Methodology and Result

We evaluated every OS-level setting against the three most important metrics: 32B latency (M1), 500KB throughput (M3), and 32B RPC rate (M5)[cite: 1]. The reference recipe was re-applied item by item, with a full cluster restart between each step to isolate the effects[cite: 1]. 

**Results Table (Cumulative Application)**

| Change applied | M1 P50 (us) | M3 (Gbps) | M5 (Kops) | Verdict |
| :--- | :--- | :--- | :--- | :--- |
| Baseline | 12.59 | 12.78 | 927 | Reference[cite: 1] |
| `irqbalance` off, `performance` governor, THP=never, `bpf_stats_enabled=0`, `numa_balancing=0`, `ksm/run=0` | ~12.5 | 12.8 | 928 | Neutral / No effect[cite: 1] |
| `no_turbo=1` | 11.29 | 11.98 | 568 (-39%) | REVERTED (Hurts CPU)[cite: 1] |
| `gro off`, `tso off` (on top) | n/a | n/a | 568 | REVERTED (Hurts throughput)[cite: 1] |
| `taskset`, NIC ring 4096, 2M hugepages | 12.5 | 12.8 | 928 | No effect[cite: 1] |

**Key Discoveries:**
*   **Essential Tunings:** Disabling mitigations, C-states, and ASPM in GRUB is required for sub-15 us latency[cite: 1]. The `performance` CPU governor and keeping SMT (Hyper-Threading) enabled are critical for stable RPC rates[cite: 1].
*   **Internal Microkernel Tuning:** The eTran root daemon (`micro_kernel`) automatically handles several tuning and setup tasks internally[cite: 1, 2]. It pins its own control loop (e.g., `CP_CPU=19`), pins application threads, and manages 2M hugepages for the AF_XDP UMEM[cite: 1, 2]. This built-in configuration renders manual OS-level interventions like `taskset` redundant and ineffective[cite: 1].
*   **Detrimental Tunings:** Turning off Intel Turbo or GRO drops the RPC rate by 39%, as eTran Homa relies heavily on maximum clock speed and GRO batching[cite: 1].
*   **Irrelevant Tunings:** Most standard link-bound tunings (like disabling `irqbalance` or NUMA balancing) are bypassed entirely by eTran's AF_XDP busy-polling[cite: 1].
*   **The Bottleneck is Software:** The remaining throughput gap compared to the paper is not an OS tuning issue[cite: 1]. It stems from inherent eBPF software bottlenecks (e.g., `XDP_GEN` grant dispatch and BPF map contention) that require upstream code optimization[cite: 1].


## 7. Conclusion

Overall, our reproduction of the paper was only partially successful. However, the TCP/DCTCP benchmarks were a major highlight, decisively proving that eTran-DCTCP superior to the native Linux-DCTCP implementation across every measured workload. Conversely, the scalability results of the Homa protocol-especially concurrent throughput and the handling of **high-frequency small RPCs-proved to be significantly lower than reported.**

Despite the architectural limitations that emerged under heavy Homa loads, the eTran approach is highly promising and useful in several real-world scenarios:

A Superior Replacement for Native Linux-DCTCP: eTran unequivocally outperforms standard Linux-DCTCP. It delivers up to 3.95x higher streaming throughput (achieving ~7.19 Gbps compared to Linux's 1.8-2.8 Gbps for 1KB streams). It also handles large-scale concurrency far better, processing 1,000 persistent TCP connections at roughly 2.8x the rate of the native kernel. Because of this massive performance upgrade, eTran-DCTCP is highly suitable for key-value databases (as demonstrated by the flexkvs workload tests).

Unmatched CPU Efficiency for TCP: eTran is significantly more lightweight than the standard Linux stack. It consumes only about 2.93 CPU kcycles per request, making it approximately 2.5x more efficient than the ~7.4 kcycles required by the Linux TCP baseline.

Conversely, the scalability results of the Homa protocol,especially concurrent throughput and the handling of high,frequency small RPCs,proved to be significantly lower than reported, though eTran still maintained a slight edge in single-stream latency.


## Appendix

You are asked to write this report using Markdown. You can find a cheat sheet
of Markdown syntax at this [link](https://rust-lang.github.io/mdBook/format/markdown.html).

For generating a PDF file from your report you can use a tool of your choice.
*md2pdf* is one such tool. See this [link](https://pypi.org/project/md2pdf/)
for more information about it. You can also use an online editor such as [this](https://www.md2pdf.io/).

