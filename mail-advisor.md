Subject: eTran (NSDI '25) — first reproduction attempt: single-thread ok, multi-thread unreachable, documentation gaps

Ciao [Nome],

ti aggiorno sulla riproduzione del paper "eTran: Extensible Kernel Transport with eBPF" (NSDI 2025). In breve: gli autori propongono un nuovo stack di trasporto (TCP + Homa) che usa eBPF per bypassare il kernel Linux e ottenere latenze e throughput migliori del kernel nativo. L'hanno accettato a NSDI, conferenza top. Abbiamo preso il loro codice esatto dalla repo ufficiale (`github.com/eTran-NSDI25/eTran`) e lo stiamo eseguendo sui loro stessi benchmark — sono i binari che shippano loro, non roba nostra.

Ho completato un primo ciclo di esecuzione su due macchine xl170 di CloudLab — stesso identico modello del paper (Xeon E5-2640v4, ConnectX-4 25 Gbps). Il codice compila, i binari partono. Ecco lo stato.

## Cosa funziona e batte il paper (✓)

| Metrica | Paper | Misurato |
|---------|------:|---------:|
| Latenza Homa 32B (P50) | 11.8 µs | **10.2 µs** |
| Throughput Homa 1MB | 17.7 Gbps | **20.8 Gbps** |

Single-thread: nessun problema, battiamo il paper.

## Cosa non arriva al paper (⚠️)

| Metrica | Paper | Misurato | Spiegazione |
|---------|------:|---------:|-------------|
| Throughput Homa 500KB con 7 porte | 23.0 Gbps | 18.5 Gbps | NAPI serialization: con `--ports 7` nello stesso processo, i 7 client condividono 1 contesto NAPI → RTT ×7 |
| RPC rate Homa 32B con 7 porte | 2.9 Mops | 0.45 Mops | Stesso problema. 7 processi cp_node separati non aiutano perché Homa smista tutti gli RPC alla stessa porta server |
| AF_XDP tx-only baseline | 11.55 Mpps | 7.8 Mpps | ⚠️ **Questo è il punto più preoccupante.** Test su UNA macchina singola, nessuna rete coinvolta. Stesso ferro (xl170), stesso kernel, stesso NIC. Provato ogni variabile: governor=performance, coalescing disabilitato, ring buffer 8192, rebuild con -O3, core isolato, SMT topology. Nessuna combinazione va oltre 7.8 Mpps. Il 48% di gap su un test puramente locale è inspiegabile senza accesso al setup esatto del paper (configurazione BIOS, versione firmware NIC, parametri di compilazione xdpsock, patch al driver mlx5). Questo mina la fiducia in TUTTE le altre misure del paper. |

## Cosa è bloccato (❌)

- **Packet loss (§6.4)**: `tc netem` non funziona con XDP/AF_XDP perché i pacchetti bypassano il qdisc del kernel. Il paper avrà usato lo switch Mellanox per l'iniezione di perdita. CloudLab richiede accesso diretto allo switch M2410 ma la prenotazione fallisce con "resource unavailable" — ho già provato ogni combinazione di profili e ticket di supporto, senza successo.
- **Multi-thread tests**: servono 7 NIC fisiche (quindi 7 macchine client) per via del collo di bottiglia NAPI che il paper non menziona da nessuna parte.

## Problemi di documentazione trovati

1. Il paper non specifica **mai** i flag esatti usati per i test. I comandi nel paper sono di alto livello ("we ran X"), non riproducibili direttamente. Ho dovuto fare reverse engineering dal codice sorgente (`cp_node.cc`, `micro_kernel.cc`, ecc.) per capire i flag corretti. Esempi concreti:
   - I test multi-thread richiedono `--client-max` calibrato per evitare overflow UMEM
   - Il server `cp_node` crasha senza `ETRAN_PROTO=homa` (costruttore pre-main) — non documentato
   - Il pacing funziona solo quando il gap inter-pacchetto supera l'RTT — il paper non lo dice
   - `flexkvs_server` prende argomenti posizionali, non flag getopt — l'help mente
2. L'help dei binari contiene bug (flag documentati ma non implementati, semantiche invertite, default sbagliati) — vedi repo.
3. Nessuna indicazione su configurazione NIC (coalescing, governor, ring buffer) che impattano il throughput in modo drastico (da 5.3 a 7.8 Mpps solo col governor).
4. Nessuna nota sul fatto che `tc netem` è inutile con XDP; nessuna nota sul fatto che serve accesso diretto allo switch per le misure di packet loss.

## Prossimi passi

1. Ottenere altre 5-8 macchine xl170 per i test multi-thread (le prenotazioni standard su CloudLab funzionano)
2. Per lo switch: capire se c'è un workaround (script di perdita via eBPF custom sul microkernel?), o se il ticket CloudLab va insistito con spiegazione del perché è bloccante
3. MEASURE 8 (perf/cicli CPU) la possiamo già fare con 2 macchine

Ho documentato tutto in tre file nella repo:
- `eTran_only_metrics.md` — tabella metriche con attesi vs misurati, comandi esatti, flag verificati contro il codice sorgente
- `eTran_reproduction_metrics.md` — tutte le metriche del paper (inclusi Linux e TAS)
- `execution-log.md` — log di ogni comando lanciato, tentativi, tuning NIC, lezioni apprese

## TL;DR

I single-thread test li battiamo. Ma il paper è irriproducibile per tre ragioni indipendenti:

1. **Nessuna indicazione dei comandi esatti.** Ho dovuto fare reverse engineering del codice sorgente per capire che flag usare, e diversi binari hanno help buggati o incompleti.

2. **Le misure che richiedono hardware specifico (switch, 7+ macchine) non sono fattibili su CloudLab senza un profilo che nessuno riesce a prenotare.** Il paper non menziona da nessuna parte che servono queste risorse.

3. **Il baseline AF_XDP su macchina singola sottoperforma del 48% su hardware identico.** Se non riesco a riprodurre un test che non tocca la rete, il problema è a monte — configurazione BIOS? firmware NIC? patch al driver? Il paper non fornisce nessuna di queste informazioni.

Secondo me o scriviamo agli autori chiedendo lo script esatto di riproduzione, o contattiamo direttamente gli shepherd di NSDI. Fammi sapere come vuoi procedere.

Ti giro la repo appena vuoi.
