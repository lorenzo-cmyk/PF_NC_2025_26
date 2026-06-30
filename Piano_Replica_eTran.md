# Piano di Replica eTran (NSDI '25) su CloudLab

Questo documento contiene la guida passo-passo per replicare le misure presentate nell'articolo **"eTran: Extensible Kernel Transport with eBPF"** utilizzando nodi fisici su **CloudLab**.

---

## 1. Architettura e Obiettivi delle Misurazioni

Il paper propone **eTran**, un sistema per estendere il trasporto nel kernel Linux tramite eBPF. L'obiettivo delle misure è confrontare eTran con:
- **Linux (Homa)** (modulo kernel Homa nativo)
- **Linux (TCP)** con controllo di congestione DCTCP
- **TAS** (un framework di trasporto kernel-bypass in user-space basato su DPDK)

### Nota sulle versioni del Kernel Linux nel Paper:
- **eTran (TCP/Homa)** e **Linux (TCP/Homa) nativo** sono eseguiti su **Linux Kernel v6.6.0** (usando il kernel personalizzato `eTran-linux`).
- **TAS** (il baseline di confronto per TCP) è eseguito su **Linux Kernel v5.15.0** (a causa di limitazioni e incompatibilità dei driver Mellanox ConnectX sulla versione v6.6.0).
- Il riferimento **`[55]`** nel paper indica la versione originale del modulo kernel Homa (*USENIX ATC '21*).

### Metriche e Figure da Replicare:
1. **Tabella 2 (Microbenchmarks Homa)**: Latenza a 32B (target ~11.8 µs) e Throughput a 1MB (target ~17.7 Gbps).
2. **Figura 5 e 6 (Cluster Benchmark Homa)**: Rallentamento (Slowdown) RTT su carichi W2-W5 dominati da messaggi corti o lunghi.
3. **Figura 7 (Throughput TCP)**: Throughput in base alla dimensione dei messaggi e scalabilità delle connessioni persistenti.
4. **Figura 8 (Key-Value Store)**: Throughput e latenza CCDF dell'applicazione Key-Value Store (basata su FlexKVS) all'aumentare dei core CPU dell'applicazione.

---

## 2. Requisiti di Sistema (CloudLab)

Nel paper gli autori hanno usato **10 nodi fisici** per simulare un ambiente rack/datacenter realistico, ma **non tutti i test richiedono 10 macchine**:

- **Solo 2 Macchine (1 Server + 1 Client)** sono sufficienti per replicare la stragrande maggioranza delle misure:
  - Tutti i microbenchmark di latenza e throughput di Homa (Tabella 2).
  - Tutti i grafici di throughput TCP (Figura 7).
- **Da 2 a 6 Macchine (1 Server + da 1 a 5 Client)** sono raccomandate per il Key-Value Store (Figura 8), in modo da avere abbastanza client concorrenti per saturare le prestazioni del server.
- **10 Macchine** sono necessarie **solo ed esclusivamente** per il "Cluster Benchmark" di Homa (Figure 5 e 6), dove tutti i nodi generano traffico incrociato casuale simultaneamente.

> 💡 **Consiglio:** Se vuoi risparmiare risorse o tempo su CloudLab, puoi avviare un profilo con **soli 2 nodi** e replicare comunque i risultati principali (Tabella 2 e Figura 7).

### Configurazione Ottimale dei Nodi su CloudLab:
- **Profilo Hardware**: `xl170` (o simile).
  - CPU: Due Intel E5-2640v4 (10-core ciascuno, 2.4GHz)
  - RAM: 64 GB
  - NIC: Mellanox ConnectX-4 25 Gbps (connessi ad uno switch Mellanox nello stesso rack per garantire bassissima latenza).
- **Sistema Operativo**: Ubuntu 22.04 LTS.

---

## 3. Fase 1: Compilazione del Kernel Mainline 5.15 ed Esecuzione dei Test di Baseline

Questa fase prevede la compilazione di un kernel **Linux 5.15 mainline pulito**. Questo approccio garantisce che i test di baseline ("Linux Homa", "Linux TCP" e "TAS") vengano eseguiti su un kernel autocostruito e non influenzato dal kernel stock distribuito da Ubuntu, garantendo l'omogeneità dei test.

### Procedura di compilazione del Kernel 5.15 Mainline:

1. **Scaricare e scompattare i sorgenti del kernel Linux 5.15 mainline**:
   ```bash
   cd ~
   wget https://cdn.kernel.org/pub/linux/kernel/v5.x/linux-5.15.tar.xz
   tar -xf linux-5.15.tar.xz
   cd linux-5.15
   ```

2. **Installare i pacchetti necessari per la compilazione**:
   ```bash
   sudo apt update && sudo apt-get install -y git fakeroot build-essential ncurses-dev xz-utils libssl-dev bc flex libelf-dev bison clang llvm libclang-dev libbpf-dev libelf-dev dwarves libmnl-dev libc6-dev-i386 libcap-dev libgoogle-perftools-dev libdwarf-dev cpufrequtils libpcap-dev automake libtool pkg-config rsync
   ```

3. **Configurare il kernel**:
   ```bash
   # Copia la configurazione di Ubuntu corrente come base
   cp /boot/config-$(uname -r) .config
   make olddefconfig
   
   # Disabilita i certificati e la firma del kernel per evitare errori
   scripts/config --disable SYSTEM_TRUSTED_KEYS
   scripts/config --disable SYSTEM_REVOCATION_KEYS
   ```

4. **Compilare ed installare il Kernel 5.15**:
   ```bash
   make -j`nproc`
   sudo make modules_install -j`nproc`
   sudo make install -j`nproc`
   sudo make headers_install INSTALL_HDR_PATH=/usr
   ```

5. **Configurazione Sicura di GRUB (Menu interattivo all'avvio)**:
   Modifichiamo le impostazioni di GRUB in modo da visualizzare l'elenco dei kernel all'avvio:
   ```bash
   sudo sed -i 's/GRUB_TIMEOUT_STYLE=hidden/GRUB_TIMEOUT_STYLE=menu/' /etc/default/grub
   sudo sed -i 's/GRUB_TIMEOUT=0/GRUB_TIMEOUT=10/' /etc/default/grub
   sudo update-grub
   ```

6. **Riavviare nel Kernel 5.15 Mainline appena compilato**:
   ```bash
   sudo reboot
   ```
   *Al riavvio, seleziona il kernel `5.15.0` compilato. Verifica che sia attivo con `uname -r`.*

---

### Esecuzione dei Test di Baseline (sotto Kernel 5.15):

Sotto questo kernel 5.15, eseguiremo tutte le baseline native riportate nel paper.

#### Baseline 1: Linux (Homa) Nativo
1. Clonare il modulo kernel Homa ufficiale degli autori (commit `8321cde` citato nel paper):
   ```bash
   git clone https://github.com/johnousterhout/homa.git ~/homa-baseline
   cd ~/homa-baseline
   git checkout 8321cde
   make
   sudo insmod homa.ko
   ```
2. Eseguire i test di latenza/throughput per il modulo Homa nativo usando l'applicazione di benchmark inclusa nel repository di Homa.

#### Baseline 2: Linux (TCP) Nativo con DCTCP
1. Abilitare DCTCP nel kernel:
   ```bash
   sudo modprobe tcp_dctcp
   sudo sysctl -w net.ipv4.tcp_congestion_control=dctcp
   ```
2. Eseguire i test di throughput TCP standard con `iperf3` o con l'applicazione `epoll_server` compilata nativamente (senza `LD_PRELOAD` di eTran):
   ```bash
   # Compila tcp_app senza librerie esterne
   cd ~/eTran/eTran/tcp_app
   make
   # Server (Nodo 1)
   ./epoll_server -i 192.168.6.1 -l 100000 -b 100000
   # Client (Nodo 2)
   ./epoll_client -i 192.168.6.1 -l 100000 -b 100000
   ```

#### Baseline 3: TAS (TCP Acceleration Service) con DPDK
1. Clonare TAS (commit `d3926ba` citato nel paper):
   ```bash
   git clone --recursive https://github.com/microsoft/tas.git ~/tas-baseline
   cd ~/tas-baseline
   git checkout d3926ba
   ```
2. Configurare DPDK e compilare TAS seguendo la guida ufficiale di TAS sotto il kernel 5.15.
3. Eseguire i benchmark di TAS.

---

## 4. Fase 2: Compilazione ed Installazione del Kernel Personalizzato eTran (`eTran-linux` 6.6.0)

Una volta raccolti tutti i dati della baseline, passiamo alla compilazione del kernel personalizzato di eTran. eTran richiede estensioni eBPF (come `BPF_MAP_TYPE_PKT_QUEUE` e `XDP_EGRESS`) disponibili solo in questa versione modificata.

### Procedura di compilazione del Kernel `eTran-linux`:

1. **Clonare il repository di `eTran-linux`**:
   ```bash
   git clone https://github.com/eTran-NSDI25/eTran-linux.git ~/eTran-linux
   cd ~/eTran-linux
   ```

2. **Configurare il kernel 6.6.0**:
   ```bash
   # Usa la configurazione corrente del kernel 5.15 come base stabile per il 6.6.0
   cp /boot/config-$(uname -r) .config
   make olddefconfig
   
   # Disabilita la firma dei moduli e le chiavi di sistema per evitare errori di avvio
   scripts/config --disable SYSTEM_TRUSTED_KEYS
   scripts/config --disable SYSTEM_REVOCATION_KEYS
   ```

3. **Compilare ed Installare**:
   ```bash
   make -j`nproc`
   sudo make modules_install -j`nproc`
   sudo make install -j`nproc`
   sudo make headers_install INSTALL_HDR_PATH=/usr
   ```

4. **Aggiornare GRUB e riavviare nel kernel eTran (6.6.0)**:
   ```bash
   sudo update-grub
   sudo reboot
   ```
   *Al boot, seleziona il nuovo kernel modificato `6.6.0`. Verifica con `uname -r`.*

---

## 5. Fase 3: Configurazione di eTran (User-space & eBPF)

Eseguire questi passaggi su **tutti i nodi** dopo aver avviato con successo il kernel modificato `eTran-linux` (6.6.0).

1. **Installare le dipendenze per l'applicazione user-space e eBPF**:
   Anche se hai già installato alcune dipendenze durante la compilazione del kernel, assicurati che questi pacchetti specifici per lo user-space di eTran siano presenti (essenziali se usi nodi diversi per i client):
   ```bash
   sudo apt update && sudo apt-get install -y libmnl-dev libgoogle-perftools-dev libelf-dev zlib1g-dev build-essential
   ```
   *(Nota: `libgoogle-perftools-dev` è fondamentale in quanto fornisce `tcmalloc`, necessario per compilare `tcp_app`)*

2. **Clonare il repository principale di eTran**:
   ```bash
   git clone https://github.com/eTran-NSDI25/eTran.git ~/eTran
   ```

3. **Installare la toolchain eBPF compilando `bpftool` e configurando `LLVM-16`**:
   ```bash
   cd ~/eTran
   sudo bash install.sh
   ```

4. **Configurare e Compilare eTran**:
   ```bash
   ./configure && make -C eTran
   ```

5. **Warming up delle tabelle ARP e di Routing (FONDAMENTALE)**:
   eTran effettua l'instradamento dei pacchetti in eBPF tramite l'helper di kernel `bpf_fib_lookup`. Per farlo con successo, **la tabella ARP del kernel deve già conoscere il MAC address del peer**.
   *Prima di avviare qualsiasi benchmark con eTran, esegui sempre un ping di riscaldamento tra tutti i client e server*:
   ```bash
   ping -c 5 <IP_DEL_PEER>
   ```
   *Senza questo passaggio preliminare, eTran scarterà silenziosamente i pacchetti in quanto `bpf_fib_lookup` fallirà nel trovare il MAC del destinatario.*

---

## 6. Fase 4: Esecuzione delle Misure con eTran

### Configurazione di Rete Preliminare
Su ogni nodo, configurare le interfacce Mellanox (es. `eth2` o l'interfaccia a 25 Gbps) con IP statici sulla stessa sottorete (es. `192.168.6.X`).
Disabilitare l'interrupt coalescing come specificato nel paper per ridurre al minimo la latenza:
```bash
sudo ethtool -C <interface_name> rx-usecs 0 tx-usecs 0
```
Assicurarsi che la MTU sia impostata a 1500:
```bash
sudo ip link set dev <interface_name> mtu 1500
```

---

### Misure 1: Microbenchmark Homa (Tabella 2 & RTT / Throughput)

Questo test confronta eTran (Homa) con Linux (Homa).

#### 1. Avviare il Microkernel eTran (su Server e Client):
```bash
cd ~/eTran/eTran/micro_kernel
sudo ./micro_kernel
```
*Lasciare il processo in esecuzione (o avviarlo in un terminale separato/screen).*

#### 2. Esecuzione del Server (Nodo 1):
```bash
cd ~/eTran/eTran/homa_app
ETRAN_PROTO=homa ./cp_node server
```

#### 3. Esecuzione del Client (Nodo 2):
- **Per misurare la latenza a 32B (Target: ~11.8 µs)**:
  ```bash
  ETRAN_PROTO=homa ./cp_node client --first-server 192.168.6.1 --workload 32 --client-max 1 --one-way
  ```
- **Per misurare il throughput a 1MB (Target: ~17.7 Gbps)**:
  ```bash
  ETRAN_PROTO=homa ./cp_node client --first-server 192.168.6.1 --workload 1048576 --client-max 1 --one-way
  ```

---

### Misure 2: Cluster Benchmark Homa (Figure 5 e 6)

Questo benchmark misura il rallentamento (Slowdown) RTT medio e al 99° percentile su un cluster di 10 macchine sotto carichi simulati (W2-W5).

1. Avviare il microkernel su tutti i 10 nodi.
2. Avviare `cp_node` in modalità server su tutti i 10 nodi.
3. Avviare `cp_node` in modalità client su tutti i nodi contemporaneamente specificando il carico di lavoro:
   ```bash
   # Esempio per il Workload W2 (dominato da messaggi piccoli)
   ETRAN_PROTO=homa ./cp_node client --workload W2 --client-max 10
   ```
   Gli script all'interno di `homa_app` (come `dist.cc`) si occupano di generare i messaggi secondo la distribuzione empirica. Calcolare la latenza slowdown dividendo il RTT osservato per il RTT ideale (tempo di trasmissione teorico sul link a 25Gbps).

---

### Misure 3: Throughput TCP (Figura 7)

Questo test confronta eTran (TCP) con Linux (TCP) nativo.

#### 1. Avviare il Microkernel eTran (su Server e Client):
```bash
cd ~/eTran/eTran/micro_kernel
sudo ./micro_kernel
```

#### 2. Avviare il Server TCP (Nodo 1):
```bash
cd ~/eTran/eTran/tcp_app
ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 LD_PRELOAD=../shared_lib/libetran.so ./epoll_server -i 192.168.6.1 -l 100000 -b 100000
```

#### 3. Avviare il Client TCP (Nodo 2):
Variare la dimensione del messaggio (`-l` e `-b`) per tracciare i grafici di Figura 7a (messaggi grandi) e Figura 7b (messaggi piccoli).
```bash
ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=1 ETRAN_NR_NIC_QUEUES=1 LD_PRELOAD=../shared_lib/libetran.so ./epoll_client -i 192.168.6.1 -l 100000 -b 100000
```

---

### Misure 4: Key-Value Store Benchmark (Figura 8)

Questo benchmark valuta le prestazioni complessive con un carico reale (tipo Memcached) all'aumentare dei core di applicazione dedicati.

#### 1. Avviare il Server KVS (Nodo 1):
```bash
cd ~/eTran/eTran/tcp_app
ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=4 ETRAN_NR_NIC_QUEUES=4 LD_PRELOAD=../shared_lib/libetran.so ./flexkvs_server
```
*(Modificare `ETRAN_NR_APP_THREADS` da 1 a 10 per replicare l'asse X di Figura 8a).*

#### 2. Avviare il Client di Benchmark (Nodi 2-6 - usa fino a 5 client fisici per saturare il server):
```bash
ETRAN_PROTO=tcp ETRAN_NR_APP_THREADS=4 ETRAN_NR_NIC_QUEUES=4 LD_PRELOAD=../shared_lib/libetran.so ./flexkvs_bench -i 192.168.6.1 -c 6000 -q 32
```
Questo comando configura 6000 connessioni persistenti per client con un massimo di 32 richieste in volo concorrenti, inviando richieste con distribuzione Zipf (s=0.9) e un rapporto GET:SET di 9:1.

---

## 7. Ottimizzazioni Avanzate per la Latenza (Paper & CloudLab best practices)

Per ottenere i tempi di risposta sub-millisecondo riportati nel paper, è fondamentale applicare alcune configurazioni avanzate sia sul kernel 5.15 (Baseline) che sul kernel 6.6.0 (eTran):

### 1. Risparmio Energetico della CPU (C-States) e Governor
La latenza di wake-up della CPU distrugge le prestazioni di Homa e eTran.
* **Imposta il governor in modalità Performance** su tutti i nodi:
  ```bash
  sudo cpufreq-set -g performance
  # Oppure tramite sysfs:
  echo "performance" | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
  ```
* **Disabilita i C-States profondi** per impedire alla CPU di andare in sleep:
  Aggiungi `intel_idle.max_cstate=0 processor.max_cstate=0 idle=poll` ai parametri di avvio in `/etc/default/grub`:
  ```text
  GRUB_CMDLINE_LINUX_DEFAULT="console=ttyS1,115200 intel_idle.max_cstate=0 processor.max_cstate=0 idle=poll"
  ```
  Esegui `sudo update-grub` e riavvia.

### 2. Configurazione degli Hugepages (Essenziale per TAS/DPDK)
TAS (baseline) si basa su DPDK e richiede l'allocazione delle hugepages per la gestione della memoria in user-space:
* **Alloca Hugepages a runtime** (es. 2048 pagine da 2MB per nodo):
  ```bash
  echo 2048 | sudo tee /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages
  ```
* Rendi la configurazione permanente in `/etc/sysctl.conf`:
  ```text
  vm.nr_hugepages = 2048
  ```

### 3. Abilitazione ECN per DCTCP (Soglia a 70KB)
Come specificato nel paper, DCTCP richiede che l'ECN (Explicit Congestion Notification) sia abilitato e lo switch Mellanox sia configurato con una soglia di marcatura a **70KB**:
* **Abilita ECN a livello kernel**:
  ```bash
  sudo sysctl -w net.ipv4.tcp_ecn=1
  ```

### 4. Zero-Copy e Driver Mellanox (`mlx5`)
eTran si basa sulle prestazioni di Zero-Copy di AF_XDP. 
* Assicurati che l'interfaccia Mellanox stia effettivamente usando il driver modificato `mlx5` del kernel `eTran-linux`:
  ```bash
  ethtool -i <nome_interfaccia>
  ```
  Dovresti vedere la versione del driver corrispondente a quella compilata nel kernel 6.6.0.

### 5. CPU Pinning e Bilanciamento degli Interrupt (IRQ)
Per ottenere latenze e throughput stabili, gli interrupt della scheda di rete e i thread applicativi devono essere rigidamente isolati su core CPU dedicati (affinità dei core CPU):
* **Disabilita il servizio irqbalance** per evitare che il sistema sposti gli interrupt tra i vari core in modo dinamico:
  ```bash
  sudo systemctl stop irqbalance
  sudo systemctl disable irqbalance
  ```
* **Associa l'interrupt della NIC ad un core dedicato**:
  Trova i numeri di IRQ per la tua scheda di rete Mellanox (`/proc/interrupts`) e associa l'affinità (es. al core 1):
  ```bash
  # Esempio: assegna IRQ al core 1
  echo 2 | sudo tee /proc/irq/<IRQ_NUMBER>/smp_affinity
  ```
* **Usa `taskset`** per forzare l'esecuzione dell'applicazione client/server su core separati rispetto a quelli che gestiscono gli interrupt (NAPI):
  ```bash
  # Esegui il server sul core 2 (isolato)
  taskset -c 2 ./epoll_server ...
  ```

### 6. Configurazione delle Code della NIC (Multi-Queue vs Single-Queue)
Nel paper, gli autori utilizzano `ETRAN_NR_NIC_QUEUES=1` (coda singola) per i test a thread singolo (per massimizzare la cache locality ed evitare l'overhead del multi-queue) e `ETRAN_NR_NIC_QUEUES=4` (o più) per il Key-Value Store multi-core.
* **Imposta il numero corretto di code combinate** prima di avviare il microkernel:
  ```bash
  # Forza la NIC ad utilizzare una sola coda per i microbenchmark
  sudo ethtool -L <nome_interfaccia> combined 1
  
  # Imposta 4 code per i test del Key-Value Store (Figura 8)
  sudo ethtool -L <nome_interfaccia> combined 4
  ```

### 7. Verifica della Velocità di Collegamento (25 Gbps)
I nodi `xl170` su CloudLab montano porte a 25 Gbps, ma talvolta negoziano velocità inferiori (10 Gbps) a causa del cablaggio o dello switch. Verifica sempre la velocità reale negoziata prima di trarre conclusioni sulle prestazioni:
```bash
sudo ethtool <nome_interfaccia> | grep "Speed"
# Dovrebbe mostrare: Speed: 25000Mb/s
```
