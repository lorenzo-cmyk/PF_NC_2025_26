# Metriche eTran — NSDI '25

Questo documento contiene **esclusivamente** le metriche di performance che coinvolgono **eTran** (eTran-Homa, eTran-TCP, hook XDP e pacing). Baseline e stack di confronto (Linux TCP/Homa, TAS) sono esclusi.

---

## 1. Metriche primarie eTran

| Stack | Misura | Unità | Valore atteso |
| :--- | :--- | :--- | :--- |
| **eTran - Homa** | Latenza RTT mediana, messaggi corti (32B, single client thread) | µs | **11.8** |
| **eTran - Homa** | Throughput, messaggi grandi (1MB, single-threaded, client-max=1) | Gbps | **17.7** |
| **eTran - Homa** | Throughput server multi-thread (500KB RPC da 7 porte) | Gbps | **23.0** |
| **eTran - Homa** | Throughput client multi-thread (500KB RPC verso 7 server) | Gbps | **22.7** |
| **eTran - Homa** | RPC rate client, messaggi corti (32B, 7 porte) | Mops | **2.9** |
| **eTran - Homa** | RPC rate server, messaggi corti (32B) | Mops | **3.3** |
| **eTran - Homa** | P99 tail latency slowdown, W2-W3 (short messages) | Slowdown Factor | `Linux-Homa (P99 Slowdown) / (3.9 ~ 7.5)` |
| **eTran - Homa** | P50 median latency slowdown, W2-W3 (short messages) | Slowdown Factor | `Linux-Homa (P50 Slowdown) / (1.4 ~ 3.6)` |
| **eTran - Homa** | RTT P50 slowdown, shortest 10% RPC, W4 (20 Gbps) | Slowdown Factor | `Linux-Homa (W4 P50 Slowdown) / 4.1` |
| **eTran - Homa** | RTT P50 slowdown, shortest 10% RPC, W5 (20 Gbps) | Slowdown Factor | `Linux-Homa (W5 P50 Slowdown) / 3.9` |
| **eTran - Homa** | RTT P99 slowdown, shortest 10% RPC, W4 (20 Gbps) | Slowdown Factor | `Linux-Homa (W4 P99 Slowdown) / 4.3` |
| **eTran - Homa** | RTT P99 slowdown, shortest 10% RPC, W5 (20 Gbps) | Slowdown Factor | `Linux-Homa (W5 P99 Slowdown) / 2.9` |
| **eTran - TCP** | Throughput, messaggi 1KB (64 outstanding, single-threaded) | Gbps | `4.8 × Linux-TCP (Throughput 1KB)` |
| **eTran - TCP** | Throughput, messaggi 2KB (64 outstanding, single-threaded) | Gbps | `0.87 × TAS-TCP (Throughput 2KB)` |
| **eTran - TCP** | Throughput, 1K connessioni persistenti (64B, closed-loop) | Mops | `2.26 × Linux-TCP (Throughput 1K conn)` |
| **eTran - TCP** | Throughput, connessioni brevi 16 msg/conn (1K flussi concorrenti) | Mops | `42.7 × Linux-TCP (Throughput 16 msg/conn)` |
| **eTran - TCP** | Throughput, connessioni brevi 256 msg/conn (1K flussi concorrenti) | Mops | `5.4 × Linux-TCP (Throughput 256 msg/conn)` |
| **eTran - TCP** | Throughput Key-Value Store (100K keys, Zipf s=0.9, 9:1 GET:SET) | Mops | `(2.4 ~ 4.8) × Linux-TCP (KV Throughput)` |
| **eTran - TCP** | RTT P50 (mediana) Key-Value Store (server under-loaded) | µs | **17.2** (`Linux-TCP KV Latency P50 / 3.7`) |
| **eTran - TCP** | RTT P99 (tail) Key-Value Store (server under-loaded) | µs | **27.5** (`Linux-TCP KV Latency P99 / 3.2`) |
| **eTran - TCP** | Cicli CPU totali per richiesta (total kcycles, vedi breakdown) | kcycles | **4.37** |
| **eTran - Homa** | Cicli CPU totali per richiesta (total kcycles, vedi breakdown) | kcycles | **5.48** |
| **eTran (Pacing)** | Deviazione dalla conformità del rate shaping (1MB @ 8 Gbps) | % | **< 0.4** |
| **eTran (Pacing)** | Throughput aggregato multi-flusso con target 8 Gbps | Mbps | **7950 ~ 8050** |
| **eTran - TCP** | Penalità di throughput con 1% packet loss | % | **~8** |
| **eTran - TCP** | Penalità di throughput con 5% packet loss | % | **~33** |
| **eTran - Homa** | Penalità di throughput con 5% packet loss | % | **~90-100** |

---

## 2. Breakdown cicli CPU per singola richiesta — eTran (Table 5)

Valori in **migliaia di cicli CPU (kcycles)** sotto stress test con singolo contesto NAPI.

| Componente | eTran - TCP | eTran - Homa |
| :--- | :---: | :---: |
| **Application** | 0.48 | 0.95 |
| **Socket / RPC** | 0.63 | 0.98 |
| **Data Copy** | 0.19 | 0.32 |
| **Sk_buff** | 0.15 | 0.08 |
| **TCP / Homa + IP** | 1.06 | 1.47 |
| **Lock / Unlock** | 0.18 | 0.24 |
| **NIC Driver** | 1.17 | 0.83 |
| **Memory Mgmt** | 0.05 | 0.06 |
| **Scheduling** | 0.25 | 0.18 |
| **Other** | 0.21 | 0.38 |
| **TOTALE (kcycles)** | **4.37** | **5.48** |

---

## 3. Microbenchmark datapath interno eTran (hook e BPF maps)

### 3.1 Overhead hook XDP_EGRESS (Table 3)
Singolo core, 64B packets sotto stress test.

| Configurazione Datapath | Throughput egress atteso (Mpps) | Throughput relativo | Perdita di throughput |
| :--- | :---: | :--- | :---: |
| **AF_XDP tx-only** (Baseline) | **11.55** | *Baseline* | — |
| **+ Empty XDP_EGRESS** | **10.79** | `AF_XDP tx-only × 0.934` | 6.6% |
| **+ Out-Of-Order (OOO) Completion** | **9.95** | `AF_XDP tx-only × 0.861` | 13.9% |
| **+ Array Lookup** | **9.71** | `AF_XDP tx-only × 0.841` | 15.9% |
| **+ Hashmap Lookup** | **9.10** | `AF_XDP tx-only × 0.788` | 21.2% |

### 3.2 Performance pacchetto XDP_GEN (Table 4)
Due core: uno genera ACK/credit con `XDP_GEN`, l'altro riceve e droppa con `AF_XDP`.

| Benchmark | Throughput totale atteso (Mpps) | Core CPU attivi | Throughput per-core (Mpps) |
| :--- | :---: | :---: | :---: |
| **rx-drop + XDP_GEN** | **6.03** | 1.35 | **4.47** |
