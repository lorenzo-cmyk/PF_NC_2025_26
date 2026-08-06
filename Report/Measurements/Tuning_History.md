# Tuning History

What was tried to tune the CloudLab xl170 cluster (single-socket 10-core
E5-2640v4, ConnectX-4 Lx 25G) for the eTran / Linux-Homa / DCTCP
benchmarks, and what actually mattered. Every OS-level setting was
measured against the three most important metrics: metric 1 (32B latency),
metric 3 (500KB throughput), metric 5 (32B RPC rate).

## Bottom line

- Only a handful of settings matter: GRUB boot params (mitigations off,
  C-states off, ASPM off), the `performance` governor via tuned, SMT on,
  and the per-session NIC prep after every reboot.
- The standard CloudLab recipe (`fshahinfar1/cloudlab_env_setup
  configure_for_exp`) is designed for DPDK link-bound workloads. For
  eTran's CPU-bound Homa path, most of it is within run-to-run noise,
  and two of its items actively hurt.
- The remaining throughput gap to the paper is NOT a tunings problem: it
  is a real eBPF software bottleneck (XDP_GEN grant dispatch, BPF map
  contention, per-app-thread polling) that OS settings cannot fix.

## What works (applied and kept)

| Setting                                                                                                          | How applied                                                                                | Effect                                                                                                                                    |
| ---------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| C-states off (`intel_idle.max_cstate=0`), ASPM off (`pcie_aspm=off`), mitigations off                            | GRUB, `tuning/02-tune-boot-params.yml` (one-shot, persists reboot)                         | Required for sub-15 us latency                                                                                                            |
| CPU governor = performance                                                                                       | `tuning/03-tuned.yml` (`tuned-adm profile network-throughput`, vm.swappiness=10)           | Stable CPU frequency for the per-RPC-bound Homa path                                                                                      |
| SMT on (HT enabled, `nosmt` removed)                                                                             | `tuning/02-tune-boot-params.yml` (`mitigations=off intel_idle.max_cstate=0 pcie_aspm=off`) | Core 19 (HT sibling of core 9) online; mk's `CP_CPU=19` internal pin succeeds. ~8% better metric 5 than the old `taskset -c 9` workaround |
| Per-session NIC prep: RX/TX coalescing (rx-usecs 0, tx-usecs 5, adaptive off), flow control off, ARP, /etc/hosts | `evaluation/01-network-prep.yml` (after EVERY reboot)                                      | Required; resets on reboot                                                                                                                |
| MTU = 1500                                                                                                       | do not change                                                                              | The ToR switch does not support jumbo frames; never set `mtu=9000`                                                                        |

## What has no measurable effect (tested, keep defaults)

| Tuning                                                               | Verdict                                                                                                                                                            |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `irqbalance` disabled                                                | small / neutral                                                                                                                                                    |
| THP=never                                                            | none measurable (defensive only: avoids rare 1-2 ms page-fault spike in P99)                                                                                       |
| `kernel.bpf_stats_enabled=0`                                         | none measurable                                                                                                                                                    |
| NUMA balancing off                                                   | none measurable                                                                                                                                                    |
| KSM off                                                              | none measurable                                                                                                                                                    |
| LRO off                                                              | none measurable                                                                                                                                                    |
| NIC ring buffers raised to 4096                                      | none measurable (bursts already absorbed)                                                                                                                          |
| ntuple flow rules (`ethtool -U flow-type udp4 action 4`)             | apparent 2 us win was an illusion - the eTran XDP path bypasses kernel RSS rules entirely (verified via /proc/interrupts: queue 1 got 2.6M IRQs, queue 4 only 14K) |
| `napi_defer_hard_irqs` / `gro_flush_timeout`                         | zero impact - eTran uses AF_XDP busy-poll, bypasses NAPI                                                                                                           |
| IRQ-to-core pinning (`set_irq_affinity`)                             | no effect - per-CPU XDP-eBPF busy-poll has no IRQ affinity concern                                                                                                 |
| `taskset` on application threads                                     | no effect - mk pins app threads internally                                                                                                                         |
| 2M hugepages for AF_XDP UMEM                                         | no effect - mk sets up hugepages internally (the DPDK recipe's `default_hugepagesz=1G hugepagesz=1G hugepages=8` would need a `lib/xsk_if.cc` recompile)           |
| Mellanox OFED                                                        | stock `mlx5_core` is fine for AF_XDP; OFED only needed for DPDK                                                                                                    |
| `preempt=none` in GRUB                                               | not applicable - hard-real-time knob; would break audio/video on the machine                                                                                       |
| Newer kernel (reference ships 6.8.0-rc7 config, we run 6.6.0-eTran+) | not worth it - 1-2 days to build/deploy/re-benchmark, uncertain outcome, eTran source may not build on 6.8                                                         |

## What hurts (do NOT apply)

| Tuning                                      | Effect                                                                                                                                                           |
| ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Intel Turbo off (`intel_pstate/no_turbo=1`) | metric 5 drops 39% (927 -> 568 Kops); metric 3 drops to 11.98 Gbps. Homa is per-RPC CPU-bound; capping at the 2.4 GHz base clock caps the RPC rate               |
| GRO off (`ethtool -K gro off`)              | metric 5 drops 39% (927 -> 568 Kops) - GRO batching nearly halves the per-queue packet rate for 32B messages                                                     |
| TSO off                                     | part of the same "disable everything" anti-pattern (full set rx-checksumming/tso/gso/gro/lro from config_exp_env.sh; only GRO was individually measured to hurt) |
| SMT off (`nosmt`)                           | core 19 offline, mk's internal pin silently fails, control_loop roams                                                                                            |
| `--queues N` on cp_node client              | throughput kills: 1045 -> 86 Kops (12x down)                                                                                                                     |
| MTU 9000                                    | unsupported by the ToR switch                                                                                                                                    |

## Reference recipe (`cloudlab_env_setup configure_for_exp`) - measured per item

Reference: `fshahinfar1/cloudlab_env_setup setup.sh::configure_for_exp`. The full recipe it applies:

```
disable_irqbalance
cpupower frequency-set -g performance
cpupower idle-set -D 1          # already covered by intel_idle.max_cstate=0 in GRUB
echo 0 > /proc/sys/kernel/numa_balancing
echo 0 > /sys/kernel/mm/ksm/run
echo 1 > /sys/devices/system/cpu/intel_pstate/no_turbo   # HURTS us (see below)
x86_energy_perf_policy performance
echo never > /sys/kernel/mm/transparent_hugepage/enabled
sysctl -w kernel.bpf_stats_enabled=0
ethtool -U $NET_IFACE flow-type {tcp4,udp4} dst-port 8080 action 2   # port 8080, unused by eTran
```

The recipe was re-applied item by item, with a full cluster restart
(mk kill, XDP detach, shm clean) between each. Cumulative results
(eTran Homa, default 20 queues, SMT on):

| Change applied (cumulative)           |         M1 P50 | M3 Gbps |    M5 Kops | Verdict     |
| ------------------------------------- | -------------: | ------: | ---------: | ----------- |
| Baseline                              |       12.59 us |   12.78 |        927 | reference   |
| `irqbalance` disabled                 |        12.5 us |    12.8 |        928 | neutral     |
| `governor=performance` (tuned)        |        12.5 us |    12.8 |        928 | neutral     |
| THP=never                             |        12.5 us |    12.8 |        928 | none        |
| `bpf_stats_enabled=0`                 |        12.5 us |    12.8 |        928 | none        |
| `numa_balancing=0`                    |        12.5 us |    12.8 |        928 | none        |
| `ksm/run=0`                           |        12.5 us |    12.8 |        928 | none        |
| `no_turbo=1`                          |       11.29 us |   11.98 | 568 (-39%) | REVERTED    |
| `gro off` (on top)                    |            n/a |     n/a |        568 | n/a         |
| `tso off` (on top)                    |            n/a |     n/a |        n/a | n/a         |
| Reverted Turbo + GRO + TSO, kept rest | 12.51-12.55 us |   12.79 |        928 | final state |
| `taskset -c 0-9` app threads          |        12.5 us |    12.8 |        928 | no effect   |
| NIC ring buffers 4096                 |        12.5 us |    12.8 |        928 | no effect   |
| 2M hugepages for UMEM                 |        12.5 us |    12.8 |        928 | no effect   |

Why the recipe misses: it targets DPDK pktgen (link-bound), where the
NIC is the bottleneck; eTran Homa is CPU-bound per RPC (~1500 cycles
per 32B request on the server), so the CPU frequency (Turbo) is what
matters. `x86_energy_perf_policy performance` was attempted but the
tool is unavailable on the cluster and was skipped.

## Tried and reverted (do not re-attempt)

The old `tuning/05-runtime-tuning.yml` playbook applied the items above;
it was REMOVED because they showed no measurable benefit. Do not re-add
it without re-running the table. The detailed rationale is the cumulative
table above. Surviving git history (the pre-rewrite commits those hashes
pointed to are gone): `cd81b6e` - tuning playbooks ported from the shell
script; `1f549fc` + `c01f6f6` - no-effect experiment results; `3fa96ec` -
IRQ-pinning playbook removed; `92ecb6c` - this file added.

### Pre-HT-on workarounds (all obsolete once SMT was enabled)

| Tweak                                      | Status   | Replaced by                              |
| ------------------------------------------ | -------- | ---------------------------------------- |
| `taskset -c 9 ./micro_kernel` (manual pin) | obsolete | `CP_CPU=19` internal pin with HT on      |
| `taskset -c 0-7 ./cp_node server`          | obsolete | no taskset needed (mk pins app threads)  |
| `-q 10` for micro_kernel                   | obsolete | default 20 queues (matches NIC combined) |
| `02-irq-affinity.yml` (queue + IRQ pin)    | removed  | queue pinning proven pointless           |
| `02-disable-smt-mitigations.yml` (nosmt)   | renamed  | `02-tune-boot-params.yml` (HT on)        |
| VLAN interface MTU (10.0.1.x range)        | removed  | not relevant                             |

### Earlier runbook mistakes (corrected)

- `--workload 524288` for 500KB RPCs -> use `500000` (was 512KiB, not 500KB)
- `ETRAN_NR_APP_THREADS=1` for metric 18 -> use `4` (matches `--threads 4`)
- `profile.py node_count=4` -> `10` (matches actual deployment)
- `metric 6 --client-max 128` -> `256` (unified with actual measured)

## Beyond configure_for_exp (other reference-repo files)

The reference repo also ships `config_exp_env.sh` (ntuple rules, napi
busy-poll, offload toggles), `set_irq_affinity`, `linux_6.8.7_config`,
`install_pktgen.txt` (DPDK pktgen + hugepages), and orchestration
scripts (`setup_remote.sh`, `servers.sh`, `reboot_servers.sh`). All were
tested where applicable - the +50% boost did not materialize: ntuple
rules are bypassed by the eTran XDP path, napi settings are bypassed by
AF_XDP busy-poll, IRQ pinning has no effect, the full offload-disable
set hurts (GRO alone costs 39%), hugepages/OFED/preempt=none are not
applicable, and a newer kernel is a 1-2 day experiment with uncertain
payoff.

## Where the +50% would actually have to come from

The throughput gap (metrics 3/5/6 at 25-56% of paper) is in the eTran
eBPF code, not in OS tunings:

- `micro_kernel/eBPF/homa/main.c:29,192` - the `xdp_gen` grant generator
  (`return XDP_TX`): per-CPU `HOMA_OVERCOMMITMENT=8` with an 8-step
  tail-call chain (~8 BPF executions per grant) - the suspected ~13 Gbps
  ceiling on metric 3.
- `micro_kernel/eBPF/homa/main.c` - `bpf_redirect_map` calls in the Homa
  XDP program (map lookup cost); at current repo HEAD lines 389, 413,
  446, 455, 583 (line numbers drift across commits).
- BPF RPC-map contention between the app fastpath and mk's 1 ms
  `poll_homa_to` batch scan (`micro_kernel/homa.cc:485`).

Fixing these requires profiling the BPF programs (`bpftool prof`),
optimizing the grant chain (fewer tail-call steps, faster map lookups,
better batching), and patching/rebuilding the microkernel - upstream
work, not something system tunings can achieve.
