# Metric 1: 32B RTT latency (echo, single stream)

- Number of nodes required: 2

Execution:
```bash
# Server (node0) - single-threaded, echoes 32B response (no --one-way):
sudo screen -dmS server bash -c 'cd /local/eTran/eTran/homa_app && exec env ETRAN_PROTO=homa ./cp_node server'

# Client (node1):
timeout 15 env ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 32

# Read P50 from client output: "RTT (us) P50 <p50>"
```

# Metric 2: 1MB throughput, back-to-back single stream

- Number of nodes required: 2

Execution:
```bash
# Server (node0) - single-threaded:
sudo screen -dmS server bash -c 'cd /local/eTran/eTran/homa_app && exec env ETRAN_PROTO=homa ./cp_node server'

# Client (node1) - single-stream back-to-back:
timeout 15 env ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 999999 \
  --one-way

# Read Gbps out from client output: "Clients: ... Gbps out ..."
```

# Metric 3: Multi-threaded server throughput, 500KB, 7 clients -> 1 server

- Number of nodes required: 8

Execution:
```bash
# Server (node0) - multi-threaded (4 ports = 4 server threads):
sudo screen -dmS server bash -c 'cd /local/eTran/eTran/homa_app && exec env ETRAN_PROTO=homa ./cp_node server --ports 4'

# 7 client nodes (node1-node7), each (start with 0.3s stagger):
timeout 30 env ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 500000 \
  --client-max 1 \
  --ports 1 \
  --server-ports 4 \
  --one-way

# Measure server-side Gbps in from server's screen log:
sudo screen -S server -X hardcopy /tmp/srv.log
grep 'Servers:' /tmp/srv.log | tail -3
```

# Metric 4: Multi-threaded client throughput, 500KB, 1 client -> 7 servers

- Number of nodes required: 8

Execution:
```bash
# 7 servers (node0-node6), each - run on every node:
sudo screen -dmS server bash -c 'cd /local/eTran/eTran/homa_app && exec env ETRAN_PROTO=homa ./cp_node server'

# 1 client (node7) with 7 ports matching 7 servers:
timeout 30 env ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 500000 \
  --client-max 1 \
  --ports 7 \
  --server-nodes 7 \
  --one-way

# Read client-side Gbps out from client output
```

# Metric 5: Client RPC rate, 32B, 7 clients -> 1 server

- Number of nodes required: 8

Execution:
```bash
# Server (node0) - 7 server threads:
sudo screen -dmS server bash -c 'cd /local/eTran/eTran/homa_app && exec env ETRAN_PROTO=homa ./cp_node server --ports 7'

# 7 client nodes (node1-node7), each:
timeout 30 env ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 32 \
  --client-max 64 \
  --ports 1 \
  --server-ports 7

# Read server-side aggregate Kops from server screen log
```

# Metric 6: Server RPC rate, 32B, 1 client -> 7 servers

- Number of nodes required: 8

Execution:
```bash
# 7 servers (node0-node6), each - run on every node:
sudo screen -dmS server bash -c 'cd /local/eTran/eTran/homa_app && exec env ETRAN_PROTO=homa ./cp_node server'

# Client (node7):
timeout 30 env ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 32 \
  --client-max 256 \
  --ports 7 \
  --server-nodes 7

# Read client-side Kops/sec (aggregate across all servers)
```

# Metrics 7-12: All-to-all tail latency, W2-W5 (each node is client + server)

- Number of nodes required: 10

Execution:
```bash
# Per-workload parameters:
#   W2: --workload w2  --gbps 3.2   RUN_SECONDS=5
#   W3: --workload w3  --gbps 14    RUN_SECONDS=10
#   W4: --workload w4  --gbps 20    RUN_SECONDS=20
#   W5: --workload w5  --gbps 20    RUN_SECONDS=30

# Repeat for each workload, on each node (node0-node9):
NODE_ID=0          # change per node
WL=w2              # w2, w3, w4, or w5
GBPS=3.2           # 3.2, 14, 20, or 20 (see above)
RUN_SECONDS=5      # 5, 10, 20, or 30 (see above)

(echo "client --first-server 0 --server-nodes 10 --workload ${WL} --client-max 100 --ports 4 --server-ports 4 --one-way --gbps ${GBPS} --both 2 --id ${NODE_ID}"; \
 sleep $((RUN_SECONDS + 5)); \
 echo "dump_times /tmp/rtts_node${NODE_ID}.txt"; \
 sleep 1; \
 echo "exit") \
| timeout $((RUN_SECONDS + 15)) env ETRAN_PROTO=homa ./cp_node 2>&1

# W4/W5 shortest-10% filtering (filter comment header lines with: grep -v '^#'):
# Interactive mode (headless alternative): start cp_node, issue commands via stdin
(echo "client --first-server 0 --server-nodes 10 ..."; sleep 30; \
  echo "dump_times /tmp/rtts.txt"; echo "exit") | env ETRAN_PROTO=homa ./cp_node

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

# Metric 13: TCP 1KB throughput, 64 outstanding, single-threaded

- Number of nodes required: 2

Execution:
```bash
# Server (node0):
sudo screen -dmS epoll_server bash -c 'cd /local/eTran/eTran/tcp_app && exec env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 LD_PRELOAD=../shared_lib/libetran.so ./epoll_server -i 192.168.6.1 -b 1024'

# Client (node1):
timeout 30 env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_client -i 192.168.6.1 -b 1024 -o 64 -f 1 -t 1

# Read "Throughput In/Out(<gbps>/<gbps> Gbps)(<kops> Kops)"
```

# Metric 14: TCP 2KB throughput, 64 outstanding, single-threaded

- Number of nodes required: 2

Execution:
```bash
# Server (node0):
sudo screen -dmS epoll_server bash -c 'cd /local/eTran/eTran/tcp_app && exec env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 LD_PRELOAD=../shared_lib/libetran.so ./epoll_server -i 192.168.6.1 -b 2048'

# Client (node1):
timeout 30 env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_client -i 192.168.6.1 -b 2048 -o 64 -f 1 -t 1

# Read "Throughput In/Out(<gbps>/<gbps> Gbps)(<kops> Kops)"
```

# Metric 15: TCP 1K persistent connections, 64B closed-loop

- Number of nodes required: 6

Execution:
```bash
# Server (node0) - 10 threads:
sudo screen -dmS epoll_server bash -c 'cd /local/eTran/eTran/tcp_app && exec env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=10 ETRAN_NR_NIC_QUEUES=10 LD_PRELOAD=../shared_lib/libetran.so ./epoll_server -i 192.168.6.1 -b 64 -t 10'

# Clients (5 nodes, node1-node5), each: 200 connections -> 1000 total:
timeout 30 env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=4 ETRAN_NR_NIC_QUEUES=4 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_client -i 192.168.6.1 -b 64 -f 200 -t 4 -o 1 -w 2

# Read aggregate Kops from client output
```

# Metrics 16-17: TCP short-lived connections (16 and 256 msg/conn, 1K concurrent flows)

- Number of nodes required: 6

Execution:
Not reproducible with the public eTran repo: epoll_client only supports persistent connections, and no short-lived connection benchmark binary is included.

# Metric 18: TCP KV throughput, 100K keys, Zipf s=0.9, 9:1 GET:SET

- Number of nodes required: 6

Execution:
```bash
# Server (node0) - 4 threads, 1 NIC queue:
sudo screen -dmS flexkvs_server bash -c 'cd /local/eTran/eTran/tcp_app && exec env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=4 ETRAN_NR_NIC_QUEUES=1 LD_PRELOAD=../shared_lib/libetran.so ./flexkvs_server default 4 1'

# Clients (5 nodes, node1-node5), each:
timeout 45 env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=4 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./flexkvs_bench \
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

# Read "TP: total=<mops> mops 50p=<us> ... 99.99p=<us>" every second
```

# Metric 19: TCP KV P50 latency, under-loaded

- Number of nodes required: 2

Execution:
```bash
# Server (node0) - same as metric 18:
sudo screen -dmS flexkvs_server bash -c 'cd /local/eTran/eTran/tcp_app && exec env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=4 ETRAN_NR_NIC_QUEUES=1 LD_PRELOAD=../shared_lib/libetran.so ./flexkvs_server default 4 1'

# Client (node1) - 1 thread, 1 connection, 1 pending:
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

# Read P50 from output ("50p=<us>")
```

# Metric 20: TCP KV P99 latency, under-loaded

- Number of nodes required: 2

Execution:
Same command as metric 19; read P99 from output ("99p=<us>").

# Metric 21: TCP total CPU cycles per request

- Number of nodes required: 2

Execution:
```bash
sudo perf stat -e cycles,instructions,context-switches,cpu-migrations,page-faults \
  timeout 20 env ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 \
  LD_PRELOAD=../shared_lib/libetran.so \
  ./epoll_client -i 192.168.6.1 -b 1024 -o 64 -f 1 -t 1

# kcycles/request = total_cycles / (avg_Kops x active_seconds)
```

# Metric 22: Homa total CPU cycles per request

- Number of nodes required: 2

Execution:
```bash
# NOTE: perf breaks eTran AF_XDP timing (inflates cycles/RPC via busy-poll stalls).
# Build perf first if needed: cd /lib/modules/6.6.0-eTran+/build/tools/perf
#   && sudo make -j$(nproc) NO_JEVENTS=1 NO_LIBTRACEEVENT=1 NO_LIBPFM4=1
sudo perf stat -e cycles,instructions,context-switches,cpu-migrations,page-faults \
  timeout 15 env ETRAN_PROTO=homa ./cp_node client \
  --first-server 0 \
  --workload 999999 \
  --one-way

# kcycles/request = total_cycles / (avg_Kops x active_seconds)
```

# Metric 3.1: XDP_EGRESS egress overhead (driver microbenchmark)

- Number of nodes required: 2

Execution:
```bash
# AF_XDP tx-only baseline:
sudo timeout 15 taskset -c 2 ./xdpsock -i ens1f1np1 -q 2 -t -s 64 -N -z

# + Empty XDP_EGRESS: load empty XDP_EGRESS BPF program, then run the same txonly command
# + OOO Completion: enable OOO completion buffer support (eTran kernel feature)
# + Array Lookup / Hashmap Lookup: load the specific BPF programs via the eTran kernel BPF loader
```

# Metric 3.2: XDP_GEN packet generation (driver microbenchmark)

- Number of nodes required: 2

Execution:
```bash
# l2fwd baseline:
sudo timeout 15 taskset -c 2 ./xdpsock -i ens1f1np1 -q 2 -l -N -z -B -b 256

# rx-drop + XDP_GEN (requires a BPF program using the XDP_GEN hook):
sudo timeout 15 taskset -c 3 ./xdpsock -i ens1f1np1 -q 3 -r -N -z
```
