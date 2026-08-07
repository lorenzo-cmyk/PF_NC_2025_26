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

1. **New `XDP_EGRESS` Hook (Egress Handling and Isolation):** This hook is placed in the vendor-agnostic AF_XDP function `xsk_tx_peek_desc`. It allows eBPF to intercept packets transmitted by AF_XDP, fill in TCP, Homa, IP, and Ethernet headers, check windows and rates, and apply pacing through `XDP_REDIRECT`. It adds an `umem_id` field to the packet context so that eTran can verify that the application's memory pool ID matches the pool registered for the connection, blocking spoofing attempts and unauthorized access.
2. **New `XDP_GEN` Hook (In-Kernel ACK/Credit Generation):** This hook is placed in `xdp_do_flush`, which runs at the end of a NAPI cycle. It avoids the cost of dynamic allocation: when the ingress path requires an ACK or credit, it pushes the metadata into a per-CPU queue. `XDP_GEN` retrieves the metadata, uses buffers pre-allocated through `page_pool`, and transmits control packets in high-speed batches.
3. **New `BPF_MAP_TYPE_PKT_QUEUE` Map and BPF Timers (Pacing):** This map stores pointers to deferred packets such as `xdp_frame` objects. It is integrated with BPF timers extended with two asynchronous execution modes: per-CPU execution through `NETTX_SOFTIRQ` for rate-based pacing, as used by TCP, and a global kernel thread for complex global scheduling, such as Homa credit management.
4. **Out-of-Order Completion Support for AF_XDP:** AF_XDP natively requires buffers to be recycled in order. Since eBPF pacing holds and delays some packets, the authors modified AF_XDP memory management and the network card driver, including approximately 20 lines of code in the Mellanox `mlx5` driver, to support asynchronous and out-of-order buffer completion and recycling.

### **3. Practical Architecture and Execution Flow**

eTran is organized into three components:

* **Control Path Daemon (Root User-Space Process):** A centralized manager with `root` privileges creates AF_XDP sockets, allocates UMEM, loads eBPF programs into the kernel, and manages connection handshakes such as the TCP SYN and ACK exchange. It runs floating-point congestion control by updating eBPF maps through shared `BPF_F_MMAPABLE` memory and handles retransmissions after severe timeouts.
* **Kernel Data Path (eBPF):** The transport engine runs inside the kernel. It performs high-speed I/O in the softirq and NAPI contexts while keeping connection state, timers, windows, and sequence numbers in protected BPF maps.
* **User Transport Library (`LD_PRELOAD` or RPC API):** An unprivileged library in the application exposes a **Virtual AF_XDP Socket**. It groups NIC queues and converts application calls into operations on shared AF_XDP ring buffers.

#### **Practical Connection Lifecycle:**
1. **Setup and Handshake (Control Plane):** The application calls `socket()` or `connect()`. The `LD_PRELOAD` library intercepts the call and sends a request through **LRPC** to the root daemon. The daemon allocates the AF_XDP socket and UMEM, passes the file descriptor to the application through a Unix socket, manages the network SYN/ACK handshake, and installs the control information in the kernel's eBPF maps.
2. **Data Transfer (Direct Data Plane - Daemon Bypassed):** During `write()`, the application places data in the AF_XDP ring buffers. The `XDP_EGRESS` hook reads the data, applies headers and pacing through the BPF maps, and transmits the packets. During `read()`, the `XDP` hook validates incoming packets, updates BPF state, and places them in the AF_XDP receive ring, where the application reads them directly.
3. **In Case of an Application Crash:** The user library is isolated and cannot access the BPF state in the kernel. If the application crashes, the kernel's network state remains protected and intact.

### **4. Case Studies and Validation**

As discussed, eTran is not a single protocol but an extension framework that provides in-kernel primitives, including `XDP_EGRESS`, `XDP_GEN`, `PKT_QUEUE`, and BPF timers, for programming transport logic such as congestion control, pacing, and loss recovery.

To demonstrate the feasibility of the platform, the authors implemented two proof-of-concept transports that cover opposite datacenter transport paradigms:

1. **TCP with DCTCP:** Built on classic **POSIX-like stream APIs**, it implements a connection-oriented, sender-driven transport with rate-based pacing.
2. **Homa:** In addition to POSIX-like APIs, the authors developed **RPC message APIs** and implemented Homa as a connectionless, receiver-driven transport with credit- and priority-based scheduling using SRPT.

---

# **2. Selected Result**

The selected result is a cross-stack comparison between the transport implementations shipped with eTran and their Linux counterparts. We compare eTran-Homa with Linux-Homa, and eTran-DCTCP with Linux-DCTCP.

The eTran-Homa and Linux-Homa comparison uses the same Homa protocol with two different data paths. eTran runs Homa through AF_XDP, eBPF, and the eTran user-space library, while Linux-Homa uses the Homa kernel module. The eTran-DCTCP and Linux-DCTCP comparison follows the same idea for TCP with DCTCP: eTran uses its eBPF transport path, while Linux-DCTCP uses the standard Linux TCP stack with `tcp_dctcp` and ECN.

This comparison tests whether eTran can retain the protection of kernel networking while achieving the performance expected from a specialized transport implementation. Comparing the same protocol across the two stacks also limits the effect of protocol design when interpreting the results.

The evaluation uses the benchmark suites included with eTran and Linux-Homa. To make the workload descriptions self-contained, an RPC is a request followed by a response, while a single-stream workload uses one communication stream. Many-to-one means that several clients send to one server; one-to-many reverses that direction. P50 and P99 are the median and 99th-percentile values, and Kops/Mops denote thousands or millions of operations per second.

| Paper metric | What we measured                                                                                                                                                                                                                          | Why it matters                                                                                    |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| 1            | A single client sends a 32B request to one server and waits for the echoed response before sending the next request. The round-trip time (RTT) P50 and P99 are recorded.                                                                  | Measures the latency cost of the data path for a small request with no request-level concurrency. |
| 2            | A single client sends 1MB messages to one server back-to-back over a single stream. Sustained throughput is recorded.                                                                                                                     | Tests bulk data movement without contention from concurrent flows.                                |
| 3-4          | 500KB messages are sent concurrently either from 7 clients to 1 server (many-to-one) or from 1 client to 7 servers (one-to-many). Aggregate throughput is recorded.                                                                       | Tests scaling when several flows share a receiver or a sender.                                    |
| 5-6          | 32B RPCs are sent either from 7 clients to 1 server or from 1 client to 7 servers, with multiple requests outstanding. The aggregate RPC rate is recorded in Kops or Mops.                                                                | Measures small-message processing capacity and contention.                                        |
| 7-12         | Ten nodes act as both clients and servers in the W2-W5 all-to-all workloads. W2 and W3 emphasize short messages, while W4 and W5 emphasize large messages at higher offered loads. Overall and shortest-10% RTT P50 and P99 are recorded. | Tests incast, contention, and tail behavior under mixed message sizes.                            |
| 13-14        | A TCP client and server exchange 1KB or 2KB messages with 64 requests outstanding. Stream throughput is recorded.                                                                                                                         | Measures eTran-DCTCP and Linux-DCTCP on a sustained stream workload.                              |
| 15           | Five clients maintain 200 persistent TCP connections each, for 1,000 connections in total. Each connection sends closed-loop 64B requests with one request outstanding. Aggregate request rate is recorded.                               | Tests connection management and small-request processing at high concurrency.                     |
| 18           | Five clients run a key-value workload over 100,000 keys, with 32B keys, 64B values, a 90% GET and 10% SET mix, Zipf skew 0.9, and multiple connections and outstanding requests. Throughput is recorded.                                  | Tests the transports in an application-style workload.                                            |
| 19-20        | A single client runs the same key-value workload with one thread, one connection, and one request outstanding. Request-latency P50 and P99 are recorded.                                                                                  | Measures application responsiveness without saturation from competing requests.                   |
| 21-22        | CPU cycles per request are measured for the TCP and Homa benchmark processes using the corresponding CPU-cycle workloads.                                                                                                                 | Estimates the processing cost of each transport path.                                             |

The comparison answers two related questions. For Homa, it isolates the effect of the eTran data path by comparing eTran-Homa with the same protocol implemented in the Linux kernel. For DCTCP, it tests whether eTran's AF_XDP and eBPF path changes the behavior of a conventional TCP transport relative to Linux-DCTCP. The metric suite combines latency, throughput, scalability, tail latency, application workloads, and CPU cost so that the comparison does not depend on a single performance measure.

# **3. Environment Setup**

The reproduction was conducted on the same physical CloudLab cluster used for the original experiments. The evaluation therefore used the same `xl170` node type, rack, Mellanox 2410 switch fabric, and official paper artifact as the authors. The hardware, software, and runtime configuration are described below.

### **Hardware Environment**

The cluster was provisioned at the CloudLab Utah site and contained ten physical nodes connected through the same rack switch:

* **Cluster:** Ten `xl170` nodes in one rack on the CloudLab Utah site.
* **CPU:** Single-socket Intel Xeon E5-2640 v4 at 2.40 GHz, with 10 physical cores and 20 logical CPUs per node.
* **Memory:** 64 GB ECC DDR4 RAM per node.
* **Storage:** A 16 GB CloudLab blockstore mounted at `/mydata` on each node.
* **Network Card:** Mellanox ConnectX-4 Lx 25 GbE NIC using the `mlx5` driver and the `ens1f1np1` interface.
* **Network Switch:** Mellanox 2410 25 GbE rack switch.

### **Software Environment**

The evaluation used the official repositories and the corresponding stack-specific software:

* **Operating System:** Ubuntu 22.04 LTS.
* **eTran kernel:** Custom `6.6.0-eTran+` kernel built from `eTran-linux`, including the eTran patches for `XDP_EGRESS`, `XDP_GEN`, `BPF_MAP_TYPE_PKT_QUEUE`, and AF_XDP out-of-order buffer completion.
* **eTran implementation:** `eTran`, including `micro_kernel`, `libetran.so`, the Homa application, and the TCP applications.
* **Linux-Homa kernel:** Linux-Homa was validated with the HomaModule kernel, built from Linux `v6.17.8` with the Homa module. This kernel is different from the custom `6.6.0-eTran+` kernel used by eTran.
* **Linux-DCTCP baseline:** The DCTCP setup reuses the eTran system setup and custom kernel, then builds the HomaModule `cp_node` utility and configures standard Linux TCP with DCTCP and ECN.
* **Linux-Homa baseline:** `PlatformLab/HomaModule`, including its `cp_node` benchmark utility and Homa kernel module.
* **Repositories:**
  * `https://github.com/eTran-NSDI25/eTran`
  * `https://github.com/eTran-NSDI25/eTran-linux`
  * `https://github.com/PlatformLab/HomaModule`
* **Recorded artifact revisions:**
  * `eTran`: `f26ef186bde0f9b3b899712e44112de47b7d5a65`, `Update README.md`, 2025-04-28.
  * `eTran-linux`: `3e96097421b41d3d9f2935d3405e956076c9d823`, `fix bug`, 2024-10-30.
  * `HomaModule`: `9edb95896ba874dcb64064a51099ae4b38c84617`, HEAD of `main` on 2026-07-09, `Add more material to INSTALL.md`, 2026-07-01.
* **Compiler and libraries:** GCC/G++ 11.4.0, Clang/LLVM, `libbpf`, `libelf`, and the other dependencies installed by the Ansible setup playbooks.

### **Configuration Parameters**

The main system and network parameters were kept consistent across the benchmark stacks:

* **Switch configuration:** The Mellanox 2410 used its default ECN configuration, including a 70 KB marking threshold. Direct access to the Mellanox switch was confirmed to be unavailable through CloudLab, so its default configuration could not be changed.
* **MTU:** The MTU was kept at 1500 bytes because the switch does not support jumbo frames for this experiment.
* **NIC coalescing:** Adaptive RX and TX coalescing were disabled. RX coalescing was set to zero microseconds with one frame, and TX coalescing was set to 5 microseconds.
* **Flow control:** NIC RX and TX flow control were disabled.
* **Offloads:** GRO and TSO remained enabled. Disabling either offload was found to hurt performance on this hardware.
* **Kernel tuning:** SMT was enabled, kernel mitigations were disabled, CPU C-states were disabled, and PCIe ASPM was disabled. The `network-throughput` profile from `tuned` was enabled.
* **eTran queues and CPU placement:** The eTran `micro_kernel` used its default 20 NIC queues. Its control loop was internally pinned to CPU 19 through `CP_CPU`; no external `taskset` was used for the micro-kernel or application threads. For eTran TCP, `ETRAN_NR_APP_THREADS` was set to the application thread count and `ETRAN_NR_NIC_QUEUES` was set to the same value.
* **DCTCP parameters:** The Linux-DCTCP baseline used `tcp_dctcp` as the congestion-control algorithm, enabled ECN with `net.ipv4.tcp_ecn=1`, and enabled TCP timestamps.
* **Linux-Homa parameters:** The Homa evaluation installed the `homa` qdisc on `ens1f1np1`, set `net.homa.max_gso_size=100000` and `net.homa.hijack_tcp=0`, and set the CPU governor to `performance`.
* **Network preparation:** Static ARP entries and `/etc/hosts` entries were installed for all nodes. The benchmark interface was `ens1f1np1`, with addresses in the `192.168.6.0/24` network.
* **Runtime parameters:** The workload-specific parameters included message size, `--client-max`, `--ports`, `--server-ports`, `--server-nodes`, `--one-way`, `--gbps`, `--both`, and `--id`, as specified by the metric runbooks.

No external dataset was used. The workloads were generated by the benchmark programs, including the W2-W5 Homa workloads and the `flexkvs` key-value workload.

### **Deviations from the Original Setup**

No hardware setup deviation was introduced: the same physical cluster was used. The Linux-Homa validation uses the HomaModule Linux `v6.17.8` kernel, while eTran uses the custom `6.6.0-eTran+` kernel. This difference is required by the two stack implementations being compared, rather than being an experimental substitution. The official eTran and HomaModule sources were used, and the benchmark parameters were taken from the metric definitions and runbooks rather than replaced with a separate workload or dataset.

# 4. Experiment Result

> Explain how your experiment was conducted and then what results you acquired. 
Afterwards, compare your results with those of the paper and state your
takeaways.

Step-by-step description:

1. Execution procedure
1. Measurement method
1. Number of runs
1. Statistical treatment (mean, median, CI, etc.)

Also Describe:

- How did you ensure correctness (did you check also other metrics to make sure the experiment is running correctly?)
- Did you do any debugging? Discuss issues you faced and how you overcame them (if applicable consider allocating a subsection for this item) 

Share your result and compare them with the paper's. Then discuss your takeaways.

For comparison include:

- Graph(s) or table(s)
- Matching axes and units with the source paper
- Error bars if applicable
- You may want to report difference with the original results (e.g., absolute
number or percentage).

For example:

![The figure shows that method A improves throughput compared to method B](figures/one_bar.png){width=30%}

![Our reproduction of Figure 1 shows results with the similar trend as claimed by the paper](figures/two_bar.png){width=30%}

> **Reminder:** the goal is not achieve the exact results of the paper, but to do a rigorous experiment with similar assumptions from the source paper and gain insight. The insight can be correctness of work, failure to reproduce same results, or even infeasibility of doing such experiment for interesting reasons.

# 5. Further Exploration

In this project you are required to also explore a research question of your own. Either:

1. Take the same test with different input workload or a variation of a test that is not present in the paper and comment the results you obtain
1. Implement a new feature on top of the system you evaluated and show a figure showing the performance

Discuss which approach you take, and what you explored. Explain what was your
motivation and importance of your question.

## 5.1. Methodology and Result

Report the experiment you designed for answering the question and share the
result you got.

Include:

- Graph(s) or table(s)
- How the experiment was conducted (share the details)
- What did you discover?

# 6. Reproducibility Assessment of the Paper

Evaluate the paper itself:

- Was the methodology clearly described?
- Was the artifact usable?
- How difficult was reproduction?

# 7. Conclusion

Conclude the report by mentioning the takeaways of experiments you did


---

# Appendix

You are asked to write this report using Markdown. You can find a cheat sheet
of Markdown syntax at this [link](https://rust-lang.github.io/mdBook/format/markdown.html).

For generating a PDF file from your report you can use a tool of your choice.
*md2pdf* is one such tool. See this [link](https://pypi.org/project/md2pdf/)
for more information about it. You can also use an online editor such as [this](https://www.md2pdf.io/).

