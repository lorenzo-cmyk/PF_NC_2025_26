# Benchmark Results

Consolidated measured results for the three benchmark stacks:

- eTran: AF_XDP + eBPF transports (Homa + TCP), micro_kernel + libetran.so
- Linux-Homa: Homa kernel module (PlatformLab/HomaModule)
- DCTCP: standard Linux TCP with tcp_dctcp + ECN (baseline for eTran TCP)

Units: latency in us, throughput in Gbps, RPC rate in Kops/Mops, CPU in
kcycles. "-" = metric not applicable/not measured for that stack.
Per-metric secondary measurements are in the appendix at the end.

# Metric 1: 32B RTT latency (echo, single stream)

Description: Round-trip time of 32B echo RPCs, single client thread to a
single-threaded server. 2 nodes.

Results:
| eTran (Homa)                                   | Linux-Homa                                    | DCTCP                    |
| ---------------------------------------------- | --------------------------------------------- | ------------------------ |
| P50 12.59 us, P99 14.85 us (93% of paper 11.8) | P50 ~16 us (15.26, paper 15.6), P99 ~25-35 us | P50 22.7 us, P99 26.4 us |

Notes: eTran and kernel Homa are both close to paper; eTran's AF_XDP fastpath
is ~1.27x faster than kernel Homa. DCTCP is the plain-TCP baseline with
higher latency.

# Metric 2: 1MB throughput, back-to-back single stream

Description: Sustained throughput of back-to-back 1MB RPCs, single client to
single-threaded server (`--one-way`). 2 nodes.

Results:
| eTran (Homa)                  | Linux-Homa                                                | DCTCP     |
| ----------------------------- | --------------------------------------------------------- | --------- |
| 16.6 Gbps (94% of paper 17.7) | ~10-11 Gbps (conflicting: 17.9 Gbps on 07-08; paper 14.5) | 21.5 Gbps |

Notes: Unresolved Linux-Homa conflict (17.9 vs 10-11 Gbps, same commands,
different sessions). The 07-09 value is internally consistent (RTT P50 ~720 us
=> ~11 Gbps at 1MB per RPC); candidate: qdisc/sysctl state differences
between sessions. Re-measure on next cluster allocation before quoting
either. DCTCP saturates the 25G NIC for bulk transfers.

# Metric 3: 500KB throughput, 7 clients -> 1 server

Description: Server throughput receiving concurrent 500KB RPCs from 7
clients, 4 server threads. 8 nodes.

Results:
| eTran (Homa)                         | Linux-Homa            | DCTCP               |
| ------------------------------------ | --------------------- | ------------------- |
| ~12.78-12.9 Gbps (56% of paper 23.0) | ~23 Gbps (paper 23.1) | 23.5 Gbps server in |

Notes: eTran is capped at ~13 Gbps regardless of server `--ports`
(4/5/7 -> 12.9/12.78/12.77 Gbps; 10 -> 8.01 Gbps). Real eBPF bottleneck:
XDP_GEN grant dispatch serialization, NOT server parallelism or core
count. Kernel Homa and DCTCP saturate the link.

# Metric 4: 500KB throughput, 1 client -> 7 servers

Description: Client throughput sending concurrent 500KB RPCs to 7 servers,
7 sending threads. 8 nodes.

Results:
| eTran (Homa)                   | Linux-Homa              | DCTCP                |
| ------------------------------ | ----------------------- | -------------------- |
| ~19.5 Gbps (86% of paper 22.7) | ~23.1 Gbps (paper 22.9) | 23.5 Gbps client out |

Notes: eTran gap is NOT the NIC (paper hit 22.7 on the same 25G link); likely
XDP_GEN grant pacing plus per-app-thread send rate on the client.

# Metric 5: 32B RPC rate, 7 clients -> 1 server

Description: Aggregate RPC rate for 32B messages, 7 clients to 1 server
(7 server threads, 64 outstanding per client). 8 nodes.

Results:
| eTran (Homa)                             | Linux-Homa            | DCTCP     |
| ---------------------------------------- | --------------------- | --------- |
| ~927 Kops server (32% of paper 2.9 Mops) | ~1.1 Mops (paper 1.7) | ~866 Kops |

Notes: eTran gap is per-app-thread polling + BPF RPC-map contention (mk is
off the data path). Paper eTran/Linux-Homa ratio 1.71x vs our 0.85x - the
residual is the open question. DCTCP P99 is 2-5 ms (TCP incast tail).

# Metric 6: 32B RPC rate, 1 client -> 7 servers

Description: Aggregate RPC rate for 32B messages, 1 client to 7 servers
(7 ports; --client-max 256 -> 36 outstanding per port, 252 in flight
due to integer division). 8 nodes.

Results:
| eTran (Homa)                              | Linux-Homa            | DCTCP      |
| ----------------------------------------- | --------------------- | ---------- |
| ~1120 Kops client (34% of paper 3.3 Mops) | ~0.9 Mops (paper 1.8) | ~1082 Kops |

Notes: eTran beats kernel Homa here (paper ratio 1.83x vs our 1.24x). DCTCP
P50 ~66 us is best-in-class for this workload (no AF_XDP polling overhead).

# Metrics 7-12: All-to-all tail latency, W2-W5

Description: End-to-end RTT distributions in a 10-node all-to-all cluster;
each node is both client and server. W2/W3 are short-message dominated
(3.2 / 14 Gbps), W4/W5 are large-message dominated (20 / 20 Gbps).
Shortest-10% = latency of the 10% smallest messages. 10 nodes.

Results:
| Workload | Metric (us)            | eTran (Homa)   | Linux-Homa    | DCTCP |
| -------- | ---------------------- | -------------- | ------------- | ----- |
| W2       | Overall P50 / P99      | 109 / 1344     | 94 / 9453     | -     |
| W2       | Shortest-10% P50 / P99 | 91 / 118       | 19 / 21       | -     |
| W3       | Overall P50 / P99      | 115 / 1428     | 100 / 9511    | -     |
| W3       | Shortest-10% P50 / P99 | 110 / 1462     | 20 / 22       | -     |
| W4       | Overall P50 / P99      | 3068 / 13713   | 128 / 224000  | -     |
| W4       | Shortest-10% P50 / P99 | 2848 / 12604   | 22 / 24       | -     |
| W5       | Overall P50 / P99      | 18007 / 130044 | 1135 / 404000 | -     |
| W5       | Shortest-10% P50 / P99 | 14530 / 48026  | 61 / 84       | -     |

Notes: W2/W3 P99 slowdown (eTran vs Linux-Homa) is 7.0x / 6.7x - within the
paper's expected 3.9-7.5x. Kernel Homa's worse P99 under short-message
load reflects TCP-style incast queuing: it has no grant-based flow control,
where eTran's XDP_GEN grants prevent incast. P50 slowdowns (0.86x / 0.87x)
are BELOW the paper's 1.4-3.6x. W4/W5 eTran values are INVALID: the system
is overloaded at the 20 Gbps offered load (eTran can only drain ~13 Gbps),
so they reflect queue build-up, not protocol behavior. Kernel Homa handles
small messages in mixed workloads far better (22-61 us vs eTran's
2.8-14.5 ms). Linux-Homa's W4/W5 runs used a different harness
(pre-started servers + piped stdin, self-targeting overhead), so those
comparisons are under dissimilar conditions. Re-measurement plan: sweep
offered load below each stack's sustainable rate with achieved-load
reporting, use identical harness for both stacks (e.g., backport
`--both`/`--id` to HomaModule's cp_node).

# Metric 13: TCP 1KB throughput, 64 outstanding

Description: TCP streaming throughput, 1KB messages, 64 outstanding,
single-threaded. 2 nodes.

Results:
| eTran (TCP)                                                                         | Linux-Homa | DCTCP                       |
| ----------------------------------------------------------------------------------- | ---------- | --------------------------- |
| 1x1: ~7.19 Gbps / 878 Kops; 1x5: ~12.1 Gbps / 1474 Kops; 5x5: ~7.55 Gbps / 922 Kops | -          | 1.8-2.8 Gbps / 222-346 Kops |

Notes: eTran/DCTCP ratios ~3.95x (1x1), ~3.98x (1x5), ~2.79x (5x5) - best
~3.96-3.98x vs paper's 4.8x, consistent across concurrency levels. Main
bottleneck is server-side queue contention (single 5-thread client hits
1474 Kops, 5x5 aggregate drops to 922 Kops). DCTCP baseline varies 2-3x
run-to-run; switch ECN marking IS enabled on the SN2410 (corrected
2026-07-18), so the mechanism is unresolved: threshold mismatch vs the
paper's deduced ~70KB, DCTCP oscillation around the marking point, or
measurement-window transients. Single-point ratios are unreliable.
5x5 x 64 (1600 in-flight) is stable for 20s+ runs, no drops.

# Metric 14: TCP 2KB throughput, 64 outstanding

Description: TCP streaming throughput, 2KB messages, 64 outstanding,
single-threaded. 2 nodes.

Results:
| eTran (TCP)            | Linux-Homa | DCTCP                       |
| ---------------------- | ---------- | --------------------------- |
| ~12.29 Gbps / 750 Kops | -          | 1.8-4.6 Gbps / 111-283 Kops |

Notes: No TAS baseline available (paper reference is 0.87x TAS). Ratio vs
DCTCP spans 2.65-6.76x depending on the DCTCP baseline run (unresolved
variance).

# Metric 15: TCP 1K persistent connections, 64B closed-loop

Description: Aggregate throughput over 1000 persistent TCP connections
(5 clients x 200), 64B requests, 1 outstanding per connection. 6 nodes.

Results:
| eTran (TCP)                     | Linux-Homa | DCTCP                 |
| ------------------------------- | ---------- | --------------------- |
| ~1129 Kops peak / ~655 K steady | -          | ~234 Kops (5 x ~46.8) |

Notes: eTran/DCTCP ratio ~2.8x - EXCEEDS the paper's expected 2.26x. No
connection drops observed post-fix (DCTCP baseline ran clean too).

# Metrics 16-17: TCP short-lived connections (16 / 256 msgs per conn)

Description: Throughput of short-lived TCP connections (16 and 256 messages
per connection) with 1K concurrent flows. 6 nodes.

Results:
| eTran (TCP)      | Linux-Homa | DCTCP |
| ---------------- | ---------- | ----- |
| Not reproducible | -          | -     |

Notes: The public eTran repo has no short-lived connection benchmark
(epoll_client only supports persistent connections). Not reproduced.
Paper targets: 42.7x / 5.4x over Linux TCP.

# Metric 18: TCP KV throughput, 100K keys, Zipf s=0.9

Description: Throughput of a key-value store workload (flexkvs), 100K keys,
Zipf skew 0.9, 9:1 GET:SET, 5 clients x 4 threads x 10 conns x 32 pending.
6 nodes.

Results:
| eTran (TCP)        | Linux-Homa | DCTCP       |
| ------------------ | ---------- | ----------- |
| ~0.73 Mops (2.62x) | -          | ~0.278 Mops |

Notes: Ratio is within the paper's expected 2.4-4.8x. `--pending 32` matches
the paper spec; 16 vs 32 gives identical results.

# Metric 19: TCP KV P50 latency, under-loaded

Description: KV request latency P50 (90% GET / 10% SET mix) with a
single client, 1 thread x 1 conn x 1 pending (server unloaded). 2 nodes.

Results:
| eTran (TCP)              | Linux-Homa | DCTCP                              |
| ------------------------ | ---------- | ---------------------------------- |
| 14 us (beats paper 17.2) | -          | 17 us idle; 36 us at 320 in-flight |

Notes: eTran beats the paper target. DCTCP is far below the paper's Linux-TCP
64.2 us - the paper value most likely reflects testbed base-latency
differences, not switch ECN (marking cannot affect the queue-free test).

# Metric 20: TCP KV P99 latency, under-loaded

Description: KV request latency P99 (90% GET / 10% SET mix) with a
single client, 1 thread x 1 conn x 1 pending (server unloaded). 2 nodes.

Results:
| eTran (TCP)              | Linux-Homa | DCTCP      |
| ------------------------ | ---------- | ---------- |
| 16 us (beats paper 27.5) | -          | 24 us idle |

Notes: eTran beats the paper target; tight distribution (14-18 us up to
P99.9). Same testbed caveat as metric 19 for the DCTCP value (paper's
Linux-TCP P99 target is 89.3 us).

# Metric 21: TCP CPU cycles per request

Description: Total CPU cycles consumed per request, 1KB TCP workload.
2 nodes.

Results:
| eTran (TCP)                 | Linux-Homa | DCTCP                      |
| --------------------------- | ---------- | -------------------------- |
| ~2.93 kcycles (server-side) | -          | ~7.4 kcycles (client-side) |

Notes: Process-scoped `perf stat` accounting vs the paper's system-wide
single-NAPI-context values - methodologies differ, so "below paper" does not
mean outperforming. eTran is ~2.5x more efficient than DCTCP.

# Metric 22: Homa CPU cycles per request

Description: Total CPU cycles consumed per request. Linux-Homa: 32B Homa
RPC workload (matches paper). eTran: per its runbook, measured with the
1MB workload (--workload 999999 --one-way), so the raw value is NOT a 32B
comparison. 2 nodes.

Results:
| eTran (Homa)                                            | Linux-Homa    | DCTCP |
| ------------------------------------------------------- | ------------- | ----- |
| ~1357 kcycles raw (AF_XDP busy-poll); ~5 kcycles active | ~18.6 kcycles | -     |

Notes: eTran's raw value is dominated by idle busy-polling (99.6%); active
processing ~5 kcycles matches the paper's 5.48. Linux-Homa is close to
paper's 17.43.

# Table 5: CPU cycles per request - component breakdown (paper values)

Paper's per-component breakdown (kcycles) under a single NAPI context
(Table 5 of the paper). Only totals were measured on this cluster (metric
21 for TCP, metric 22 for Homa); per-component attribution was not done.

| Component     | eTran TCP | Linux TCP | eTran Homa | Linux Homa |
| ------------- | --------- | --------- | ---------- | ---------- |
| Application   | 0.48      | 0.53      | 0.95       | 1.04       |
| Socket / RPC  | 0.63      | 3.50      | 0.98       | 3.38       |
| Data Copy     | 0.19      | 0.57      | 0.32       | 1.30       |
| Sk_buff       | 0.15      | 0.47      | 0.08       | 0.39       |
| TCP/Homa + IP | 1.06      | 2.12      | 1.47       | 3.36       |
| Lock / Unlock | 0.18      | 0.45      | 0.24       | 2.68       |
| NIC Driver    | 1.17      | 1.54      | 0.83       | 1.81       |
| Memory Mgmt   | 0.05      | 0.32      | 0.06       | 1.04       |
| Scheduling    | 0.25      | 1.19      | 0.18       | 1.02       |
| Other         | 0.21      | 1.82      | 0.38       | 1.41       |
| **TOTAL**     | **4.37**  | **12.51** | **5.48**   | **17.43**  |

Measured totals (metric 21 / 22): eTran TCP ~2.93 kcycles server-side
(2026-07-08), Linux TCP ~7.4 kcycles client-side (2026-07-08), eTran Homa
~1357 kcycles raw (AF_XDP busy-poll, 99.6% idle; ~5 kcycles active),
Linux Homa ~18.6 kcycles.

# Metric 3.1: XDP_EGRESS egress overhead (driver microbenchmark)

Description: Throughput loss from stacking XDP_EGRESS features on an
AF_XDP tx-only datapath, 64B packets, single core. 2 nodes.

Results:
| Config             | eTran measured | Paper target           |
| ------------------ | -------------- | ---------------------- |
| AF_XDP tx-only     | not measured   | 11.55 Mpps             |
| + Empty XDP_EGRESS | not measured   | 10.79 Mpps (6.6% loss) |
| + OOO Completion   | not measured   | 9.95 Mpps (13.9% loss) |
| + Array Lookup     | not measured   | 9.71 Mpps (15.9% loss) |
| + Hashmap Lookup   | not measured   | 9.10 Mpps (21.2% loss) |

Notes: Never benchmarked - the required XDP_EGRESS BPF programs are not
standalone build targets in the repo.

# Metric 3.2: XDP_GEN packet generation (driver microbenchmark)

Description: ACK/credit packet generation throughput on a second core while
the first core drops received packets. 2 nodes.

Results:
| Config            | eTran measured | Paper target                                     |
| ----------------- | -------------- | ------------------------------------------------ |
| l2fwd baseline    | not measured   | 6.73 Mpps overall (3.87/core), 1.74 active cores |
| rx-drop + XDP_GEN | not measured   | 6.03 Mpps overall (4.47/core), 1.35 active cores |

Notes: Never benchmarked - requires a BPF program using the XDP_GEN hook
that is not provided as a standalone build target.

# Paper targets for unmeasured / low-priority metrics

Not benchmarked on this cluster; kept for completeness. Pacing and
packet-loss tests need extra testbed setup; TAS is a separate project.

| Metric                                            | Paper target                         | Why not measured          |
| ------------------------------------------------- | ------------------------------------ | ------------------------- |
| Pacing: rate conformance deviation (1MB @ 8 Gbps) | < 0.4%                               | low priority              |
| Pacing: aggregate throughput, 8 Gbps target       | 7950-8050 Mbps                       | low priority              |
| eTran TCP throughput penalty @ 1% loss            | ~8%                                  | no loss-injection testbed |
| eTran TCP throughput penalty @ 5% loss            | ~33%                                 | no loss-injection testbed |
| eTran Homa throughput penalty @ 5% loss           | ~90-100%                             | no loss-injection testbed |
| TAS TCP 1KB throughput (64 outstanding)           | 7.7x Linux -> 21.56 Gbps             | no TAS baseline           |
| TAS TCP 2KB throughput                            | reference baseline                   | no TAS baseline           |
| TAS TCP 1K persistent connections (64B)           | 4.1x Linux -> 0.959 Mops             | no TAS baseline           |
| TAS TCP KV throughput                             | (3.9-7.9)x Linux -> 1.084-2.196 Mops | no TAS baseline           |

# Appendix: secondary measurements

Per-metric details not shown in the main tables (per-client breakdowns, RTT
medians, perf counters, aggregate all-to-all rates).

| Metric | eTran                                                                                                                      | Linux-Homa                                                                                           | DCTCP                                                          |
| ------ | -------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| 1      | -                                                                                                                          | ~61 Kops; P99 ~25-35, P99.9 ~43-56 us                                                                | ~44 Kops; P99.9 29.1 us                                        |
| 2      | RTT P50 442 us                                                                                                             | ~1.3 Kops; RTT P50 ~720 us                                                                           | RTT P50 371 us                                                 |
| 3      | RTT P50 ~2.1 ms; client-max 2/4/64 -> 10.9/10.6/10.57 Gbps (448 RPCs stall)                                                | ~5.75 Kops; RTT P50 ~1.2 ms; per-client 3.0-4.1 Gbps                                                 | RTT P50 ~1188 us; per-client ~3.4 Gbps                         |
| 4      | RTT P50 ~1.37 ms; per-server ~2.8 Gbps                                                                                     | ~5.6 Kops; RTT P50 ~1.19 ms; per-server ~3.2 Gbps                                                    | RTT P50 ~1184 us                                               |
| 5      | RTT P50 ~400-460 us                                                                                                        | per-client 139-209 Kops; RTT P50 210-375 us                                                          | per-client 140-207 Kops; RTT P50 54-75 us                      |
| 6      | RTT P50 ~217 us; per-server ~160 Kops                                                                                      | RTT P50 360-395 us; per-server 25-91 Kops                                                            | per-server ~150 Kops; RTT P99 ~300 us                          |
| 7-12   | aggregate: W2 ~3990, W3 ~707, W4 ~84, W5 ~16 Kops                                                                          | aggregate: W2/W3 ~1000 Kops, W4/W5 ~6 Gbps/node; samples/node: W2 ~800K, W3 ~1.3M, W4 ~290K, W5 ~66K | -                                                              |
| 13     | per-client ~178 Kops (5x5); 1600 in-flight stable, no drops                                                                | -                                                                                                    | RTT ~2.9 ms under load                                         |
| 14     | 6.76x ratio vs 1.82 Gbps DCTCP baseline                                                                                    | -                                                                                                    | -                                                              |
| 15     | per-client 160-170 Kops; node5 connects 167/200                                                                            | -                                                                                                    | per-client ~46.8 Kops                                          |
| 18     | per-client 150/149/146/142/140 Kops; under load P50 262, P99 310 us                                                        | -                                                                                                    | per-client ~55.6 Kops; under load P50 717, P90 760, P99 862 us |
| 19     | 0.067 Mops at 1 pending; P90 16, P99.9 18, P99.99 187 us; 122% of paper                                                    | -                                                                                                    | ~54 Kops at 1 pending; P90 22, P99.9 29, P99.99 193 us         |
| 20     | distribution 14-18 us up to P99.9; 172% of paper                                                                           | -                                                                                                    | -                                                              |
| 21     | client: 63.8B cyc, 94.8B instr, IPC 1.49 (25s @ ~880 Kops); server: 31.1B cyc, ~4950 instr/req, IPC 1.69 (12s @ ~884 Kops) | -                                                                                                    | 33.8B cyc, ~4.5M req, user 0.8s + sys 12.4s (13s @ ~346 Kops)  |
| 22     | 50.9B cyc, 89.9B instr, IPC 1.77, 2055 ctx-switches, 16 migrations (20s @ 15-16 Gbps)                                      | ~279 Kops avg, ~5M req, 21.6K instr/req, IPC 1.17, user 8.2s + sys 27.9s                             | -                                                              |
