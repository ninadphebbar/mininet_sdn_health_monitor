# SDN Network Performance & QoS Health Monitor

An automated Software-Defined Networking (SDN) health monitoring and Quality of Service (QoS) controller system built with Mininet, POX, iperf, and Streamlit. This project demonstrates how dynamic SDN flow prioritization maintains smooth telemetry packet delivery under heavy network saturation and link congestion.

---

## Team Member Contributions & File Ownership

* **Ninad Pramoda Hebbar (Application Developer & Dashboard Lead):**
  * **File Ownership:** `apps/telemetry_sender.py`, `apps/telemetry_receiver.py`, `app.py`, `sdnperf/pcap.py`
  * **Contributions:** Built the interactive Streamlit dashboard (`app.py`), telemetry sender/receiver applications, process-level stats collection (`psutil`), heartbeat failure detection, and dynamic `"priority": "HIGH"` JSON payload tagging.

* **Mridul Panicker (SDN & Control Plane Engineer):**
  * **File Ownership:** `controller/qos_controller.py`, `topology/perf_topo.py`
  * **Contributions:** Configured the POX SDN controller (`qos_controller.py`) to install high-priority OpenFlow rules on switch `s1` for telemetry traffic, implemented link failure detection (`ofp_port_status`), and automated path rerouting.

* **Nishanth Allena (Network Performance & Traffic Engineer):**
  * **File Ownership:** `traffic/iperf_load.py`, `scripts/run_benchmark.py`, `scripts/plot_results.py`, `sdnperf/report.py`
  * **Contributions:** Created background `iperf` saturation load scripts, automated the benchmark execution suite (`run_benchmark.py`), handled TShark/Wireshark PCAP capture metrics processing, and generated comparative plot visualizations.

---

## Project Architecture & Directory Structure

```text
sdn-network-performance/
├── apps/
│   ├── telemetry_sender.py      # Telemetry probe generator (Agent)
│   └── telemetry_receiver.py    # Telemetry server & heartbeat monitor
├── controller/
│   └── qos_controller.py        # POX OpenFlow QoS controller logic
├── topology/
│   └── perf_topo.py             # Custom Mininet network topology
├── traffic/
│   └── iperf_load.py            # Background network saturation generator
├── scripts/
│   ├── run_benchmark.py         # Automated test runner (Baseline vs QoS)
│   └── plot_results.py          # Comparative plotting script
├── sdnperf/
│   ├── pcap.py                  # PCAP file parsing & latency metrics
│   └── report.py                # CSV metrics summary exporter
├── docs/                        # Proof-of-work screenshots
├── app.py                       # Interactive Streamlit Web Dashboard
├── results/                     # Output metrics (results.csv & plots)
└── README.md                    # Project documentation

How to Run
1. Start the POX Controller
Run the POX controller with L2 learning and custom QoS routing enabled:
PYTHONPATH=~/Desktop/cn/sdn-network-performance/controller python3 pox/pox.py log.level --packet=ERROR openflow.of_01 --port=6653 forwarding.l2_learning qos_controller
2. Execute the Benchmarking Suite
In a separate terminal, run the automated benchmark runner across Baseline and QoS modes:
sudo mn -c
sudo python3 scripts/run_benchmark.py
3. Generate Comparative Plots & Launch Dashboard
Regenerate the comparative performance graphs and open the Streamlit web dashboard:
python3 scripts/plot_results.py
streamlit run app.py
Access the dashboard in your browser at: http://localhost:8501
