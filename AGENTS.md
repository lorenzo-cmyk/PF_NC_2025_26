# eTran Benchmark Session Notes

## Ansible evaluation pipeline (must run after EVERY reboot)

Reboot resets: ARP table, /etc/hosts, NIC coalescing, flow control, queue count, IRQ affinity, MTU.

```bash
# Required after every reboot:
.venv/bin/ansible-playbook playbooks/eTran/evaluation/01-network-prep.yml
.venv/bin/ansible-playbook playbooks/eTran/evaluation/02-irq-affinity.yml
.venv/bin/ansible-playbook playbooks/eTran/evaluation/04-verify-network.yml

# Optional: MTU (default 1500, skip for standard runs)
# .venv/bin/ansible-playbook playbooks/eTran/evaluation/03-mtu.yml --extra-vars 'mtu=9000'
```

**IRQ affinity (02) details**: There are 2 mlx5 devices on these nodes
(`0000:07:00.0` and `0000:03:00.1`). The 02-irq-affinity.yml playbook uses
`grep mlx5_comp /proc/interrupts` which picks up IRQs from BOTH devices.
The sort-order may interleave them. Always verify the pinning targets the
correct PCI slot for `ens1f1np1` (`0000:03:00.1`). After running, check:
```bash
for irq in $(grep "mlx5_comp@pci:0000:03:00.1" /proc/interrupts | sed 's/^ *//' | cut -d: -f1 | sort -n | head -10); do
  echo -n "IRQ $irq -> "; cat /proc/irq/$irq/smp_affinity_list
done
```

## Critical procedure for running benchmarks

Every metric run follows this exact sequence:

```bash
# 1. Kill everything on all involved nodes
for n in node0 node1 node2 ...; do
  ssh $n "sudo pkill -9 cp_node; sudo pkill -9 micro_kernel; \
    sudo screen -S server -X quit 2>/dev/null; \
    sudo screen -S micro_kernel -X quit 2>/dev/null"
done

# 2. Clean shared memory
for n in node0 node1 node2 ...; do
  ssh $n "sudo rm -f /dev/shm/BufferPool_* /dev/shm/UMEM_* /dev/shm/LRPC_*"
done

# 3. Start micro_kernel on all involved nodes with screen (no timeout)
for n in node0 node1 node2 ...; do
  ssh $n "sudo screen -dmS micro_kernel bash -c \
    'cd /local/eTran/eTran/micro_kernel && exec ./micro_kernel -i ens1f1np1 -q 10'"
done
sleep 5

# 4. Start server on node0 with screen (no timeout — stays alive for multiple runs)
ssh node0 "sudo screen -dmS server bash -c \
  'cd /local/eTran/eTran/homa_app && exec env ETRAN_PROTO=homa ./cp_node server'"
sleep 3

# 5. Run clients with timeout (they exit when done)
for i in 1 2 3 ...; do
  timeout 30 ssh node$i "cd /local/eTran/eTran/homa_app && timeout 28 \
    env ETRAN_PROTO=homa ./cp_node client ... 2>&1" > /tmp/client_$i.out &
  sleep 0.3
done
wait

# 6. Collect results from saved client logs and server screen log
for i in 1 2 3 ...; do grep "Clients:" /tmp/client_$i.out | tail -1; done
ssh node0 "sudo screen -S server -X hardcopy /tmp/srv.log; \
  grep 'Servers:' /tmp/srv.log | tail -3"
```

### Key principles
- **micro_kernel** and **server** run in `screen` with NO timeout — they persist
  across runs. Only restart them if switching metrics or hitting stale state.
- **clients** always use `timeout N` — they're ephemeral.
- Use `env VAR=val` (NOT `timeout VAR=val command`) — timeout doesn't parse env prefixes.
- Start clients sequentially with 0.3s stagger to avoid overwhelming the server
  (especially for multi-client metrics like #3, #5).

### Controlling screen sessions
```bash
# Check micro_kernel is up
ssh nodeN "sudo screen -ls micro_kernel; sudo pgrep -a micro_kernel"

# Collect server output without killing it
ssh node0 "sudo screen -S server -X hardcopy /tmp/srv.log; cat /tmp/srv.log"

# Kill when done
ssh nodeN "sudo screen -S micro_kernel -X quit; sudo pkill -9 micro_kernel"
ssh node0 "sudo screen -S server -X quit; sudo pkill -9 cp_node"
```

### Reading server stats from screen
The server's screen buffer may truncate old output. To get the latest lines:
```bash
ssh node0 "sudo screen -S server -X hardcopy /tmp/srv.log; \
  grep 'Servers:' /tmp/srv.log | tail -5"
```
The `hardcopy` command dumps the screen's scrollback buffer to a file.
If too old, the server has scrolled them out — check during/right after the run.

## BPF XDP_EGRESS patch (must be re-applied if source is re-cloned)
File: `micro_kernel/eBPF/homa/main.c` lines 235-248
Fix: Move `c->type != DATA` check before `data_header` bounds check,
     route non-DATA packets through `xmit_packet()` instead of dropping.
After patching: `touch micro_kernel/eBPF/homa/main.c && make -j$(nproc)`

## Correct metric invocations
- Metrics 1: NO `--one-way` (32B echo per paper §4.2)
- Metrics 2-4, 7-12, 22: YES `--one-way` (large messages need small response)
- Metrics 2: `--client-max 1 --ports 1` (single-stream back-to-back)
- Metric 3: server `--ports 4`, clients `--ports 1 --client-max 1` (sweet spot for 10-core)
- Metric 4: servers default ports, client `--ports 7 --client-max 1` (sweet spot for 10-core)
- Metric 1-2: 2 nodes only
- Metric 5: server `--ports 4`, clients `--ports 1 --client-max 64` (best: 962 Kops)
- Metric 6: client `--ports 7 --client-max 256` (works with fresh state, 1100 Kops)

## Known issues
- `--workload 1000000` stalls — use `999999` (HOMA_MAX_MESSAGE_LENGTH off-by-one)
- Server `--ports > 4` crashes buffer pool (`nr_slabs_avail` assertion)
- Multi-client (>200 concurrent RPCs) overwhelms BPF grant mechanism
- TCP benchmarks (epoll_*) crash with SIGABRT — unresolved
- **SMT ON breaks eTran entirely** — AF_XDP busy-polling gets 0 completions
  regardless of queue count or IRQ pinning. Paper also notes SMT degrades AF_XDP.
  SMT=off (via `nosmt` in GRUB) is mandatory.
- `perf` breaks eTran AF_XDP timing (sampling interrupts cause RPC stalls)
- All-to-all `--both` segfaults on exit (shared memory cleanup race)
- 10-core SMT=off limits throughput to ~50-60% of paper (paper had 20 cores)

## What NOT to do
- Never use `--queues` on cp_node client — kills throughput (e.g. 1045→86 Kops)
- Never use `-b` (busy-poll) on micro_kernel — breaks Homa benchmark
- Never double `umem_num_frames` — doesn't help, causes overhead
- Never skip shm cleanup between metrics — causes silent failures
- Never use `nohup ... </dev/null` for micro_kernel — monitor thread exits on stdin EOF.
  Use `screen -dmS` instead (provides a proper pty).
- Never use `timeout` on the server or micro_kernel — wrap them in `screen` instead.
- Never assume `grep mlx5_comp` targets the right PCI device — there are 2 mlx5 NICs.
  Always verify the PCI slot: `0000:03:00.1` for `ens1f1np1`.

## Multi-node orchestration
```bash
for i in 1 2 3 4 5 6 7; do
  timeout 30 ssh node$i "cd /local/eTran/eTran/homa_app && timeout 28 \
    env ETRAN_PROTO=homa ./cp_node client ... 2>&1" > /tmp/m_$i.out &
  sleep 0.3
done
wait
```

## Hardware
- CloudLab xl170, 10-core E5-2640v4 × 1 socket, Mellanox ConnectX-4 Lx 25G
- Paper used 2 sockets (20 cores) + ConnectX-4 25G on same node type
- NIC: `ens1f1np1` (PCI 0000:03:00.1), NUMA node 0
- Second mlx5 device at PCI 0000:07:00.0 (unused, but its IRQs appear in
  `/proc/interrupts` and confuse `grep mlx5_comp`)
- SMT=off: 10 logical cores, NIC has 10 combined queues → `-q 10`
- C-states=off (`intel_idle.max_cstate=0`), ASPM=off — required for sub-15µs latency metrics

## Ansible playbook structure
- `playbooks/eTran/setup/` — one-time: system deps, kernel build, install eTran
- `playbooks/eTran/tuning/` — one-time (persists reboot): SMT off, mitigations off, C-states off, ASPM off, tuned
- `playbooks/eTran/evaluation/` — per-session (run after EVERY reboot): ARP, hosts, NIC tuning, IRQ affinity, MTU, verify

## Ansible inventory
- `@server` = node0, `@clients` = node1–node9
- Paper PDF: `nsdi25-chen-zhongjie.pdf` in repo root

## Key source files
- `common/xskbp/xsk_buffer_pool.h` — buffer pool constants (umem_num_frames, buffers_per_slab)
- `micro_kernel/eBPF/homa/main.c:240` — XDP_EGRESS grant drop bug
- `common/tran_def/homa.h:8` — HOMA_MAX_MESSAGE_LENGTH = 1000000
- `micro_kernel/micro_kernel.cc:51` — default queues = 20
- `homa_app/cp_node.cc:1616` — default workload = "100"
