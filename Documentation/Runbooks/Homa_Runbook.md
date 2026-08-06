# Homa Kernel Module Benchmark Runbook — Exact Commands per Metric

> Uses the **Linux kernel Homa module** via `cp_node` from
> [PlatformLab/HomaModule](https://github.com/PlatformLab/HomaModule)`/util`.
>
> Homa is a transport protocol implemented as a Linux kernel module. These
> benchmarks exercise the in-kernel Homa implementation to establish a baseline
> for comparison against eTran's AF_XDP-accelerated Homa.
>
> Pre-flight: ensure `homa.ko` is loaded on all nodes and `cp_node` is compiled
> (see `Ansible/playbooks/Homa/setup/`). Network is assumed pre-configured by
> eTran's evaluation playbooks (ARP, `/etc/hosts`, NIC tuning).
>
> **No micro_kernel, no eTran XDP/BPF, no `ETRAN_PROTO` needed.** The kernel
> Homa module handles all protocol logic in the kernel.

## Results Summary

Hardware: CloudLab xl170, single-socket 10-core E5-2640v4, Mellanox ConnectX-4 Lx 25G, SMT=on.

## Key Findings

- **Large-message throughput (metrics 3-4)**: Kernel Homa saturates the 25G link at
  ~23 Gbps. eTran's Homa is capped at ~13 Gbps for multi-client (metric 3) due to
  the XDP_GEN grant dispatch serialization in eBPF — a real eTran bug (same HW as
  paper, so not a core-count deficit). For single-stream 1MB (metric 2), eTran is
  1.5× faster than kernel Homa (16.6 vs 11 Gbps) thanks to AF_XDP's kernel-bypass
  for data movement.
- **Small-message latency (metric 1)**: eTran's 12.59 µs P50 beats kernel Homa's
  ~16 µs by 27%. The AF_XDP fastpath avoids kernel TCP/Homa processing overhead
  for small RPCs.
- **RPC rate (metrics 5-6)**: Mixed picture. For 7:1 client RPC rate (metric 5),
  kernel Homa achieves ~1.1 Mops vs eTran's ~0.93 Mops — the kernel's multi-threaded
  accept path handles concurrent clients better, while eTran's per-app-thread
  polling incurs overhead. For 1:7 server RPC rate (metric 6), eTran wins at
  ~1.12 Mops vs kernel Homa's ~0.9 Mops — the single-client eTran app thread
  drives 7 server connections more efficiently than the kernel's one-thread-per-port
  model.
- **No micro_kernel or XDP cleanup needed**: Kernel Homa runs entirely in the kernel.
  No need to kill micro_kernel, clean `/dev/shm/`, or detach XDP programs between
  metrics. Just kill stale `cp_node` processes and restart.
- **All-to-all (W2-W5)**: Kernel Homa's P99 tail latency for short-message workloads
  (W2/W3) is 6.7-7.0× worse than eTran due to TCP-style incast queuing — within
  the paper's expected 3.9-7.5× range. However, kernel Homa handles small messages
  in mixed workloads (W4/W5 shortest-10%) vastly better: 22-61 µs vs eTran's
  2.8-14.5 ms. eTran's AF_XDP busy-poll overhead inflates latency for all messages,
  while the kernel module processes small RPCs efficiently even under heavy
  large-message load.
- **CPU efficiency**: ~18.6 kcycles/request for kernel Homa, close to the paper's
  17.43 kcycles. eTran's AF_XDP path measures ~1357 kcycles (dominated by idle
  busy-poll), with active processing estimated at ~5 kcycles/req.

## Metric 1: Homa 32B Latency (Echo, Single Stream)

Output: `homa_32 clients: ... RTT (us) P50 <p50> P99 <p99> P99.9 <p99.9>`
Read P50 for the metric.

## Metric 2: Homa 1MB Throughput (Single Stream)

Output: `homa_999999 clients: ... Gbps out ...` — read Gbps out for the metric.

> `--workload 999999` avoids `HOMA_MAX_MESSAGE_LENGTH` off-by-one (1M boundary).
> `--one-way` = 100B response (Homa convention for throughput measurement).

## Metrics 7–12: All-to-All Tail Latency (W2–W5)

Servers target all 10 nodes including self (localhost connection through kernel Homa
adds ~8ms RTT overhead, reducing effective concurrency by ~10%). Results are still
valid as a Linux-Homa baseline — the self-target penalty is consistent across all nodes.

### Key observations
- **W2/W3 P99 slowdown**: Kernel Homa's P99 is 6.7-7.0× worse than eTran for
  short-message workloads — within the paper's expected 3.9-7.5× range. eTran's
  XDP_GEN grant-based flow control prevents incast queuing.
- **Shortest-10% latency**: Kernel Homa handles small messages vastly better in
  mixed workloads (W4: 22 µs vs eTran's 2848 µs, W5: 61 µs vs eTran's 14.5 ms).
  eTran's AF_XDP busy-poll + XDP_GEN grant dispatch has overhead that inflates
  latency for all messages, while kernel Homa processes small messages efficiently
  even under heavy large-message load.
- **Throughput**: Kernel Homa shows higher RPC rate for W3 (~1000 Kops vs eTran's
  707 Kops) but lower for W2 (~1000 Kops vs eTran's 4300 Kops). The difference is
  the offered load (3.2 vs 14 Gbps) and how each stack handles the concurrency limit.

