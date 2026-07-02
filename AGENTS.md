# eTran Benchmark Session Notes

## Ansible evaluation pipeline (run before every benchmark session)

```bash
# Always run: ARP, /etc/hosts, NIC coalescing, flow control
.venv/bin/ansible-playbook playbooks/eTran/evaluation/01-network-prep.yml

# Optional: IRQ affinity (queue count + core pinning)
.venv/bin/ansible-playbook playbooks/eTran/evaluation/02-irq-affinity.yml

# Optional: MTU (e.g. mtu=9000)
.venv/bin/ansible-playbook playbooks/eTran/evaluation/03-mtu.yml --extra-vars 'mtu=9000'

# Verify everything
.venv/bin/ansible-playbook playbooks/eTran/evaluation/04-verify-network.yml
```

Reboot clears ARP table and /etc/hosts entries, so run `01-network-prep.yml` after each reboot.

## Critical procedure for running benchmarks

Every metric requires:
1. Kill micro_kernel + cp_node on all involved nodes
2. Clean `/dev/shm/BufferPool_* /dev/shm/UMEM_* /dev/shm/LRPC_*`
3. Start micro_kernel with `-q 10` (NIC has 10 combined queues)
4. Start server
5. Run client with `timeout N env ETRAN_PROTO=homa ./cp_node client ...`

Headless invocation:
```bash
ssh node1 "cd /local/eTran/eTran/homa_app && timeout 10 env ETRAN_PROTO=homa ./cp_node client ... 2>&1"
```
Use `env VAR=val` (NOT `timeout VAR=val command`) — timeout doesn't parse env prefixes.

## BPF XDP_EGRESS patch (must be re-applied if source is re-cloned)
File: `micro_kernel/eBPF/homa/main.c` lines 235-248
Fix: Move `c->type != DATA` check before `data_header` bounds check,
     route non-DATA packets through `xmit_packet()` instead of dropping.
After patching: `touch micro_kernel/eBPF/homa/main.c && make -j$(nproc)`

## Correct metric invocations
- Metrics 1: NO `--one-way` (32B echo per paper §4.2)
- Metrics 2-4, 7-12, 22: YES `--one-way` (large messages need small response)
- Metrics 2: `--client-max 1 --ports 1` (single-stream back-to-back)
- Metric 3: server default ports, clients `--ports 1 --client-max 64`
- Metric 4: servers default ports, client `--ports 7 --client-max 64`
- Metric 1-2: 2 nodes only

## Known issues
- `--workload 1000000` stalls — use `999999` (HOMA_MAX_MESSAGE_LENGTH off-by-one)
- Server `--ports > 4` crashes buffer pool (`nr_slabs_avail` assertion)
- Multi-client (>200 concurrent RPCs) overwhelms BPF grant mechanism
- TCP benchmarks (epoll_*) crash with SIGABRT — unresolved
- SMT ON degrades AF_XDP performance

## What NOT to do
- Never use `--queues` on cp_node client — kills throughput (e.g. 1045→86 Kops)
- Never use `-b` (busy-poll) on micro_kernel — breaks Homa benchmark
- Never double `umem_num_frames` — doesn't help, causes overhead
- Never skip shm cleanup between metrics — causes silent failures

## Multi-node orchestration
Start clients sequentially (0.3s stagger) to avoid overwhelming the server:
```bash
for i in 1 2 3 4 5 6 7; do
  ssh node$i "nohup bash -c '...timeout 15 env ETRAN_PROTO=homa ./cp_node client ...' </dev/null >/tmp/client.log 2>&1 &" &
  sleep 0.3
done
```

## Hardware
- CloudLab xl170, 10-core E5-2640v4 × 1 socket, Mellanox ConnectX-4 Lx 25G
- Paper used 2 sockets (20 cores) + ConnectX-4 25G on same node type
- NIC: `ens1f1np1` (PCI 0000:03:00.1), NUMA node 0
- SMT=off: 10 logical cores, NIC has 10 combined queues → `-q 10`
- C-states=off (`intel_idle.max_cstate=0`), ASPM=off — required for sub-15µs latency metrics

## Ansible playbook structure
- `playbooks/eTran/setup/` — one-time: system deps, kernel build, install eTran
- `playbooks/eTran/tuning/` — one-time (persists reboot): SMT off, mitigations off, C-states off, ASPM off, tuned
- `playbooks/eTran/evaluation/` — per-session: ARP, hosts, NIC tuning, IRQ affinity, MTU, verify

## Ansible inventory
- `@server` = node0, `@clients` = node1–node9
- Paper PDF: `nsdi25-chen-zhongjie.pdf` in repo root

## Key source files
- `common/xskbp/xsk_buffer_pool.h` — buffer pool constants (umem_num_frames, buffers_per_slab)
- `micro_kernel/eBPF/homa/main.c:240` — XDP_EGRESS grant drop bug
- `common/tran_def/homa.h:8` — HOMA_MAX_MESSAGE_LENGTH = 1000000
- `micro_kernel/micro_kernel.cc:51` — default queues = 20
- `homa_app/cp_node.cc:1616` — default workload = "100"
