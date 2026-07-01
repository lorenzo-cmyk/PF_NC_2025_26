# eTran Benchmark Runbook — Exact Commands per Metric

Cross-references each metric from `eTran_reproduction_metrics_relevant.md`
against source code in `https://github.com/eTran-NSDI25/eTran`.

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

4. **Interface name** is hardcoded as `ens1f1np1` (`IF_NAME` macro in cp_node.cc:54,
   micro_kernel.cc, xdpsock.c). Recompile if your NIC differs.

6. **Headless execution** — run benchmarks non-interactively via ssh:

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

---

## Table 1 — Primary eTran Metrics

### 1. eTran - Homa | Median RTT latency, 32B requests, single client | 11.8 µs | 2-Node

```bash
# Microkernel (both nodes) — MUST use -q 10
# (NIC has 10 combined queues; default=20 crashes with SMT off)
sudo ./micro_kernel -i ens1f1np1 -q 10

# Server (node0):
ETRAN_PROTO=homa ./cp_node server

# Client (node1):
ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 32 \
  --client-max 1 \
  --ports 1 \
  --server-nodes 1 \
  --server-ports 1 \
  --one-way
```
Output every 1s: `RTT (us) P50 ... P99 ... P99.9 ...`

> **Measured**: 75 Kops/sec, P50 12.2 µs, P99 27.5 µs, P99.9 39 µs (paper: 11.8 µs).

### 2. eTran - Homa | Throughput, 1MB requests, back-to-back | 17.7 Gbps | 2-Node

```bash
# Server (node0):
ETRAN_PROTO=homa ./cp_node server

# Client (node1) — single-stream back-to-back:
ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 1000000 \
  --client-max 1 \
  --ports 1 \
  --server-nodes 1 \
  --server-ports 1 \
  --one-way \
  --gbps 0
```
Output: `Clients: ... Gbps out ...` (line 1528 of cp_node.cc)

> **Measured**: 17.06 Gbps @ 2.13 Kops/sec, P50 435 µs, P99 617 µs, P99.9 740 µs
> (paper: 17.7 Gbps).
>
> **Notes**: `--one-way` is required — without it, the server echoes the 1MB
> response which doubles the grant-path load. `--client-max 1 --ports 1` is the
> correct "back-to-back" single-stream configuration; the paper's 17.7 Gbps is
> single-stream throughput, not concurrent saturation.
> If `--workload 1000000` stalls at startup (few initial seconds of
> `Homa timer: Abort RPC` before stabilizing), use `999999` to avoid
> `HOMA_MAX_MESSAGE_LENGTH` off-by-one in the grant scheduler.

### 3. eTran - Homa | Multi-threaded server throughput, 500KB, 7 clients | 23.0 Gbps | Medium

```bash
# Server (node0): uses 7 port receivers
ETRAN_PROTO=homa ./cp_node server --ports 7

# 7 client nodes each running:
ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 524288 \
  --client-max 100 \
  --ports 7 \
  --server-nodes 1 \
  --server-ports 7 \
  --one-way \
  --gbps 0
```
Measure server-side Gbps in (output line: `Servers: ... Gbps in ...`).

### 4. eTran - Homa | Multi-threaded client throughput, 500KB, 7 servers | 22.7 Gbps | Medium

```bash
# 7 server nodes, each:
ETRAN_PROTO=homa ./cp_node server --ports 1

# 1 client with 7 ports:
ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 524288 \
  --client-max 100 \
  --ports 7 \
  --server-nodes 7 \
  --server-ports 1 \
  --one-way \
  --gbps 0
```
Measure client-side Gbps out.

### 5. eTran - Homa | Client RPC rate, 32B | 2.9 Mops | Medium

```bash
# Server (node0):
ETRAN_PROTO=homa ./cp_node server

# Client (node1) — maximize Kops/sec via high client-max:
ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 32 \
  --client-max 256 \
  --ports 8 \
  --server-nodes 1 \
  --server-ports 1 \
  --one-way \
  --gbps 0
```
Output: `Clients: ... Kops/sec ...`

> **Measured**: 1,045 Kops/sec, P50 225 µs (paper: 2.9 Mops).

### 6. eTran - Homa | Server RPC rate, 32B | 3.3 Mops | Medium

```bash
# Server (node0):
ETRAN_PROTO=homa ./cp_node server --ports 8

# Client (node1):
ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 32 \
  --client-max 256 \
  --ports 8 \
  --server-nodes 1 \
  --server-ports 8 \
  --one-way \
  --gbps 0
```
Output: `Servers: ... Kops/sec ...`

> **Measured**: 658 Kops/sec server-side (paper: 3.3 Mops).

### 7–12. eTran - Homa | P50/P99 tail latency slowdown, W2–W5 | 10-Node Cluster

Workloads defined in `/local/eTran/eTran/homa_app/dist.cc`: `w2`, `w3`, `w4`, `w5`.
Each workload is a heavy-tailed distribution of message sizes.

```bash
# Repeat for each workload (w2, w3, w4, w5) twice:
#   once with eTran kernel booted,
#   once with stock Linux kernel booted (for Linux-Homa baseline).

# Server (node0):
ETRAN_PROTO=homa ./cp_node server --ports 8

# Clients (nodes 1-9), each:
ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload w2 \
  --client-max 100 \
  --ports 4 \
  --server-nodes 1 \
  --server-ports 8 \
  --one-way \
  --gbps 20
```
Record P50/P99/P99.9 RTT (µs) from 1s stats output (`client_stats`, line 1528).
Slowdown = `eTran_RTT / Linux_RTT`.
For W4/W5: also filter to shortest 10% of RPCs (use `dump_times` command
before stopping the client, then post-process).
Record P50/P99/P99.9 RTT (µs) from 1s stats output (`client_stats`, line 1528).
Slowdown = `eTran_RTT / Linux_RTT`.
For W4/W5: also filter to shortest 10% of RPCs (use `dump_times` command
before stopping the client, then post-process).

**IMPORTANT**: The paper's W4/W5 shortest-10% filtering requires collecting
individual RTT samples. Use `./cp_node dump_times /tmp/rtts.txt` before
stopping the client, then sort and take lowest decile.

### 13. eTran - TCP | 1KB throughput, 64 outstanding, single-threaded | 4.8x Linux | 2-Node

```bash
# Server:
ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_server -i 192.168.6.1 -b 1024 -l 100000

# Client:
ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_client -i 192.168.6.1 -b 1024 -o 64 -f 1 -t 1 -l 100000
```
Output: `epoll_client` prints `Gbps out` every second.

### 14. eTran - TCP | 2KB throughput, 64 outstanding, single-threaded | 0.87x TAS | Medium

```bash
# Server:
ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_server -i 192.168.6.1 -b 2048 -l 100000

# Client:
ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_client -i 192.168.6.1 -b 2048 -o 64 -f 1 -t 1 -l 100000
```

### 15. eTran - TCP | 1K persistent connections, 64B requests | 2.26x Linux | 6-Node

```bash
# Server (1 node):
ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=10 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_server -i 192.168.6.1 -b 64 -t 10 -l 100000

# Clients (5 nodes), each: 200 connections → 1000 total:
ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=4 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_client -i 192.168.6.1 -b 64 -f 200 -t 4 -o 1 -l 100000 -w 2
```

### 16. eTran - TCP | Short-lived 16 msg/conn, 1K concurrent | 42.7x Linux | 6-Node

**⚠️ CAVEAT**: `epoll_client` only supports **persistent** connections. The public
eTran repo does not include a short-lived TCP connection benchmark binary.
This metric may require:
- A custom benchmark that opens/closes connections and sends 16 messages each, or
- It was measured using the `cp_node` (Homa) as the "short-lived connection"
  test (since Homa is connectionless and each RPC is like a short-lived
  connection).

**If using cp_node as proxy for short-lived connections:**
```bash
# Server:
ETRAN_PROTO=homa ./cp_node server

# Client — send 16 messages, measure rate:
ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 64 \
  --client-max 1 \
  --ports 16 \
  --server-nodes 1 \
  --server-ports 1 \
  --gbps 0
```

### 17. eTran - TCP | Short-lived 256 msg/conn, 1K concurrent | 5.4x Linux | Medium

**⚠️ Same caveat as #16.**

### 18. eTran - TCP | KV throughput, 100K keys, Zipf s=0.9, 9:1 GET:SET | 2.4~4.8x Linux | 6-Node

```bash
# Server (1 node) — CONFIG can be "default":
ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./flexkvs_server default 4 1

# Clients (5 nodes), each:
ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
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
Output: `flexkvs_bench` prints Mops/sec, P50/P90/P95/P99/P99.9/P99.99 µs every second.

### 19. eTran - TCP | KV P50 latency, under-loaded | 17.2 µs | 6-Node

```bash
# Same as #18 but with just 1 client thread, 1 connection, 1 pending:
ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
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
Read P50 µs from output.

### 20. eTran - TCP | KV P99 latency, under-loaded | 27.5 µs | 6-Node

Same command as #19. Read P99 µs from output.

### 21. eTran - TCP | Total CPU cycles per request | 4.37 kcycles | 2-Node CPU Profiling

```bash
# Run TCP throughput test (#13) under perf:
perf stat -e cycles,instructions,LLC-load-misses,LLC-store-misses \
  -e context-switches,cpu-migrations,page-faults \
  ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_client -i 192.168.6.1 -b 1024 -o 64 -f 1 -t 1 -l 100000

# Calculate kcycles/request = (total cycles) / (total requests)

# For per-component breakdown (matching Table 5), use perf record + report:
perf record -g -F 99 \
  ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_client -i 192.168.6.1 -b 1024 -o 64 -f 1 -t 1 -l 100000
perf report --stdio --sort=comm,dso,symbol,dso_from,symbol_from
# Map symbols to the categories in Table 5 (Application, Socket/RPC, Data Copy,
# Sk_buff, TCP/Homa+IP, Lock/Unlock, NIC Driver, Memory Mgmt, Scheduling, Other).
```

### 22. eTran - Homa | Total CPU cycles per request | 5.48 kcycles | 2-Node CPU Profiling

```bash
# Run Homa throughput test (#2) under perf:
perf stat -e cycles,instructions \
  ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 1000000 \
  --client-max 1 \
  --ports 1 \
  --server-nodes 1 \
  --server-ports 1 \
  --one-way \
  --gbps 0
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
`/local/eTran/bench-afxdp/`.

### AF_XDP tx-only baseline | 11.55 Mpps
```bash
sudo taskset -c 2 ./xdpsock -i ens1f1np1 -q 2 -t -s 64 -N -z
```

### + Empty XDP_EGRESS | 10.79 Mpps (6.6% loss)
**⚠️** Requires eTran kernel BPF program with empty `XDP_EGRESS` hook loaded:
```bash
# Load empty XDP_EGRESS BPF program (depends on eTran kernel config)
# Then run the same txonly benchmark:
sudo taskset -c 2 ./xdpsock -i ens1f1np1 -q 2 -t -s 64 -N -z
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
sudo taskset -c 2 ./xdpsock -i ens1f1np1 -q 2 -l -N -z -B -b 256
```

### rx-drop + XDP_GEN | 6.03 Mpps overall, 1.35 active cores | 2-Node
**⚠️** `XDP_GEN` is an eTran kernel hook — requires a BPF program that generates
ACK/credit packets using the `XDP_GEN` hook. The rx-drop side:
```bash
sudo taskset -c 3 ./xdpsock -i ens1f1np1 -q 3 -r -N -z
```

---

## Quick-Reference: Key Source Code Lines in `/tmp/eTran_repo`

| File                                    | Key Lines                                                                 |
|:----------------------------------------|:--------------------------------------------------------------------------|
| `eTran/homa_app/cp_node.cc`             | L54 `IF_NAME`, L78 `workload`, L70 `net_gbps`, L72 `one_way`, L79 `unloaded`, L1528 client stats print, L1457 server stats print |
| `eTran/homa_app/dist.cc`              | `w1`-`w5` distribution arrays, integer→fixed-size logic (L45)              |
| `eTran/tcp_app/epoll_client.cc`        | L63-75 `parse_args`, output Gbps/Kops every 1s                            |
| `eTran/tcp_app/lat_client.cc`          | L170-230: 500K ping-pongs, sorted P50/P99/P99.9 output                    |
| `eTran/tcp_app/flexkvs_bench.cc`       | L630-680 `parse_settings()`, L780-820 stats output with P50-99.99          |
| `eTran/tcp_app/flexkvs/workload.c`     | L105-118 `distribute_zipf(s)`                                             |
| `eTran/micro_kernel/micro_kernel.cc`    | L51 `opt_num_queues=20` default, L106-121 `-q` flag, L70-90 `parse_args`, `-i` iface, `-b` busy-poll |
| `eTran/lib/eTran_common.cc`            | L594-649 `pre_main` — reads `ETRAN_PROTO`, `ETRAN_NR_APP_THREADS`, `ETRAN_NR_NIC_QUEUES` |
| `bench-afxdp/xdpsock.c`                | L120-250 `parse_args`, `-r`/`-t`/`-l` modes, `-s` pkt size, `-b` batch    |

---

## Known Limitations

1. **Short-lived TCP connections (metrics #16–17)** — Not supported by any
   binary in the public repo. The `epoll_client` only creates persistent
   connections. A custom benchmark is needed.

2. **Interface name** — Hardcoded as `ens1f1np1` in cp_node.cc:54,
   micro_kernel.cc, and xdpsock.c. For CloudLab xl170 nodes (Mellanox
   ConnectX-5), check `ip link` and recompile if different.

3. **CPU cycles breakdown (Table 5)** — Requires hardware PMU counters
   and careful kernel symbol mapping. Not automatically categorized.

4. **XDP_EGRESS / XDP_GEN benchmarks (Tables 3–4)** — These test eTran's
   new eBPF hooks. BPF programs implementing the tested features are needed
   but not found as standalone build targets in the repo. They may be embedded
   in the microkernel/eTran library build.

5. **6-Node / 10-Node multi-node tests** — Require synchronized start
   across nodes. The `--wait` / `--both` flags provide some coordination,
   but a startup script (e.g., Ansible `--serial`) is recommended.

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

8. **`--one-way` required for large Homa messages** — Without `--one-way`,
   the server echoes the full message as a response, doubling the grant-path
   load and hitting the `HOMA_MAX_MESSAGE_LENGTH` boundary in both directions.
   All large-message benchmarks (metrics #2–4, #7–12, #22) use `--one-way`.

9. **`HOMA_MAX_MESSAGE_LENGTH` off-by-one** — `HOMA_MAX_MESSAGE_LENGTH = 1000000`
   (`common/tran_def/homa.h:8`). If `--workload 1000000` stalls at startup (few
   initial seconds of `Homa timer: Abort RPC` before stabilizing), use `--workload
   999999` to avoid the exact boundary.
