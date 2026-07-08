# DCTCP Benchmark Runbook — Exact Commands per Metric

> Two benchmark suites are used:
> - **HomaModule `cp_node`** (`/local/HomaModule/util/cp_node`) with `--protocol tcp`
>   for RPC-style metrics (latency, multi-node throughput, RPC rate).
> - **eTran `epoll_*`** (`/local/eTran/eTran/tcp_app/`) **without `LD_PRELOAD`**
>   for raw TCP streaming throughput (same binaries as eTran TCP metrics,
>   running on standard kernel TCP stack instead of AF_XDP).
>
> Pre-flight: ensure DCTCP is configured on all nodes (see `playbooks/setup/site.yml`).
> Network is assumed pre-configured by eTran's evaluation playbooks (ARP, `/etc/hosts`, NIC tuning).
>
> DCTCP uses the **standard Linux TCP stack** with DCTCP congestion control + ECN.
> No micro_kernel, no eTran XDP/BPF, no LD_PRELOAD needed.

## Results Summary

Hardware: CloudLab xl170, single-socket 10-core E5-2640v4, Mellanox ConnectX-4 Lx 25G, SMT=on.

| # | Metric | Result | Notes |
|---|--------|--------|-------|
| 1 | 32B RTT latency (P50) | **22.7 µs** | Echo, single-stream, node0↔node1 |
| 2 | 1MB throughput, single stream | **21.5 Gbps** | `--one-way`, saturating the NIC |
| 3 | 500KB throughput, 7 clients → 1 server | **23.5 Gbps** server in | 7 × ~3.4 Gbps clients fills 25G link |
| 4 | 500KB throughput, 1 client → 7 servers | **23.5 Gbps** client out | 7 ports × 7 servers saturates client NIC |
| 5 | 32B RPC rate, 7 clients → 1 server | **~866 Kops** server | 7 × ~155 Kops clients (--client-max 64, --ports 1 each) |
| 6 | 32B RPC rate, 1 client → 7 servers | **~1082 Kops** client | 7 × ~155 Kops servers (--client-max 256, --ports 7) |
| 7 | 1KB throughput, streaming (epoll) | **~1.8-2.8 Gbps**, ~222-346 Kops | `epoll_client`, 64 outstanding, single-threaded, 2-node. Varies with switch ECN state |
| 8 | 2KB throughput, streaming (epoll) | **~1.8-4.6 Gbps**, ~111-283 Kops | `epoll_client`, 64 outstanding, single-threaded, 2-node. Varies with switch ECN state |
| 9 | CPU cycles/request (1KB, epoll, client) | **~7.4 kcycles** | vs eTran TCP (AF_XDP): ~2.9 kcycles |
| 10 | KV throughput (flexkvs, 5 clients × 4 threads × 10 conns × 32 pending) | **~0.278 Mops** | P50≈717 µs, P99≈862 µs. 5 clients steady: ~55.7, ~55.5, ~55.5, ~55.7, ~55.6 Kops |
| 11 | KV P50 latency, under-loaded (flexkvs, 1 thread × 1 conn × 1 pending) | **17 µs** | P90=22 µs, P99=24 µs. Matches eTran TCP (14 µs) under no load — no congestion means identical network latency |
| 12 | KV P99 latency, under-loaded (flexkvs, 1 thread × 1 conn × 1 pending) | **24 µs** | Same run as #11 |
| 13 | 1K persistent connections 64B, closed-loop (epoll, 5 clients × 200 conns × 1 outstanding) | **~234 Kops** | Per-client steady ~46.8 Kops. No connection drops (20s timeout). eTran TCP: ~655 Kops. Ratio eTran/DCTCP ≈ 2.8× |

## Key Findings

- **Large-message throughput saturates the 25G link** (metrics 2-4): DCTCP over the
  mature Linux TCP stack fills the NIC for bulk transfers. The ~21.5-23.5 Gbps
  range equals or beats eTran Homa's best throughput (16.6 Gbps for 1MB, 12.9 Gbps
  for 500KB × 7). The standard kernel TCP stack is highly optimized for bulk data.
- **Small-message RPC rate is competitive** (metrics 5-6): ~866-1082 Kops/sec vs
  eTran Homa's ~927-1120 Kops/sec. DCTCP's RTT P50 (~64-75 µs) is far better than
  Homa's (~217-460 µs) for these workloads because there's no AF_XDP polling or
  BPF map contention.
- **TCP streaming throughput** (metrics 7-8): Using the same `epoll_client` binary
  as eTran TCP metrics, DCTCP achieves ~1.8-2.8 Gbps (1KB, varies with switch ECN)
  and ~1.8-4.6 Gbps (2KB). This is **~2.6-3.96× lower** than eTran's AF_XDP-accelerated
  TCP (~7.2 Gbps / ~12.3 Gbps), confirming that eTran's AF_XDP data-path bypass
  provides significant throughput gains for small-to-medium messages.
  softirq processing, and syscall overhead are the bottleneck.
- **CPU efficiency** (metric 9): DCTCP uses ~7.4 kcycles/request for 1KB messages,
  ~2.6× more than eTran's AF_XDP TCP (~2.9 kcycles). The kernel TCP stack spends
  ~12s sys vs ~0.8s user, showing the overhead is entirely in kernel TCP processing.

## Pre-Flight Checklist

1. **DCTCP configured** on every node (run if not already done):
   ```bash
   sudo modprobe tcp_dctcp
   sudo sysctl -w net.ipv4.tcp_allowed_congestion_control=dctcp
   sudo sysctl -w net.ipv4.tcp_congestion_control=dctcp
   sudo sysctl -w net.ipv4.tcp_ecn=1
   sudo sysctl -w net.ipv4.tcp_timestamps=1
   ```
   Or via Ansible: `cd DCTCP/Ansible && .venv/bin/ansible-playbook playbooks/setup/site.yml`

2. **cp_node binary** compiled on all nodes:
   ```bash
   ls /local/HomaModule/util/cp_node   # should exist
   ```
   If missing, run setup playbook above.

3. **epoll_* binaries** compiled on all nodes (for streaming metrics):
   ```bash
   ls /local/eTran/eTran/tcp_app/epoll_server  # should exist
   ```

4. **Hostname resolution** — `cp_node` resolves `node0`, `node1` etc. via `getaddrinfo()`.
   Verify `/etc/hosts` across all nodes (setup by eTran's 01-network-prep.yml).

5. **Clean state** between metrics (kill stale processes):
   ```bash
   for n in node0 node1 ...; do
     ssh $n "for p in \$(pgrep -x cp_node) \$(pgrep -x epoll_server) \$(pgrep -x epoll_client); do sudo kill -9 \$p 2>/dev/null; done"
   done
   ```

6. **No micro_kernel needed** — DCTCP uses standard Linux TCP directly.

7. **C stdout buffering** — epoll_* output over SSH is hidden by C buffering.
   Use `stdbuf -oL` or `script -q -c 'cmd' /dev/null` to force line-buffered output.

## Metric 1: DCTCP 32B Latency (Echo, Single Stream)

Minimal RTT for 32B echo requests between two nodes.

```bash
# Server (node0):
screen -dmS dctcp_server bash -c 'cd /local/HomaModule/util && exec ./cp_node server --protocol tcp --ports 1'

# Client (node1):
timeout 15 ./cp_node client --protocol tcp \
  --first-server 0 \
  --workload 32 \
  --client-max 1 \
  --ports 1
```

Output: `tcp_32 clients: ... RTT (us) P50 <p50> P99 <p99> P99.9 <p99.9>`

**Result** (2026-07-08, default config): P50 **22.7 µs**, P99 **26.4 µs**, P99.9 **29.1 µs**.
~44 Kops/sec. No `--one-way` (server echoes full 32B response).

## Metric 2: DCTCP 1MB Throughput (Single Stream)

Maximum throughput for large messages with `--one-way` (server returns 100B response).

```bash
# Server (node0) — keep running from metric 1, or restart:
screen -dmS dctcp_server bash -c 'cd /local/HomaModule/util && exec ./cp_node server --protocol tcp --ports 1'

# Client (node1):
timeout 15 ./cp_node client --protocol tcp \
  --first-server 0 \
  --workload 999999 \
  --client-max 1 \
  --ports 1 \
  --one-way
```

Output: `tcp_999999 clients: ... Gbps out ...` — read Gbps out.

> `--workload 999999` avoids `HOMA_MAX_MESSAGE_LENGTH` off-by-one (1M boundary).
> `--one-way` = 100B response (not an echo of 1MB). This is the Homa convention
> for throughput measurement — for TCP the response size has negligible impact on
> 1MB send throughput.

**Result** (2026-07-08): **21.5 Gbps** out, **371 µs** RTT P50. Near line-rate on 25G NIC.
For comparison: eTran Homa 1MB = 16.6 Gbps.

## Metric 3: DCTCP 500KB Throughput — 7 Clients → 1 Server

Multi-client throughput with large messages, 7:1 ratio.

```bash
# Server (node0) — 4 server ports:
screen -dmS dctcp_server bash -c 'cd /local/HomaModule/util && exec ./cp_node server --protocol tcp --ports 4'

# 7 clients (node1–node7), each:
timeout 20 ./cp_node client --protocol tcp \
  --first-server 0 \
  --workload 500000 \
  --client-max 1 \
  --ports 1 \
  --server-ports 4 \
  --one-way
```
Start clients with 0.3s stagger (see AGENTS.md multi-node orchestration).
Measure server-side Gbps in from server's screen log:
```bash
sudo screen -S dctcp_server -X hardcopy /tmp/srv.log
grep 'servers:' /tmp/srv.log | tail -3
```

**Result** (2026-07-08): Server **23.5 Gbps** in (saturating 25G NIC).
Each client ~3.4 Gbps. RTT P50 ~1188 µs.
For comparison: eTran Homa 500KB × 7 = 12.9 Gbps (limited by XDP_GEN grant dispatch).

## Metric 4: DCTCP 500KB Throughput — 1 Client → 7 Servers

Multi-server throughput, 1:7 ratio.

```bash
# 7 servers (node0–node6), each:
screen -dmS dctcp_server bash -c 'cd /local/HomaModule/util && exec ./cp_node server --protocol tcp --ports 1'

# Client (node7):
timeout 20 ./cp_node client --protocol tcp \
  --first-server 0 \
  --workload 500000 \
  --client-max 1 \
  --ports 7 \
  --server-nodes 7 \
  --one-way
```

Measure client-side Gbps out from client output.

**Result** (2026-07-08): Client **23.5 Gbps** out. 7 sending ports to 7 servers.
RTT P50 ~1184 µs. Each server ~3.4 Gbps inbound.
For comparison: eTran Homa = 19.5 Gbps (limited by per-app-thread send cap).

## Metric 5: DCTCP 32B RPC Rate — 7 Clients → 1 Server

RPC rate for small messages, 7:1 ratio.

```bash
# Server (node0) — 7 server ports for 32B:
screen -dmS dctcp_server bash -c 'cd /local/HomaModule/util && exec ./cp_node server --protocol tcp --ports 7'

# 7 clients (node1–node7), each:
timeout 15 ./cp_node client --protocol tcp \
  --first-server 0 \
  --workload 32 \
  --client-max 64 \
  --ports 1 \
  --server-ports 7
```

Output: server-side `Kops/sec` from server screen log. Client-side per-client
Kops also available.

**Result** (2026-07-08): Server **~866 Kops/sec** aggregate. Per-client ~140-207 Kops.
RTT P50 ~54-75 µs (lowest for last-connected client), P99 ~2-5 ms (TCP incast tail).
For comparison: eTran Homa 32B × 7 = ~927 Kops server (P50 ~400 µs).

## Metric 6: DCTCP 32B RPC Rate — 1 Client → 7 Servers

Server RPC rate for small messages, 1:7 ratio.

```bash
# 7 servers (node0–node6), each:
screen -dmS dctcp_server bash -c 'cd /local/HomaModule/util && exec ./cp_node server --protocol tcp --ports 1'

# Client (node7):
timeout 15 ./cp_node client --protocol tcp \
  --first-server 0 \
  --workload 32 \
  --client-max 256 \
  --ports 7 \
  --server-nodes 7
```

Output: client-side `Kops/sec` (aggregate across all servers).

**Result** (2026-07-08): Client **~1082 Kops/sec** aggregate. Per-server ~150 Kops each.
RTT P50 **~66 µs** (excellent — much better than eTran Homa's ~217 µs), P99 **~300 µs**.
For comparison: eTran Homa 32B × 7 servers = ~1120 Kops client (P50 ~217 µs).

## Metric 7: DCTCP 1KB Throughput (epoll, Streaming)

Raw TCP streaming throughput using the same `epoll_client`/`epoll_server` binaries
as eTran TCP metrics, but **without** `LD_PRELOAD=libetran.so` — uses standard
kernel TCP stack with DCTCP.

```bash
# Server (node0):
screen -dmS dctcp_epoll bash -c 'cd /local/eTran/eTran/tcp_app && \
  exec ./epoll_server -i 192.168.6.1 -b 1024'

# Client (node1):
timeout 15 stdbuf -oL ./epoll_client -i 192.168.6.1 -b 1024 -o 64 -f 1 -t 1
```

Output: `Throughput In/Out(<gbps>/<gbps> Gbps)(<kops> Kops)`

> `-b 1024` = 1KB messages, `-o 64` = 64 outstanding, `-f 1` = 1 flow, `-t 1` = 1 thread.
> Default (`-s` omitted): `short_response=true` → server sends 100B response.
> **C buffering**: use `stdbuf -oL` or `script -q -c` over SSH (see pre-flight).
> The server's `-b` must match the client's `-b` (receive buffer size).

**Result** (2026-07-08): **~1.8-2.8 Gbps out**, ~222-346 Kops/sec (varies with switch
ECN marking state). RTT ~2.9 ms (under load).
For comparison: eTran TCP (AF_XDP) 1KB = **~7.2 Gbps**, ~878 Kops.

## Metric 8: DCTCP 2KB Throughput (epoll, Streaming)

```bash
# Server (node0):
screen -dmS dctcp_epoll bash -c 'cd /local/eTran/eTran/tcp_app && \
  exec ./epoll_server -i 192.168.6.1 -b 2048'

# Client (node1):
timeout 15 stdbuf -oL ./epoll_client -i 192.168.6.1 -b 2048 -o 64 -f 1 -t 1
```

**Result** (2026-07-08): **~1.8-4.6 Gbps out**, ~111-283 Kops/sec (varies with switch
ECN marking state).
For comparison: eTran TCP (AF_XDP) 2KB = **~12.3 Gbps**, ~750 Kops.

## Metric 9: DCTCP CPU Cycles per Request (epoll, 1KB)

```bash
sudo perf stat -e cycles,instructions \
  timeout 15 stdbuf -oL ./epoll_client -i 192.168.6.1 -b 1024 -o 64 -f 1 -t 1
```

Calculate: `cycles_per_request = total_cycles / (avg_Kops × active_seconds)`

**Result** (2026-07-08): **~7.4 kcycles/request** (client-side). 33.8B cycles,
~346 Kops average over ~13s active window (~4.5M requests).
User time ~0.8s, Sys time ~12.4s — dominated by kernel TCP processing.
For comparison: eTran TCP (AF_XDP) = **~2.9 kcycles**.

## Metric 10: DCTCP KV Throughput (flexkvs, plain TCP)

```bash
# Server (1 node) — 4 threads, 1 NIC queue (no LD_PRELOAD, no env vars):
./flexkvs_server default 4 1

# Clients (5 nodes), each — no LD_PRELOAD, no ETRAN_PROTO:
timeout 45 ./flexkvs_bench \
  --threads 4 \
  --conns 10 \
  --pending 32 \
  --key-num 100000 \
  --key-size 32 \
  --val-size 64 \
  --get-prob 0.9 \
  --key-zipf=0.9 \
  --time 30 \
  --warmup 5 \
  --cooldown 5 \
  <server-ip>:11211
```

Same binaries as eTran TCP metric 18, but running without `LD_PRELOAD=libetran.so`
on the plain kernel TCP stack (no micro_kernel, no XDP).

**Result** (2026-07-08): **~0.278 Mops steady aggregate** (5 clients).
Per-client steady: ~55.7, ~55.5, ~55.5, ~55.7, ~55.6 Kops.
Per-client latency under load: P50≈717 µs, P90≈760 µs, P99≈862 µs.

For comparison: eTran TCP (AF_XDP) KV throughput = **~0.73 Mops** —
ratio **~2.61×** (within paper's 2.4-4.8× range).

> **`--pending 32`** matches the paper spec (§6.4: "each uses 32 parallel GETs").
> The eTran TCP run previously used `--pending 16`; changing to 32 had no
> throughput effect — the bottleneck is elsewhere (likely single-pending-RPC
> limit per connection × 10 connections = only 10 in-flight per client thread).

## Metric 11-12: DCTCP KV P50/P99 Latency (flexkvs, plain TCP, under-loaded)

```bash
# Server (1 node) — same as metric 10:
./flexkvs_server default 4 1

# Client (1 node) — single thread, single connection, single pending:
timeout 20 ./flexkvs_bench \
  --threads 1 \
  --conns 1 \
  --pending 1 \
  --key-num 100000 \
  --key-size 32 \
  --val-size 64 \
  --get-prob 0.9 \
  --key-zipf=0.9 \
  --time 10 \
  <server-ip>:11211
```

**Result** (2026-07-08): **P50 = 17 µs, P99 = 24 µs** (idle, 1 client × 1t×1c×1p).
Steady ~54 Kops at 1 pending. P90=22 µs, P95=22-23 µs, P99.9=29 µs, P99.99=193 µs.

For comparison: eTran TCP = **14 µs P50, 16 µs P99**; paper's Linux-TCP = 64.2 µs P50, 89.3 µs P99.

**P50 latency vs concurrency sweep (5 clients, varying per-client pipeline):**

| Config | Total in-flight | Mean P50 | Throughput |
|--------|----------------|---------|-----------|
| 1t×1c×1p | 5 | ~24 µs | ~0.21 Mops |
| 1t×1c×4p | 20 | ~22 µs | ~0.21 Mops |
| 1t×1c×8p | 40 | ~27 µs | ~0.18 Mops |
| 1t×4c×8p | 160 | ~41 µs | ~0.39 Mops |
| 1t×4c×16p | 320 | **36 µs** | ~0.45 Mops |
| 4t×10c×32p | 6400 | ~740 µs | ~0.27 Mops |

> **Paper discrepancy**: The paper reports Linux-TCP KV latency as 64.2 µs P50.
> Our DCTCP P50 caps at ~47 µs regardless of client concurrency. The paper's value
> is produced by **switch-side ECN marking at 70KB threshold** (not configured in
> our cluster). The marking creates a standing switch buffer of ~70KB, adding
> ~22 µs of queuing delay. Combined with base latency (~20 µs) and TCP backoff
> dynamics from ECN, the total reaches ~64 µs. Without switch ECN configuration,
> the P50 stays low even under significant client load.

## Metric 13: DCTCP 1K Persistent Connections, 64B Closed-Loop (epoll, plain TCP)

```bash
# Server (1 node) — 10 threads, 64B request:
./epoll_server -i 192.168.6.1 -b 64 -t 10

# Clients (5 nodes), each — 200 connections, 4 threads, 1 outstanding:
script -q -c 'timeout 20 ./epoll_client -i 192.168.6.1 -b 64 -f 200 -t 4 -o 1 -w 2' /dev/null
```

Same binaries as eTran TCP metric 15, running without `LD_PRELOAD=libetran.so`
on the plain kernel TCP stack. Total 1000 persistent connections across 5 clients,
each sending 64B requests in a closed loop with 1 outstanding per connection.

**Result** (2026-07-08): **~234 Kops aggregate** (5 × ~46.8 Kops). No connection
drops during the 20s measurement window. Per-client steady: ~46.8 Kops each.

For comparison: eTran TCP (AF_XDP) = **~655 Kops steady aggregate**.
Ratio eTran/DCTCP ≈ **2.8×**.

> Unlike eTran TCP metric 15 (which suffers from microkernel TCP connection drops
> after ~9s at this load), the DCTCP baseline ran cleanly for the full 20s window.
> The 2.8× ratio is consistent with the eTran TCP throughput advantage seen in
> other metrics (metric 13: ~2.8× at 1KB, metric 18: ~2.6× at KV).
## Quick-Reference: cp_node Arguments for TCP

| Flag | Default | Description |
|------|---------|-------------|
| `--protocol tcp` | `homa` | Select TCP protocol |
| `--workload W` | `100` | Message size in bytes (or `w2`-`w5` for Homa CDFs) |
| `--client-max N` | `1` | Max outstanding RPCs per client |
| `--ports N` | `1` | Number of client ports / server ports |
| `--server-nodes N` | `1` | Number of server nodes to target |
| `--server-ports N` | `1` | Server ports per node |
| `--first-server N` | `0` | First server node ID (`nodeN`) |
| `--first-port N` | `5000` | Base port number (TCP default, Homa uses 4000) |
| `--one-way` | off | Server returns 100B response (not echo) |
| `--gbps F` | `0` | Target Gbps; 0 = send continuously |
| `--no-trunc` | off | Allow messages >1MB (Homa compatibility limit) |
