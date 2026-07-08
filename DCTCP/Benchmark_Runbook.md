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
| 7 | 1KB throughput, streaming (epoll) | **~2.8 Gbps**, ~346 Kops | `epoll_client`, 64 outstanding, single-threaded, 2-node |
| 8 | 2KB throughput, streaming (epoll) | **~4.6 Gbps**, ~283 Kops | `epoll_client`, 64 outstanding, single-threaded, 2-node |
| 9 | CPU cycles/request (1KB, epoll, client) | **~7.4 kcycles** | vs eTran TCP (AF_XDP): ~2.9 kcycles |

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
  as eTran TCP metrics, DCTCP achieves ~2.8 Gbps (1KB) and ~4.6 Gbps (2KB).
  This is **2.8-2.6× lower** than eTran's AF_XDP-accelerated TCP (7.95 Gbps / 11.79 Gbps),
  confirming that eTran's AF_XDP data-path bypass provides significant throughput
  gains for small-to-medium messages. The kernel TCP stack's sk_buff management,
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

**Result** (2026-07-08): **~2.8 Gbps out**, ~346 Kops/sec. RTT ~2.9 ms (under load).
For comparison: eTran TCP (AF_XDP) 1KB = **7.95 Gbps**, ~970 Kops.

## Metric 8: DCTCP 2KB Throughput (epoll, Streaming)

```bash
# Server (node0):
screen -dmS dctcp_epoll bash -c 'cd /local/eTran/eTran/tcp_app && \
  exec ./epoll_server -i 192.168.6.1 -b 2048'

# Client (node1):
timeout 15 stdbuf -oL ./epoll_client -i 192.168.6.1 -b 2048 -o 64 -f 1 -t 1
```

**Result** (2026-07-08): **~4.6 Gbps out**, ~283 Kops/sec.
For comparison: eTran TCP (AF_XDP) 2KB = **11.79 Gbps**, ~719 Kops.

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
