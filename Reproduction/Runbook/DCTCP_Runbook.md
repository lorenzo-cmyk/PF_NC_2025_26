> Note: metric IDs follow `eTran_reproduction_metrics.md`. Metrics 1-6 are extra DCTCP baselines (no row in the metrics doc); metrics 13-15 and 18-21 are the DCTCP baselines for the eTran TCP metrics with the same IDs. Source-runbook local mapping: #7->13, #8->14, #13->15, #10->18, #11/12->19/20, #9->21.

# Metric 1: 32B RTT latency (echo, single stream)

- Number of nodes required: 2

Execution:
```bash
# Server (node0):
screen -dmS dctcp_server bash -c 'cd /local/HomaModule/util && exec ./cp_node server --protocol tcp --ports 1'

# Client (node1):
timeout 15 ./cp_node client --protocol tcp \
  --first-server 0 \
  --workload 32 \
  --client-max 1 \
  --ports 1

# Read P50 from client output: "RTT (us) P50 <p50>"
```

# Metric 2: 1MB throughput, single stream

- Number of nodes required: 2

Execution:
```bash
# Server (node0):
screen -dmS dctcp_server bash -c 'cd /local/HomaModule/util && exec ./cp_node server --protocol tcp --ports 1'

# Client (node1):
timeout 15 ./cp_node client --protocol tcp \
  --first-server 0 \
  --workload 999999 \
  --client-max 1 \
  --ports 1 \
  --one-way

# Read Gbps out from client output
```

# Metric 3: 500KB throughput, 7 clients -> 1 server

- Number of nodes required: 8

Execution:
```bash
# Server (node0) - 4 server ports:
screen -dmS dctcp_server bash -c 'cd /local/HomaModule/util && exec ./cp_node server --protocol tcp --ports 4'

# 7 clients (node1-node7), each (start with 0.3s stagger):
timeout 20 ./cp_node client --protocol tcp \
  --first-server 0 \
  --workload 500000 \
  --client-max 1 \
  --ports 1 \
  --server-ports 4 \
  --one-way

# Measure server-side Gbps in from server's screen log:
sudo screen -S dctcp_server -X hardcopy /tmp/srv.log
grep 'servers:' /tmp/srv.log | tail -3
```

# Metric 4: 500KB throughput, 1 client -> 7 servers

- Number of nodes required: 8

Execution:
```bash
# 7 servers (node0-node6), each - run on every node:
screen -dmS dctcp_server bash -c 'cd /local/HomaModule/util && exec ./cp_node server --protocol tcp --ports 1'

# Client (node7):
timeout 20 ./cp_node client --protocol tcp \
  --first-server 0 \
  --workload 500000 \
  --client-max 1 \
  --ports 7 \
  --server-nodes 7 \
  --one-way

# Read client-side Gbps out from client output
```

# Metric 5: 32B RPC rate, 7 clients -> 1 server

- Number of nodes required: 8

Execution:
```bash
# Server (node0) - 7 server ports for 32B:
screen -dmS dctcp_server bash -c 'cd /local/HomaModule/util && exec ./cp_node server --protocol tcp --ports 7'

# 7 clients (node1-node7), each:
timeout 15 ./cp_node client --protocol tcp \
  --first-server 0 \
  --workload 32 \
  --client-max 64 \
  --ports 1 \
  --server-ports 7

# Read server-side Kops/sec from server screen log
```

# Metric 6: 32B RPC rate, 1 client -> 7 servers

- Number of nodes required: 8

Execution:
```bash
# 7 servers (node0-node6), each - run on every node:
screen -dmS dctcp_server bash -c 'cd /local/HomaModule/util && exec ./cp_node server --protocol tcp --ports 1'

# Client (node7):
timeout 15 ./cp_node client --protocol tcp \
  --first-server 0 \
  --workload 32 \
  --client-max 256 \
  --ports 7 \
  --server-nodes 7

# Read client-side Kops/sec (aggregate across all servers)
```

# Metric 13: TCP 1KB throughput (epoll, streaming)

- Number of nodes required: 2

Execution:
```bash
# Server (node0):
screen -dmS dctcp_epoll bash -c 'cd /local/eTran/eTran/tcp_app && exec ./epoll_server -i 192.168.6.1 -b 1024'

# Client (node1):
timeout 15 stdbuf -oL bash -c 'cd /local/eTran/eTran/tcp_app && ./epoll_client -i 192.168.6.1 -b 1024 -o 64 -f 1 -t 1'

# Read "Throughput In/Out(<gbps>/<gbps> Gbps)(<kops> Kops)"
```

# Metric 14: TCP 2KB throughput (epoll, streaming)

- Number of nodes required: 2

Execution:
```bash
# Server (node0):
screen -dmS dctcp_epoll bash -c 'cd /local/eTran/eTran/tcp_app && exec ./epoll_server -i 192.168.6.1 -b 2048'

# Client (node1):
timeout 15 stdbuf -oL bash -c 'cd /local/eTran/eTran/tcp_app && ./epoll_client -i 192.168.6.1 -b 2048 -o 64 -f 1 -t 1'

# Read "Throughput In/Out(<gbps>/<gbps> Gbps)(<kops> Kops)"
```

# Metric 15: TCP 1K persistent connections, 64B closed-loop (epoll, plain TCP)

- Number of nodes required: 6

Execution:
```bash
# Server (node0) - 10 threads, 64B request:
screen -dmS epoll_server bash -c 'cd /local/eTran/eTran/tcp_app && exec ./epoll_server -i 192.168.6.1 -b 64 -t 10'

# Clients (5 nodes, node1-node5), each - 200 connections, 4 threads, 1 outstanding:
cd /local/eTran/eTran/tcp_app && script -q -c 'timeout 20 ./epoll_client -i 192.168.6.1 -b 64 -f 200 -t 4 -o 1 -w 2' /dev/null

# Read aggregate Kops from client output
```

# Metric 18: TCP KV throughput (flexkvs, plain TCP)

- Number of nodes required: 6

Execution:
```bash
# Server (node0) - 4 threads, 1 NIC queue (no LD_PRELOAD, no env vars):
screen -dmS flexkvs_server bash -c 'cd /local/eTran/eTran/tcp_app && exec ./flexkvs_server default 4 1'

# Clients (5 nodes, node1-node5), each - no LD_PRELOAD, no ETRAN_PROTO:
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

# Read "TP: total=<mops> mops ..." every second
```

# Metrics 19-20: TCP KV P50/P99 latency (flexkvs, plain TCP, under-loaded)

- Number of nodes required: 2

Execution:
```bash
# Server (node0) - same as metric 18:
screen -dmS flexkvs_server bash -c 'cd /local/eTran/eTran/tcp_app && exec ./flexkvs_server default 4 1'

# Client (node1) - single thread, single connection, single pending:
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

# Read P50 (metric 19) / P99 (metric 20) from output
```

# Metric 21: TCP CPU cycles per request (epoll, 1KB, client)

- Number of nodes required: 2

Execution:
```bash
sudo perf stat -e cycles,instructions \
  timeout 15 stdbuf -oL bash -c 'cd /local/eTran/eTran/tcp_app && ./epoll_client -i 192.168.6.1 -b 1024 -o 64 -f 1 -t 1'

# kcycles/request = total_cycles / (avg_Kops x active_seconds)
```
