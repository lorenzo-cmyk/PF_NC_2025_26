# Metric 1: 32B RTT latency (echo, single stream)

- Number of nodes required: 2

Execution:
```bash
# Server (node0) - single-threaded:
sudo screen -dmS homa_server bash -c 'cd /local/HomaModule/util && exec ./cp_node server'

# Client (node1):
timeout 15 ./cp_node client \
  --first-server 0 \
  --workload 32

# Read P50 from client output: "RTT (us) P50 <p50>"
```

# Metric 2: 1MB throughput, single stream

- Number of nodes required: 2

Execution:
```bash
# Server (node0) - single-threaded:
sudo screen -dmS homa_server bash -c 'cd /local/HomaModule/util && exec ./cp_node server'

# Client (node1):
timeout 15 ./cp_node client \
  --first-server 0 \
  --workload 999999 \
  --one-way

# Read Gbps out from client output
```

# Metric 3: 500KB throughput, 7 clients -> 1 server

- Number of nodes required: 8

Execution:
```bash
# Server (node0) - 4 server ports:
sudo screen -dmS homa_server bash -c 'cd /local/HomaModule/util && exec ./cp_node server --ports 4'

# 7 clients (node1-node7), each (start with 0.3s stagger):
timeout 30 ./cp_node client \
  --first-server 0 \
  --workload 500000 \
  --client-max 1 \
  --ports 1 \
  --server-ports 4 \
  --one-way

# Measure server-side Gbps in from server's screen log:
sudo screen -S homa_server -X hardcopy /tmp/srv.log
grep 'servers:' /tmp/srv.log | tail -3
```

# Metric 4: 500KB throughput, 1 client -> 7 servers

- Number of nodes required: 8

Execution:
```bash
# 7 servers (node0-node6), each - run on every node:
sudo screen -dmS homa_server bash -c 'cd /local/HomaModule/util && exec ./cp_node server'

# Client (node7):
timeout 30 ./cp_node client \
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
# Server (node0) - 7 server ports:
sudo screen -dmS homa_server bash -c 'cd /local/HomaModule/util && exec ./cp_node server --ports 7'

# 7 clients (node1-node7), each:
timeout 30 ./cp_node client \
  --first-server 0 \
  --workload 32 \
  --client-max 64 \
  --ports 1 \
  --server-ports 7

# Read server-side aggregate Kops from server screen log
```

# Metric 6: 32B RPC rate, 1 client -> 7 servers

- Number of nodes required: 8

Execution:
```bash
# 7 servers (node0-node6), each - run on every node:
sudo screen -dmS homa_server bash -c 'cd /local/HomaModule/util && exec ./cp_node server'

# Client (node7):
timeout 30 ./cp_node client \
  --first-server 0 \
  --workload 32 \
  --client-max 256 \
  --ports 7 \
  --server-nodes 7

# Read client-side Kops/sec (aggregate across all servers)
```

# Metrics 7-12: All-to-all tail latency (W2-W5)

- Number of nodes required: 10

Execution:
```bash
# Per-workload parameters:
#   W2: --workload w2  --gbps 3.2   sleep 10  timeout 20
#   W3: --workload w3  --gbps 14    sleep 15  timeout 25
#   W4: --workload w4  --gbps 20    sleep 25  timeout 35
#   W5: --workload w5  --gbps 20    sleep 35  timeout 45

# 1. Kill stale cp_node, start servers on all nodes (4 ports each):
for n in 0 1 2 3 4 5 6 7 8 9; do
  ssh node${n} "for p in \$(pgrep -x cp_node); do sudo kill -9 \$p; done; \
    sudo screen -dmS homa_server bash -c \
    'cd /local/HomaModule/util && exec ./cp_node server --ports 4'"
done
sleep 4

# 2. Launch clients simultaneously via pipe (captures dump_times).
#    Use the per-workload --workload/--gbps/sleep/timeout from the table above:
WL=w2; GBPS=3.2; SLEEP=10; TIMEOUT=20
for n in 0 1 2 3 4 5 6 7 8 9; do
  (echo "client --first-server 0 --server-nodes 10 --workload ${WL} --gbps ${GBPS} --client-max 100 --ports 4 --server-ports 4 --one-way"; \
   sleep ${SLEEP}; echo "dump_times /tmp/rtts_${WL}_node${n}.txt"; sleep 1; echo "exit") \
  | timeout ${TIMEOUT} ssh node${n} "cd /local/HomaModule/util && exec ./cp_node 2>&1" \
  > /tmp/${WL}_node${n}.out &
done
wait

# 3. Collect dump_times from each node:
for n in 0 1 2 3 4 5 6 7 8 9; do
  scp node${n}:/tmp/rtts_${WL}_node${n}.txt /tmp/
done

# Filter comment header lines with: grep -v '^#'
```

# Metric 22: CPU cycles per request (32B RPC rate)

- Number of nodes required: 2

Execution:
```bash
sudo perf stat -e cycles,instructions,context-switches,cpu-migrations,page-faults \
  timeout 20 ./cp_node client \
  --first-server 0 \
  --workload 32 \
  --client-max 64 \
  --ports 1 \
  --server-ports 7

# kcycles/request = total_cycles / (avg_Kops x active_seconds)
```
