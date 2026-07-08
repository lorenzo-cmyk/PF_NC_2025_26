# Metrics Requiring Redo

All tooling bugs and DCTCP baselines resolved. Remaining gaps:

- **Linux-Homa baselines** (~8 rows) — requires stock kernel + Homa kernel module
- **Metrics 16-17** (short-lived connections) — not reproducible without benchmark code
- **Switch ECN marking** (70KB threshold) — not configurable in our cluster
