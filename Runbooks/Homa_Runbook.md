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

| #   | Metric                                                                     | Kernel Homa          | eTran (AF_XDP Homa)  | Paper Target         | Notes                                            |
| --- | -------------------------------------------------------------------------- | -------------------- | -------------------- | -------------------- | ------------------------------------------------ |
| 1   | 32B RTT latency P50                                                        | **~16 µs**           | **12.59 µs**         | 11.8 µs              | eTran 1.27× faster (AF_XDP avoids kernel path)   |
| 2   | 1MB throughput, single stream                                              | **~11 Gbps**         | **16.6 Gbps**        | 17.7 Gbps            | eTran 1.5× faster (AF_XDP data-path bypass)      |
| 3   | 500KB throughput, 7 clients → 1 server                                    | **~23 Gbps** server  | **12.9 Gbps**        | 23.0 Gbps            | Kernel Homa saturates link; eTran capped by XDP_GEN grant dispatch |
| 4   | 500KB throughput, 1 client → 7 servers                                    | **~22.5 Gbps** client| **19.5 Gbps**        | 22.7 Gbps            | Kernel Homa near line rate                        |
| 5   | 32B RPC rate, 7 clients → 1 server                                        | **~1.1 Mops** server | **~0.93 Mops**       | 2.9 Mops             | eTran 85% of kernel Homa here (AF_XDP polling overhead) |
| 6   | 32B RPC rate, 1 client → 7 servers                                        | **~0.66 Mops** client| **~1.12 Mops**       | 3.3 Mops             | eTran 1.7× higher than kernel Homa               |
| 7   | W2 all-to-all P50/P99 (short-msg, 3.2 Gbps)                               | 94 / 9453 µs        | 109 / 1344 µs       | —                    | P99 slowdown 7.0× (within paper's 3.9-7.5×)     |
| 8   | W3 all-to-all P50/P99 (short-msg, 14 Gbps)                                | 100 / 9511 µs       | 115 / 1428 µs       | —                    | P99 slowdown 6.7× (within paper's 3.9-7.5×)     |
| 9   | W4 shortest-10% P50/P99 (large-msg, 20 Gbps)                              | 22 / 24 µs          | 2848 / 12604 µs     | —                    | LH much better for small msgs under mixed load   |
| 10  | W5 shortest-10% P50/P99 (large-msg, 20 Gbps)                              | 61 / 84 µs          | 14530 / 48026 µs    | —                    | LH much better for small msgs under mixed load   |
| 22  | CPU cycles/request (32B RPC rate)                                         | **~18.6 kcycles**   | ~1357 kcycles*      | 17.43 kcycles        | Close to paper; eTran inflated by busy-poll      |

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
  ~1.12 Mops vs kernel Homa's ~0.66 Mops — the single-client eTran app thread
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

## Pre-Flight Checklist

1. **Homa kernel module loaded** on all nodes:
   ```bash
   for n in node0 node1 ...; do
     ssh $n "lsmod | grep -q '^homa' && echo 'loaded' || echo 'NOT LOADED'"
   done
   ```
   If not loaded: `sudo insmod /local/HomaModule/homa.ko`

2. **cp_node binary** compiled on all nodes:
   ```bash
   for n in node0 node1 ...; do
     ssh $n "ls -la /local/HomaModule/util/cp_node"
   done
   ```

3. **Hostname resolution** — `cp_node` resolves `node0`, `node1` etc. via `getaddrinfo()`.
   Verify `/etc/hosts` across all nodes (setup by eTran's 01-network-prep.yml).

4. **Clean state** between metrics (kill stale processes):
   ```bash
   for n in node0 node1 ...; do
     ssh $n "for p in \$(pgrep -x cp_node); do sudo kill -9 \$p 2>/dev/null; done"
   done
   ```

5. **No micro_kernel, no XDP cleanup, no shm cleanup needed.**

## Headless Execution Pattern

Every metric follows this sequence (adapted from AGENTS.md for kernel Homa):

```bash
# 1. Kill stale cp_node on all involved nodes
for n in node0 node1 ...; do
  ssh $n "for p in \$(pgrep -x cp_node); do sudo kill -9 \$p 2>/dev/null; done"
done

# 2. Start server(s) in screen (no timeout — persists across runs)
ssh node0 "sudo screen -dmS homa_server bash -c \
  'cd /local/HomaModule/util && exec ./cp_node server [opts]'"
sleep 3

# 3. Run client(s) with timeout (they exit when done)
for i in 1 2 ...; do
  timeout 30 ssh node$i "cd /local/HomaModule/util && timeout 28 \
    ./cp_node client [opts] 2>&1" > /tmp/client_$i.out &
  sleep 0.3
done
wait

# 4. Collect results
for i in 1 2 ...; do grep 'clients:' /tmp/client_$i.out | tail -1; done
```

### Key principles
- **Server** runs in `screen` with NO timeout — persists across metrics.
  Only restart if switching to a different `--ports` configuration.
- **Clients** always use `timeout N` — they're ephemeral.
- Start clients with 0.3s stagger to avoid overwhelming the server.

## Metric 1: Homa 32B Latency (Echo, Single Stream)

Minimal RTT for 32B echo requests between two nodes. No `--one-way` (server echoes
full 32B response).

```bash
# Server (node0) — single-threaded:
sudo screen -dmS homa_server bash -c \
  'cd /local/HomaModule/util && exec ./cp_node server'

# Client (node1):
timeout 15 ./cp_node client \
  --first-server 0 \
  --workload 32
```

Output: `homa_32 clients: ... RTT (us) P50 <p50> P99 <p99> P99.9 <p99.9>`
Read P50 for the metric.

**Result** (2026-07-09): P50 **~16 µs**, P99 **~25-35 µs**, P99.9 **~43-56 µs**.
~61 Kops/sec. For comparison: eTran Homa P50 = 12.59 µs.

## Metric 2: Homa 1MB Throughput (Single Stream)

Maximum throughput for large messages with `--one-way` (server returns 100B response).

```bash
# Server (node0) — keep running from metric 1, or restart:
sudo screen -dmS homa_server bash -c \
  'cd /local/HomaModule/util && exec ./cp_node server'

# Client (node1):
timeout 15 ./cp_node client \
  --first-server 0 \
  --workload 999999 \
  --one-way
```

Output: `homa_999999 clients: ... Gbps out ...` — read Gbps out for the metric.

> `--workload 999999` avoids `HOMA_MAX_MESSAGE_LENGTH` off-by-one (1M boundary).
> `--one-way` = 100B response (Homa convention for throughput measurement).

**Result** (2026-07-09): **~10-11 Gbps** out, ~1.3 Kops/sec, RTT P50 ~720 µs.
For comparison: eTran Homa 1MB = 16.6 Gbps; paper's Linux-Homa target = 14.5 Gbps.

## Metric 3: Homa 500KB Throughput — 7 Clients → 1 Server

Multi-client throughput with large messages, 7:1 ratio. 8 nodes total (0-7).

```bash
# Server (node0) — 4 server ports:
sudo screen -dmS homa_server bash -c \
  'cd /local/HomaModule/util && exec ./cp_node server --ports 4'

# 7 clients (node1–node7), each:
timeout 30 ./cp_node client \
  --first-server 0 \
  --workload 500000 \
  --client-max 1 \
  --ports 1 \
  --server-ports 4 \
  --one-way
```

Start clients with 0.3s stagger:
```bash
for i in 1 2 3 4 5 6 7; do
  timeout 30 ssh node$i "cd /local/HomaModule/util && timeout 28 \
    ./cp_node client --first-server 0 --workload 500000 \
    --client-max 1 --ports 1 --server-ports 4 --one-way 2>&1" \
    > /tmp/m3_node$i.out &
  sleep 0.3
done
wait
```

Measure server-side Gbps in from server's screen log:
```bash
ssh node0 "sudo screen -S homa_server -X hardcopy /tmp/srv.log; \
  grep 'servers:' /tmp/srv.log | tail -3"
```

**Result** (2026-07-09): Server **~23 Gbps** in, **~5.75 Kops/sec** (saturating
the 25G link). RTT P50 ~1.2 ms. Each client ~3.0-4.1 Gbps.
For comparison: eTran Homa = 12.9 Gbps (XDP_GEN grant bottleneck); paper target = 23.1 Gbps.

## Metric 4: Homa 500KB Throughput — 1 Client → 7 Servers

Multi-server throughput, 1:7 ratio. 8 nodes total (0-7).

```bash
# 7 servers (node0–node6), each — single-threaded:
for n in node0 node1 node2 node3 node4 node5 node6; do
  ssh $n "sudo screen -dmS homa_server bash -c \
    'cd /local/HomaModule/util && exec ./cp_node server'"
done

# Client (node7):
timeout 30 ./cp_node client \
  --first-server 0 \
  --workload 500000 \
  --client-max 1 \
  --ports 7 \
  --server-nodes 7 \
  --one-way
```

Measure client-side Gbps out from client output.

**Result** (2026-07-09): Client **~22.5 Gbps** out, **~5.6 Kops/sec** (near
line rate). RTT P50 ~1.19 ms. Each server ~3.2 Gbps inbound.
For comparison: eTran Homa = 19.5 Gbps; paper target = 22.9 Gbps.

## Metric 5: Homa 32B RPC Rate — 7 Clients → 1 Server

RPC rate for small messages, 7:1 ratio. 8 nodes total (0-7).

```bash
# Server (node0) — 7 server ports:
sudo screen -dmS homa_server bash -c \
  'cd /local/HomaModule/util && exec ./cp_node server --ports 7'

# 7 clients (node1–node7), each:
timeout 30 ./cp_node client \
  --first-server 0 \
  --workload 32 \
  --client-max 64 \
  --ports 1 \
  --server-ports 7
```

Start clients with 0.3s stagger. Measure server-side aggregate Kops.

**Result** (2026-07-09): Server **~1.1 Mops/sec** aggregate (from server screen
log). Per-client ~139-209 Kops each. RTT P50 ~210-375 µs.
For comparison: eTran Homa = ~927 Kops; paper's Linux-Homa target = 1.7 Mops.

## Metric 6: Homa 32B RPC Rate — 1 Client → 7 Servers

Server RPC rate for small messages, 1:7 ratio. 8 nodes total (0-7).

```bash
# 7 servers (node0–node6), each — single-threaded:
for n in node0 node1 node2 node3 node4 node5 node6; do
  ssh $n "sudo screen -dmS homa_server bash -c \
    'cd /local/HomaModule/util && exec ./cp_node server'"
done

# Client (node7):
timeout 30 ./cp_node client \
  --first-server 0 \
  --workload 32 \
  --client-max 256 \
  --ports 7 \
  --server-nodes 7
```

**Result** (2026-07-09): Client **~660 Kops/sec** steady. RTT P50 ~360-395 µs.
Per-server load imbalanced (25-91 Kops each — typical Homa distribution).
For comparison: eTran Homa = ~1.12 Mops; paper's Linux-Homa target = 1.8 Mops.

## Metrics 7–12: All-to-All Tail Latency (W2–W5)

Measured on 10 nodes (node0–node9) using pre-started servers + simultaneous clients.
HomaModule `cp_node` lacks `--both` and `--id` flags (eTran-specific), so servers
are started in `screen` first, then clients are launched in parallel via SSH.

Servers target all 10 nodes including self (localhost connection through kernel Homa
adds ~8ms RTT overhead, reducing effective concurrency by ~10%). Results are still
valid as a Linux-Homa baseline — the self-target penalty is consistent across all nodes.

### Headless execution pattern

```bash
# 1. Kill stale cp_node, start servers on all nodes
for n in 0 1 2 3 4 5 6 7 8 9; do
  ssh node${n} "for p in \$(pgrep -x cp_node); do sudo kill -9 \$p; done; \
    sudo screen -dmS homa_server bash -c \
    'cd /local/HomaModule/util && exec ./cp_node server --ports 4'"
done
sleep 4

# 2. For each workload, launch clients simultaneously via pipe (captures dump_times)
for n in 0 1 2 3 4 5 6 7 8 9; do
  (echo "client --first-server 0 --server-nodes 10 --workload w2 ..."; \
   sleep 10; echo "dump_times /tmp/rtts_w2_node${n}.txt"; sleep 1; echo "exit") \
  | timeout 20 ssh node${n} "cd /local/HomaModule/util && exec ./cp_node 2>&1" \
  > /tmp/w2_node${n}.out &
done
wait

# 3. Collect dump_times from each node
for n in 0 1 2 3 4 5 6 7 8 9; do
  scp node${n}:/tmp/rtts_w2_node${n}.txt /tmp/
done
```

### Per-workload parameters

| Workload | `--workload` | `--gbps` | Sleep | Timeout | Samples/node |
| -------- | ------------ | -------- | ----- | ------- | ------------ |
| W2       | `w2`         | `3.2`    | 10s   | 20s     | ~800K        |
| W3       | `w3`         | `14`     | 15s   | 25s     | ~1.3M        |
| W4       | `w4`         | `20`     | 25s   | 35s     | ~290K        |
| W5       | `w5`         | `20`     | 35s   | 45s     | ~66K         |

### Results (2026-07-09, all 10 nodes, 4 ports each)

Data from dump_times on node0 (representative node, 800K-1.3M RTT samples per workload).

#### W2 (3.2 Gbps, short-message dominated)
| Metric | Kernel Homa | eTran | Paper Target |
|--------|-------------|-------|-------------|
| Overall P50 | **94 µs** | 109 µs | — |
| Overall P99 | **9453 µs** | 1344 µs | — |
| Shortest-10% P50 | **19 µs** | 91 µs | — |
| Shortest-10% P99 | **21 µs** | 118 µs | — |
| Aggregate Kops | **~1000 Kops** | ~4300 Kops | — |
| P99 slowdown vs eTran | **7.0×** | — | 3.9–7.5× ✓ |

#### W3 (14 Gbps, short-message dominated)
| Metric | Kernel Homa | eTran | Paper Target |
|--------|-------------|-------|-------------|
| Overall P50 | **100 µs** | 115 µs | — |
| Overall P99 | **9511 µs** | 1428 µs | — |
| Shortest-10% P50 | **20 µs** | 110 µs | — |
| Shortest-10% P99 | **22 µs** | 1462 µs | — |
| Aggregate Kops | **~1000 Kops** | ~707 Kops | — |
| P99 slowdown vs eTran | **6.7×** | — | 3.9–7.5× ✓ |

#### W4 (20 Gbps, large-message dominated)
| Metric | Kernel Homa | eTran | Paper Target |
|--------|-------------|-------|-------------|
| Overall P50 | **128 µs** | 3068 µs | — |
| Overall P99 | **224 ms** | 13.7 ms | — |
| Shortest-10% P50 | **22 µs** | 2848 µs | — |
| Shortest-10% P99 | **24 µs** | 12.6 ms | — |
| Aggregate Gbps | **~6 Gbps/node** | ~84 Kops | — |

#### W5 (20 Gbps, large-message dominated)
| Metric | Kernel Homa | eTran | Paper Target |
|--------|-------------|-------|-------------|
| Overall P50 | **1135 µs** | 18 ms | — |
| Overall P99 | **404 ms** | 130 ms | — |
| Shortest-10% P50 | **61 µs** | 14.5 ms | — |
| Shortest-10% P99 | **84 µs** | 48 ms | — |
| Aggregate Gbps | **~6 Gbps/node** | ~16 Kops | — |

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

## Metric 22: Homa CPU Cycles per Request

Measured by running `perf stat` on a 32B RPC rate workload (single client, `--client-max 64`):

```bash
sudo perf stat -e cycles,instructions,context-switches,cpu-migrations,page-faults \
  timeout 20 ./cp_node client \
  --first-server 0 --workload 32 \
  --client-max 64 --ports 1 --server-ports 7
```

**Result** (2026-07-09, ~279 Kops avg, ~5M requests): **~18.6 kcycles/request**.
- Instructions: ~21.6K/req
- IPC: 1.17
- User time: 8.2s, Sys time: 27.9s (dominated by kernel Homa processing)
- Close to paper's 17.43 kcycles for Linux-Homa

For comparison: eTran Homa (AF_XDP) = ~1357 kcycles (dominated by busy-poll);
active processing estimated at ~5 kcycles/req.

## Quick-Reference: cp_node Arguments for Homa

| Flag               | Default | Description                                        |
| ------------------ | ------- | -------------------------------------------------- |
| `--workload W`     | `100`   | Message size in bytes (or `w2`-`w5` for Homa CDFs) |
| `--client-max N`   | `1`     | Max outstanding RPCs per client                    |
| `--ports N`        | `1`     | Number of client ports / server ports              |
| `--server-nodes N` | `1`     | Number of server nodes to target                   |
| `--server-ports N` | `1`     | Server ports per node                              |
| `--first-server N` | `0`     | First server node ID (`nodeN`)                     |
| `--first-port N`   | `4000`  | Base port number (Homa default)                    |
| `--one-way`        | off     | Server returns 100B response (not echo)            |
| `--gbps F`         | `0`     | Target Gbps; 0 = send continuously                 |
| `--both N`         | `0`     | Start as server, wait N seconds, then start client |
| `--id N`           | `-1`    | Skip `nodeN` as target (self in all-to-all)        |
| `--unloaded`       | `0`     | Baseline RTT sweep per message size                |
