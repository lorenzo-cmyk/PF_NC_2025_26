# eTran Benchmark Runbook — Exact Commands per Metric

Cross-references each metric from `eTran_reproduction_metrics_relevant.md`
against source code in:
- **eTran repo**: `https://github.com/eTran-NSDI25/eTran` (`eTran/homa_app/cp_node.cc`,
  `eTran/tcp_app/epoll_*.cc`, `eTran/tcp_app/flexkvs_*`, `eTran/lib/eTran_common.cc`)
- **Homa upstream**: `https://github.com/PlatformLab/HomaModule` (`util/cp_node.cc`)
- **Paper**: §6.1, Figures 5-6 (Gbps values confirmed from figure captions)

---

## Pre-Flight Checklist

1. **Microkernel** must be running on every node:
   ```bash
   cd /local/eTran/eTran/micro_kernel
   sudo ./micro_kernel -i ens1f1np1 -q 10
   ```
   > **`-q 10` is required**: NIC has 10 combined queues (check with `ethtool -l ens1f1np1`).
   > Default 20 crashes with `Number of queues is greater than NIC queues (20 > 10)`,
   > exacerbated by SMT=off halving the reported core count.
   >
   > **⚠️ BPF patch required** for large Homa messages: the XDP_EGRESS program drops
   > non-DATA egress packets (grants, resends) at `micro_kernel/eBPF/homa/main.c:240`.
   > Apply the patch at `main.c` line 235-248 to move the `c->type != DATA` check
   > before the `data_header` bounds check, then `make -j$(nproc)` to rebuild.
   > See Known Limitations #7 for the exact diff.

2. **App binaries** live in their build subdirectories:
   ```
   /local/eTran/eTran/homa_app   → cp_node
   /local/eTran/eTran/tcp_app    → epoll_*, lat_*, flexkvs_*
   ```

3. **Hostname resolution** — `cp_node` resolves `node0`, `node1` etc. via `getaddrinfo()`.
   Verify `/etc/hosts` or DNS across all nodes.

4. **Interface name** is hardcoded as `ens1f1np1` (`IF_NAME` macro in cp_node.cc:48,
   micro_kernel.cc, xdpsock.c). Recompile if your NIC differs.

5. **Headless execution** — run benchmarks non-interactively via ssh:

   ```bash
   # Kill, restart, run pattern (each metric requires fresh micro_kernels):
   ssh node0 'sudo pkill -9 micro_kernel; sudo pkill -9 cp_node'
   ssh node1 'sudo pkill -9 micro_kernel'

   ssh node0 'sudo nohup bash -c "cd /local/eTran/eTran/micro_kernel && ./micro_kernel -i ens1f1np1 -q 10" </dev/null >/tmp/micro.log 2>&1 &'
   ssh node1 'sudo nohup bash -c "cd /local/eTran/eTran/micro_kernel && ./micro_kernel -i ens1f1np1 -q 10" </dev/null >/tmp/micro.log 2>&1 &'
   sleep 6

   ssh node0 'nohup bash -c "cd /local/eTran/eTran/homa_app && ETRAN_PROTO=homa ./cp_node server ..." </dev/null >/tmp/server.log 2>&1 &'
   sleep 2

   ssh node1 "cd /local/eTran/eTran/homa_app && timeout 10 env ETRAN_PROTO=homa ./cp_node client ... 2>&1"
   ```
   > Use `timeout N env VAR=val` (not `timeout VAR=val`) — `timeout` doesn't parse
   > environment prefixes, use explicit `env`. `</dev/null` prevents stdin noise
   > (the micro_kernel monitor thread complains with "Unknown command" otherwise).

6. **Shm cleanup** between metrics — mandatory to avoid stale BPF state:
   ```bash
   ssh node0 'sudo rm -f /dev/shm/BufferPool_* /dev/shm/UMEM_* /dev/shm/LRPC_*'
   ssh node1 'sudo rm -f /dev/shm/BufferPool_* /dev/shm/UMEM_* /dev/shm/LRPC_*'
   ```

---

## cp_node Argument Reference

Verified against `eTran/homa_app/cp_node.cc` and upstream `PlatformLab/HomaModule/util/cp_node.cc`.

### Client options (`cp_node client [opts]`)

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--workload` | string | `"100"` | `w1`-`w5` (Homa CDFs) or integer for fixed-size bytes |
| `--client-max` | int | `1` | Max outstanding RPCs per machine (÷ ports) |
| `--ports` | int | `1` | Sending threads (one per port) |
| `--server-nodes` | int | `1` | Number of server nodes to target |
| `--server-ports` | int | `1` | Server ports per node |
| `--first-server` | int | `1` | First server node ID (`nodeN`) |
| `--gbps` | float | `0.0` | Target Gbps; **0 = send continuously** (closed-loop) |
| `--one-way` | flag | `false` | Server returns 100B response (not echo) |
| `--id` | int | `-1` | This node's ID; skip `node{id}` as target |
| `--both` | int | `0` | Start as server, wait N seconds, then start client |
| `--unloaded` | int | `0` | Baseline RTT sweep per message size (Homa only) |
| `--queues` | int | `1` | NIC queues (eTran). **Never set on client** — kills throughput |

### Server options (`cp_node server [opts]`)

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--ports` | int | `1` | Listening ports/threads. **Max 4** (buffer pool crash at >4) |
| `--first-port` | int | `4000` | Lowest port number |

### Key semantics

- **`--gbps 0`** = unlimited (closed-loop, throttled only by `--client-max`). Nonzero = open-loop Poisson at that Gbps.
- **`--one-way`** = response capped at **100B** (not 32B as paper states). `short_response` flag in message header.
- **`--workload 1000000`** hits exact `HOMA_MAX_MESSAGE_LENGTH` boundary. Use `999999`.
- **`--both N`** = node starts server (using `--server-ports` ports), waits N seconds, then starts client. Used for all-to-all cluster topology.
- **`--id N`** = prevents sending to `nodeN` (self). Required with `--both` in all-to-all.
- `--server-ports`, `--workload`, `--gbps`, `--client-max`, `--one-way` are **client-only**. Server ignores them.

---

## Table 1 — Primary eTran Metrics

### 1. eTran - Homa | Median RTT latency, 32B requests, single client | 11.8 µs | 2-Node

Paper §6.1: "single client thread to send back-to-back requests (32B) to a
single-threaded server, which responds with a 32-byte response."

```bash
# Server (node0) — single-threaded, echoes 32B response (no --one-way):
ETRAN_PROTO=homa ./cp_node server

# Client (node1):
timeout 15 env ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 32
```
Output every 1s: `Clients: <Kops> Kops/sec, <gbps> Gbps out, ..., RTT (us) P50 <p50> P99 <p99> P99.9 <p99.9>`
Read P50 for the metric.

### 2. eTran - Homa | Throughput, 1MB requests, back-to-back | 17.7 Gbps | 2-Node

Paper §6.1: "single client thread to send back-to-back requests (1MB) to a
single-threaded server, which responds with a 32-byte response."

```bash
# Server (node0) — single-threaded:
ETRAN_PROTO=homa ./cp_node server

# Client (node1) — single-stream back-to-back:
timeout 15 env ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 999999 \
  --one-way
```
Output: `Clients: ... Gbps out ...` — read Gbps out for the metric.

> **`--one-way`** makes the server return a **100-byte** response (not 32B as the
> paper states — the `short_response` flag caps at 100B in cp_node source). This
> doesn't meaningfully affect 1MB throughput measurements.
>
> **`--workload 999999`** instead of `1000000`: avoids the `HOMA_MAX_MESSAGE_LENGTH`
> off-by-one (length 1000000 hits the exact buffer boundary; use 999999).
>
> `--client-max 1 --ports 1` are defaults — omitted for clarity. `--gbps 0` (default)
> means "send continuously" (closed-loop back-to-back).

### 3. eTran - Homa | Multi-threaded server throughput, 500KB, 7 clients | 23.0 Gbps | 8-Node

Paper §6.1: "multi-threaded server receiving concurrent RPCs (500KB) from 7 clients".

```bash
# Server (node0) — multi-threaded (4 ports = 4 server threads):
ETRAN_PROTO=homa ./cp_node server --ports 4

# 7 client nodes (node1–node7), each:
timeout 30 env ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 500000 \
  --client-max 64 \
  --server-ports 4 \
  --one-way
```
Measure server-side Gbps in (output: `Servers: ... Gbps in ...`).

> **`--ports 4`** on server: 4 server threads (max before buffer pool crash at >4).
> Paper used more threads but eTran's buffer pool asserts `nr_slabs_avail > nr_slabs`
> with `--ports > 4`. Client uses `--server-ports 4` to target all 4 server ports.
>
> **`--workload 500000`**: 500KB (paper's wording). Not 524288 (512KiB).
>
> Start clients with 0.3s stagger (see AGENTS.md multi-node orchestration).

### 4. eTran - Homa | Multi-threaded client throughput, 500KB, 7 servers | 22.7 Gbps | 8-Node

Paper §6.1: "multi-threaded client sending concurrent RPCs to 7 servers".

```bash
# 7 server nodes (node0–node6), each:
ETRAN_PROTO=homa ./cp_node server

# 1 client (node7) with 7 ports matching 7 servers:
timeout 30 env ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 500000 \
  --client-max 64 \
  --ports 7 \
  --server-nodes 7 \
  --one-way
```
Measure client-side Gbps out.

> `--ports 7`: 7 sending threads (one per server). `--server-ports 1` is default.
> `--client-max 64`: 64/7 ≈ 9 outstanding per port, 64 total.
> `--server-nodes 7` with `--first-server 0`: targets node0–node6.

### 5. eTran - Homa | Client RPC rate, 32B | 2.9 Mops | 8-Node (7:1 ratio)

Paper §6.1: "RPC rate for small messages (32B), maintaining the same
client-to-server ratio" — same 7:1 as metric 3.

```bash
# Server (node0) — 7 server threads for 32B (small messages, no buffer pool issue):
ETRAN_PROTO=homa ./cp_node server --ports 7

# 7 client nodes (node1–node7), each:
timeout 30 env ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 32 \
  --client-max 256 \
  --ports 7 \
  --server-ports 7
```
Output: `Clients: <Kops> Kops/sec` — aggregate across all 7 clients for Mops.

> 32B messages don't trigger the buffer pool crash at `--ports 7` (no grants needed).
> `--client-max 256`: 256/7 ≈ 36 outstanding per port.

### 6. eTran - Homa | Server RPC rate, 32B | 3.3 Mops | 8-Node (1:7 ratio)

Paper §6.1: same 1:7 ratio as metric 4 — 1 client → 7 servers.

```bash
# 7 server nodes (node0–node6), each:
ETRAN_PROTO=homa ./cp_node server

# Client (node7):
timeout 30 env ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 32 \
  --client-max 256 \
  --ports 7 \
  --server-nodes 7
```
Output: `Servers: <Kops> Kops/sec` (aggregate across all 7 servers).

### 7–12. eTran - Homa | P50/P99 tail latency slowdown, W2–W5 | 10-Node Cluster

Paper §6.1: "conducted with 10 machines. In this experiment, **each node serves as
both a multi-thread client and a multi-thread server simultaneously**. Clients
randomly select servers to issue a batch of RPCs."

Workloads W2–W5 from the Homa SIGCOMM paper, defined in `homa_app/dist.cc`.
Figure 5 captions give the exact offered load per workload:
- **W2: 3.2 Gbps** (short-message dominated)
- **W3: 14 Gbps** (short-message dominated)
- **W4: 20 Gbps** (large-message dominated)
- **W5: 20 Gbps** (large-message dominated)

These match the upstream Homa `cp_vs_tcp` script:
`[["w2", 3.2, 5], ["w3", 14, 10], ["w4", 20, 20], ["w5", 20, 30]]`

**Per-workload parameters** (change all three for each run):

| Workload | `--workload` | `--gbps` | `RUN_SECONDS` |
|----------|-------------|----------|---------------|
| W2       | `w2`        | `3.2`    | `5`           |
| W3       | `w3`        | `14`     | `10`          |
| W4       | `w4`        | `20`     | `20`          |
| W5       | `w5`        | `20`     | `30`          |

#### All-to-all topology (paper's setup)

Run on all 10 nodes simultaneously. Each node acts as both client and server
via `--both N` (starts server, waits N seconds, then starts client). `--id`
prevents a node from sending to itself:

```bash
# Repeat for each workload (w2, w3, w4, w5) twice:
#   once with eTran kernel booted,
#   once with stock Linux kernel booted (for Linux-Homa baseline).

# On each node (node0–node9), set NODE_ID and workload params:
NODE_ID=0          # change per node
WL=w2              # w2, w3, w4, or w5
GBPS=3.2           # 3.2, 14, 20, or 20 (see table above)
RUN_SECONDS=5      # 5, 10, 20, or 30 (see table above)

(echo "client --first-server 0 --server-nodes 10 --workload ${WL} --client-max 100 --ports 4 --server-ports 4 --one-way --gbps ${GBPS} --both 2 --id ${NODE_ID}"; \
 sleep $((RUN_SECONDS + 5)); \
 echo "dump_times /tmp/rtts_node${NODE_ID}.txt"; \
 sleep 1; \
 echo "exit") \
| timeout $((RUN_SECONDS + 15)) env ETRAN_PROTO=homa ./cp_node 2>&1
```
Record P50/P99/P99.9 RTT (µs) from 1s stats output.
Slowdown = `eTran_RTT / Linux_RTT` (run same workload on stock Linux for baseline).

> **`--both 2`**: node starts as server (4 ports via `--server-ports 4`), waits 2s,
> then starts client with 4 sending threads (`--ports 4`).
> **`--id N`**: skips `nodeN` (itself) when building the server address list.
> **`--server-ports 4`**: max before buffer pool crash (`>4` asserts).
> **Gbps per workload**: W2=3.2, W3=14, W4=20, W5=20. Using 20 for W2/W3 is WRONG.

#### Collecting individual RTT samples (for W4/W5 shortest-10% filtering)

Paper Figure 6: "RTT distributions for the shortest messages (10%) in W4 and W5".

`dump_times` writes per-RPC samples as `<length> <rtt_us>` pairs. It must be
issued as a separate command — in headless mode (single argv command), it can't
run. Use the interactive pipe pattern above, or:

```bash
# Interactive mode: start cp_node, issue commands via stdin
(echo "client --first-server 0 ..."; sleep 30; echo "dump_times /tmp/rtts.txt"; echo "exit") | ./cp_node
```

Post-process to filter shortest 10%:
```bash
# Sort by message length, take lowest decile, then compute P50/P99 of that subset
awk '{print $1, $2}' /tmp/rtts_node*.txt | sort -n | \
  awk 'NR==1{total=0} {vals[NR]=$2; total++} END{
    decile=int(total*0.1);
    for(i=1;i<=decile;i++) print vals[i]
  }' | sort -n | awk '
    {a[NR]=$1}
    END{
      print "P50:", a[int(NR/2)];
      print "P99:", a[int(NR*99/100)];
      print "P99.9:", a[int(NR*999/1000)]
    }'
```

### 13. eTran - TCP | 1KB throughput, 64 outstanding, single-threaded | 4.8x Linux | 2-Node

```bash
# Server:
ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_server -i 192.168.6.1 -b 1024

# Client:
timeout 30 env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_client -i 192.168.6.1 -b 1024 -o 64 -f 1 -t 1
```
Output: `Throughput In/Out(<gbps>/<gbps> Gbps)(<kops> Kops)` every second.

> **`-b`** is message/request size (bytes), NOT buffer size.
> **`-l`** (`max_buf_size`, default 4096) omitted — 4096 is enough for 1KB messages.
> epoll_client/server run `while(1)` — **always wrap in `timeout`**.
> **`-s`** flag (default on): response size = request size. Without `-s`: response = 100B.

### 14. eTran - TCP | 2KB throughput, 64 outstanding, single-threaded | 0.87x TAS | Medium

```bash
# Server:
ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_server -i 192.168.6.1 -b 2048

# Client:
timeout 30 env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_client -i 192.168.6.1 -b 2048 -o 64 -f 1 -t 1
```

### 15. eTran - TCP | 1K persistent connections, 64B requests | 2.26x Linux | 6-Node

```bash
# Server (1 node) — 10 threads:
ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=10 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_server -i 192.168.6.1 -b 64 -t 10

# Clients (5 nodes), each: 200 connections → 1000 total:
timeout 30 env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=4 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_client -i 192.168.6.1 -b 64 -f 200 -t 4 -o 1 -w 2
```

> **`-w 2`**: `wait_seconds` — 2s delay after connecting before measuring.
> **`-o 1`**: 1 outstanding request per connection (closed-loop).

### 16. eTran - TCP | Short-lived 16 msg/conn, 1K concurrent | 42.7x Linux | 6-Node

**⚠️ CAVEAT**: `epoll_client` only supports **persistent** connections. The public
eTran repo does not include a short-lived TCP connection benchmark binary.
This metric requires a custom benchmark that opens/closes connections and sends
16 messages each. Not reproducible with the public repo as-is.

### 17. eTran - TCP | Short-lived 256 msg/conn, 1K concurrent | 5.4x Linux | Medium

**⚠️ Same caveat as #16. Not reproducible with the public repo as-is.**

### 18. eTran - TCP | KV throughput, 100K keys, Zipf s=0.9, 9:1 GET:SET | 2.4~4.8x Linux | 6-Node

```bash
# Server (1 node) — 4 threads, 1 NIC queue:
ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=4 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./flexkvs_server default 4 1

# Clients (5 nodes), each:
timeout 45 env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=4 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./flexkvs_bench \
  --threads 4 \
  --conns 10 \
  --pending 16 \
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
Output: `TP: total=<mops> mops  50p=<us> 90p=<us> 95p=<us> 99p=<us> 99.9p=<us> 99.99p=<us>` every second.

> **`ETRAN_NR_APP_THREADS=4`** must match the application thread count (server: 4
> positional arg, client: `--threads 4`). Previously set to 1 — wrong.
> **`--time`/`--warmup`/`--cooldown` are stored but never enforced** by flexkvs_bench
> (no phase transition to DONE). Always wrap in `timeout`. The `--time 30` is
> informational only; `timeout 45` provides the actual 30s run + 5s warmup + buffer.
> Server port is hardcoded to **11211** (memcached).

### 19. eTran - TCP | KV P50 latency, under-loaded | 17.2 µs | 6-Node

```bash
# Same as #18 but with just 1 client thread, 1 connection, 1 pending:
timeout 20 env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./flexkvs_bench \
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
Read P50 µs from output (`50p=<us>`).

### 20. eTran - TCP | KV P99 latency, under-loaded | 27.5 µs | 6-Node

Same command as #19. Read P99 µs from output (`99p=<us>`).

### 21. eTran - TCP | Total CPU cycles per request | 4.37 kcycles | 2-Node CPU Profiling

```bash
# Run TCP throughput test (#13) under perf:
perf stat -e cycles,instructions,LLC-load-misses,LLC-store-misses \
  -e context-switches,cpu-migrations,page-faults \
  timeout 30 env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_client -i 192.168.6.1 -b 1024 -o 64 -f 1 -t 1

# Calculate kcycles/request = (total cycles) / (total requests)

# For per-component breakdown (matching Table 5), use perf record + report:
perf record -g -F 99 -- timeout 30 env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_client -i 192.168.6.1 -b 1024 -o 64 -f 1 -t 1
perf report --stdio --sort=comm,dso,symbol,dso_from,symbol_from
# Map symbols to the categories in Table 5 (Application, Socket/RPC, Data Copy,
# Sk_buff, TCP/Homa+IP, Lock/Unlock, NIC Driver, Memory Mgmt, Scheduling, Other).
```

### 22. eTran - Homa | Total CPU cycles per request | 5.48 kcycles | 2-Node CPU Profiling

```bash
# Run Homa throughput test (#2) under perf:
perf stat -e cycles,instructions \
  timeout 15 env ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 999999 \
  --one-way
```

---

## Table 2 — CPU Cycles Breakdown (Table 5)

Requires `perf` with hardware counters. Run against TCP and Homa benchmarks
under single-NAPI-context stress. The source code categories are:

| Paper Category     | Kernel Symbols to Match                              |
|:-------------------|:-----------------------------------------------------|
| Application        | User-space app code (cp_node/epoll_client main loop) |
| Socket/RPC         | `__sys_sendto`, `__sys_recvmsg`, socket layer        |
| Data Copy          | `copy_user_enhanced_fast_string`, `memcpy_erms`      |
| Sk_buff            | `__alloc_skb`, `__kfree_skb`, `skb_*`                |
| TCP/Homa + IP      | `tcp_*`, `homa_*`, `ip_*`, `ip6_*`                  |
| Lock/Unlock        | `_raw_spin_lock`, `mutex_lock`, `mutex_unlock`       |
| NIC Driver         | `mlx5e_*`, `mlx5_*` (adapt to your NIC driver)      |
| Memory Mgmt        | `__alloc_pages`, `__free_pages`, `slab_*`            |
| Scheduling         | `__schedule`, `schedule`, `try_to_wake_up`           |
| Other              | Everything else                                      |

```bash
perf record -g -F 99 -o /tmp/perf.data <benchmark-command>
perf report --stdio -i /tmp/perf.data --sort=comm,dso,symbol | head -80
```

---

## Table 3.1 — XDP_EGRESS Egress Overhead (Table 3)

Requires the eTran kernel's `XDP_EGRESS` hook. Benchmarked via `xdpsock` in
`/local/eTran/bench-afxdp/`. xdpsock runs indefinitely — always wrap in `timeout`.

### AF_XDP tx-only baseline | 11.55 Mpps
```bash
sudo timeout 15 taskset -c 2 ./xdpsock -i ens1f1np1 -q 2 -t -s 64 -N -z
```

### + Empty XDP_EGRESS | 10.79 Mpps (6.6% loss)
**⚠️** Requires eTran kernel BPF program with empty `XDP_EGRESS` hook loaded:
```bash
# Load empty XDP_EGRESS BPF program (depends on eTran kernel config)
# Then run the same txonly benchmark:
sudo timeout 15 taskset -c 2 ./xdpsock -i ens1f1np1 -q 2 -t -s 64 -N -z
```

### + OOO Completion | 9.95 Mpps (13.9% loss)
Enables out-of-order completion buffer support (eTran kernel feature).

### + Array Lookup | 9.71 Mpps (15.9% loss) | Medium
### + Hashmap Lookup | 9.10 Mpps (21.2% loss) | Medium

These require loading specific BPF programs via the eTran kernel's BPF loader.
The paper measures progressive overhead of each feature stacked. Run txonly
with each BPF program variant loaded.

---

## Table 3.2 — XDP_GEN Packet Generation (Table 4)

### l2fwd baseline | 6.73 Mpps overall, 1.74 active cores | Medium
```bash
sudo timeout 15 taskset -c 2 ./xdpsock -i ens1f1np1 -q 2 -l -N -z -B -b 256
```

### rx-drop + XDP_GEN | 6.03 Mpps overall, 1.35 active cores | 2-Node
**⚠️** `XDP_GEN` is an eTran kernel hook — requires a BPF program that generates
ACK/credit packets using the `XDP_GEN` hook. The rx-drop side:
```bash
sudo timeout 15 taskset -c 3 ./xdpsock -i ens1f1np1 -q 3 -r -N -z
```

---

## Quick-Reference: Key Source Code in eTran repo

| File                                    | Key Locations                                                           |
|:----------------------------------------|:------------------------------------------------------------------------|
| `eTran/homa_app/cp_node.cc`             | L48 `IF_NAME`, L1528 `client_stats` (Kops/Gbps/RTT P50-P99.9), L1457 `server_stats`, L1603 `client_cmd` defaults reset, L1929 `server_cmd` |
| `eTran/homa_app/dist.cc`                | `w1`-`w5` distribution arrays, `dist_lookup()` handles int→fixed-size or wN name |
| `eTran/tcp_app/epoll_client.cc`         | `parse_args`: `-b`(msg size) `-i` `-f`(flows) `-t`(threads) `-o`(outstanding) `-w`(wait) `-l`(max_buf_size) `-s`(response toggle) |
| `eTran/tcp_app/epoll_server.cc`         | `parse_args`: `-b` `-i` `-t` `-l` `-s`; runs `while(1)`, no loop count |
| `eTran/tcp_app/flexkvs_bench.cc`        | Uses `flexkvs/commandline.c` `parse_settings()`; `--time`/`--warmup`/`--cooldown` stored but NOT enforced |
| `eTran/tcp_app/flexkvs_server.cc`       | 3 positional args: `CONFIG THREADS QUEUES`; port hardcoded to 11211 |
| `eTran/tcp_app/lat_client.cc`           | 500K ping-pongs, sorted P50/P99/P99.9 output; `-c` flag broken (fallthrough bug) |
| `eTran/micro_kernel/micro_kernel.cc`    | L51 `opt_num_queues=20` default, L106-121 `-q` flag, `-i` iface, `-b` busy-poll |
| `eTran/lib/eTran_common.cc`             | `__attribute__((constructor)) pre_main` — reads `ETRAN_PROTO` (required), `ETRAN_NR_APP_THREADS` + `ETRAN_NR_NIC_QUEUES` (required for TCP only) |
| `eTran/shared_lib/`                     | Builds `libetran.so` via `interpose.cc` — LD_PRELOAD intercepts `socket`/`epoll_wait`/`read`/`write` |
| `bench-afxdp/xdpsock.c`                 | `-r`(rx-drop) `-t`(tx-only) `-l`(l2fwd) modes, `-s` pkt size, `-b` batch, `-z` zero-copy, `-N` native mode |

---

## Known Limitations

1. **Short-lived TCP connections (metrics #16–17)** — Not supported by any
   binary in the public repo. `epoll_client` only creates persistent connections.
   A custom benchmark is needed. Not reproducible as-is.

2. **Interface name** — Hardcoded as `ens1f1np1` in cp_node.cc:48,
   micro_kernel.cc, and xdpsock.c. CloudLab xl170 uses Mellanox ConnectX-4 Lx
   (not ConnectX-5). Check `ip link` and recompile if different.

3. **CPU cycles breakdown (Table 5)** — Requires hardware PMU counters
   and careful kernel symbol mapping. Not automatically categorized.

4. **XDP_EGRESS / XDP_GEN benchmarks (Tables 3–4)** — These test eTran's
   new eBPF hooks. BPF programs implementing the tested features are needed
   but not found as standalone build targets in the repo. They may be embedded
   in the microkernel/eTran library build.

5. **Multi-node tests** — The cluster benchmark (metrics #7-12) uses all-to-all
   topology with `--both` and `--id`. Start nodes with 0.3s stagger
   (see AGENTS.md multi-node orchestration).

6. **TAS comparison baselines** — TAS (Transport Acceleration Substrate) is
   a separate project not included in the eTran repo. For #14, compare eTran
   TCP against Linux TCP only; TAS comparison requires a separate TAS setup.

7. **Homa large-message grants (metrics #2–4, #7–12, #22)** — The upstream
   eTran XDP_EGRESS BPF program at `micro_kernel/eBPF/homa/main.c:240` drops
   grant/resend packets because the `data_header` bounds check runs before the
   `c->type != DATA` check. All large Homa benchmarks **require** this patch:

   ```diff
   --- a/micro_kernel/eBPF/homa/main.c
   +++ b/micro_kernel/eBPF/homa/main.c
        eth = (struct ethhdr *)data;
   +    CHECK_AND_DROP_LOG(eth + 1 > data_end, "eth + 1 > data_end");
        iph = (struct iphdr *)(eth + 1);
   +    CHECK_AND_DROP_LOG(iph + 1 > data_end, "iph + 1 > data_end");
        c = (struct common_header *)(iph + 1);
   -    d = (struct data_header *)c;
   -
   -    CHECK_AND_DROP_LOG(d + 1 > data_end, "d + 1 > data_end");
   +    CHECK_AND_DROP_LOG(c + 1 > data_end, "c + 1 > data_end");

        CHECK_AND_DROP_LOG(iph->protocol != IPPROTO_HOMA, "not HOMA protocol");

        if (unlikely(data_meta->tx.slowpath)) {
            return xmit_packet(ctx, eth, iph);
        }
   -    CHECK_AND_DROP_LOG(c->type != DATA, "not DATA packet");
   +    if (c->type != DATA) {
   +        return xmit_packet(ctx, eth, iph);
   +    }
   +
   +    d = (struct data_header *)c;
   +    CHECK_AND_DROP_LOG(d + 1 > data_end, "d + 1 > data_end");
   ```

   > **Rebuild after patching**: `touch micro_kernel/eBPF/homa/main.c && make -j$(nproc)`
   > Then restart the micro_kernel on all nodes.

8. **`--one-way` response size** — `--one-way` caps server responses at **100 bytes**
   (`header->short_response ? 100 : header->length` in cp_node source). The paper
   says "32-byte response" (§6.1). This 100B vs 32B difference doesn't meaningfully
   affect large-message throughput. Without `--one-way`, the server echoes the full
   request size, doubling grant-path load. 32B benchmarks (metrics #1, #5–6) do NOT
   use `--one-way` (server echoes 32B). All large-message benchmarks use `--one-way`.

9. **`HOMA_MAX_MESSAGE_LENGTH` off-by-one** — `HOMA_MAX_MESSAGE_LENGTH = 1000000`
   (`common/tran_def/homa.h:8`). `--workload 1000000` hits the exact buffer boundary
   (`msg_len > HOMA_MAX_MESSAGE_LENGTH` is false at exactly 1000000). Use
   `--workload 999999` to avoid stalls.

10. **TCP benchmarks blocked** — `epoll_client` and `epoll_server` crash with
    SIGABRT (exit 134). Likely a TCP eBPF path assertion similar to the Homa
    XDP_EGRESS bug. Metrics #13–21 are blocked pending TCP eBPF debugging.

11. **Multi-client Homa grant scaling** — Beyond ~200 concurrent RPCs, the Homa
    BPF grant mechanism collapses under `insert_grant_list → bpf_obj_new` memory
    pressure. This blocks metrics #3, #5–12 at full paper concurrency levels.
    Per-metric restart (kill micro_kernels + clean `/dev/shm/*` + restart)
    is mandatory between runs to avoid stale BPF state.

12. **`flexkvs_bench --time` not enforced** — `--time`, `--warmup`, `--cooldown`
    are stored in settings but never acted upon (no phase transition to DONE).
    Always wrap flexkvs_bench in `timeout N`. The `--time` value is informational only.

13. **`epoll_*` run indefinitely** — No loop count argument exists. `-l` is
    `max_buf_size` (default 4096), NOT a loop count. Always wrap in `timeout`.

14. **`ETRAN_NR_APP_THREADS` must match app threads** — The eTran library
    `pre_main` constructor registers this many threads with the microkernel.
    Must equal the application's actual thread count (e.g. `-t 4` → `ETRAN_NR_APP_THREADS=4`).
