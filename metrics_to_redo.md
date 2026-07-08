# Metrics Requiring Redo

## Still pending

### #21 — CPU cycles per request
**Issue:** Measured client-side (~2.9 kcycles). Paper value is server-side under
single-NAPI stress (4.37 kcycles).

**Action needed:** Rerun `perf stat` on the **server** process during a 1KB
throughput run.

---

## Dependency chain

```
#21 → measure on server side (eTran only)
```
