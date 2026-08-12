# Replicating: "eTran: extensible kernel transport with eBPF"

- Deadline: 2026-08-28
- Grade: N/D

## Description

This repository is an attempt to reproduce the findings of the original eTran paper ("eTran: extensible kernel transport with eBPF", NSDI 25), by replicating its evaluation on a CloudLab cluster.

## Repository structure

This repository contains the CloudLab profile used to set up the cluster, Ansible playbooks for configuring it, and runbooks documenting the procedures used to run the experiments and collect measurements.

```bash
.
├── Report/                          # Final report and measurements
│   ├── Deliverable/
│   │   ├── Final_Report.md          # Full report (paper summary, results, reproducibility assessment)
│   │   ├── Figures/                 # eTran architecture figure
│   │   ├── render_pdf.py            # MD -> PDF rendering script
│   │   └── gutenberg.css            # Print stylesheet for the report
│   └── Measurements/
│       ├── Results.md               # Raw measurements per metric
│       └── Tuning_History.md        # Tuning experiments and findings
└── Reproduction/                    # Reproduction pipeline and runbooks
    ├── CloudLab/
    │   └── profile.py               # CloudLab profile (10 xl170 nodes)
    ├── Ansible/                     # Cluster setup, tuning, and evaluation
    │   ├── ansible.cfg
    │   ├── inventory/hosts.yml      # @server = node0, @clients = node1-9
    │   ├── files/kernel-config
    │   └── playbooks/               # eTran, Homa, and DCTCP pipelines
    ├── Runbook/                     # Exact per-metric commands
    │   ├── eTran_Runbook.md         #   eTran (Homa + TCP) benchmarks
    │   ├── Homa_Runbook.md          #   Linux-Homa benchmarks
    │   └── DCTCP_Runbook.md         #   Linux-DCTCP benchmarks
    └── AGENTS.md                    # Cluster operations, pitfalls, anti-patterns
```

## Authors

- [pierluigigrossi](https://github.com/pierluigigrossi)
- [TeoFranken](https://github.com/TeoFranken)
- [lorenzo-cmyk](https://github.com/lorenzo-cmyk)
