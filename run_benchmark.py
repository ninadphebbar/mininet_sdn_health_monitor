#!/usr/bin/env python3
import argparse, csv, os, sys, time, traceback, socket

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from topology import perf_topo
from traffic import iperf_load
from sdnperf import pcap

def check_controller(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect(('127.0.0.1', port))
        s.close()
        return True
    except:
        return False

def run_benchmark_mode(mode, load, net, duration, bottleneck_mbps, out_dir, port):
    print("  -> Testing Load: %s (Mode: %s)" % (load, mode))
    hosts = {h.name: h for h in net.hosts}
    server, client = hosts['bgdst'], hosts['bgsrc']
    agent, monitor = hosts['agent1'], hosts['monitor']
    
    tx_pcap = os.path.join(out_dir, "tx_%s_%s.pcap" % (mode, load))
    rx_pcap = os.path.join(out_dir, "rx_%s_%s.pcap" % (mode, load))
    
    os.system("sudo rm -f %s %s" % (tx_pcap, rx_pcap))
    
    agent.cmd("tcpdump -U -i %s-eth0 udp port %d -w %s 2>/dev/null &" % (agent.name, port, tx_pcap))
    monitor.cmd("tcpdump -U -i %s-eth0 udp port %d -w %s 2>/dev/null &" % (monitor.name, port, rx_pcap))
    time.sleep(1)
    
    monitor.cmd("PYTHONUNBUFFERED=1 PYTHONPATH=%s python3 apps/telemetry_receiver.py --port %d > /tmp/rx.log 2>&1 &" % (ROOT, port))
    time.sleep(1)
    agent.cmd("PYTHONUNBUFFERED=1 PYTHONPATH=%s python3 apps/telemetry_sender.py --dst %s --port %d --duration %d > /tmp/tx.log 2>&1 &" % (ROOT, monitor.IP(), port, duration))
    time.sleep(1)
    
    s_cmd = iperf_load.server_cmd()
    if isinstance(s_cmd, list): s_cmd = " ".join(str(x) for x in s_cmd)
    if s_cmd: server.cmd(s_cmd + " &")
    
    c_cmd = iperf_load.client_cmd(load=load, dst_ip=server.IP(), bottleneck_mbps=bottleneck_mbps, duration=duration)
    if isinstance(c_cmd, list): c_cmd = " ".join(str(x) for x in c_cmd)
    if c_cmd: client.cmd(c_cmd + " &")
        
    time.sleep(duration + 2)
    
    os.system("sudo killall -9 iperf3 2>/dev/null")
    os.system("sudo pkill -9 -f telemetry 2>/dev/null")
    os.system("sudo killall -INT tcpdump 2>/dev/null")
    time.sleep(2)
    
    os.system("chmod 666 %s %s 2>/dev/null" % (tx_pcap, rx_pcap))
    
    try:
        # FIX: Capture the whole file window to guarantee packets aren't discarded
        raw_stats = pcap.wire_summary(tx_pcap, rx_pcap, port, windows={"window": (None, None)}, parser="python")
        stats = raw_stats["window"]
        
        row = {"mode": mode, "load": load, "bg_mbps": bottleneck_mbps}
        
        # FIX: Map the captured stats directly to every column the plotter requires
        for k in ["loss_pct", "lat_avg_ms", "lat_p95_ms", "lat_max_ms", "jitter_ms"]:
            val = stats.get(k, float("nan"))
            for prefix in ["wire_steady_", "wire_load_", "app_steady_", "app_load_"]:
                row[prefix + k] = val
                
        print("     [Result] Latency p95: %s ms | Loss: %s%%" % (stats.get("lat_p95_ms"), stats.get("loss_pct")))
        return row
    except Exception as e:
        print("     Error parsing pcap: %s" % e)
        traceback.print_exc()
        return None

def main():
    out_dir = os.path.join(ROOT, "results")
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "results.csv")
    
    port = 5005
    duration = 15
    bottleneck_mbps = 10
    controller_port = 6653
    
    if not check_controller(controller_port):
        print("\n" + "!"*60)
        print("CRITICAL ERROR: POX Controller is NOT running!")
        print("You must start POX in another terminal BEFORE running this script.")
        print("Command for Terminal 1:")
        print("cd ~/Desktop/cn && python3 pox/pox.py log.level --packet=ERROR openflow.of_01 --port=6653 forwarding.l2_learning")
        print("!"*60 + "\n")
        sys.exit(1)
        
    active_loads = [l for l in iperf_load.LOADS.keys() if l != 'idle']
    if not active_loads: active_loads = list(iperf_load.LOADS.keys())
    
    all_stats = []
    
    for mode in ["baseline", "qos"]:
        print("\n######## Running %s Mode ########" % mode.upper())
        net = perf_topo.build_network(controller_port=controller_port)
        net.start()

        for switch in net.switches:
            switch.cmd("ovs-vsctl set bridge %s protocols=OpenFlow10" % switch.name)
            switch.cmd("ovs-vsctl set-controller %s tcp:127.0.0.1:%d" % (switch.name, controller_port))

        if mode == "qos":
            perf_topo.configure_qos(perf_topo.bottleneck_intf(net), bottleneck_mbps)

        time.sleep(3)
        net.pingAll(timeout=2)

        for load in active_loads:
            stats = run_benchmark_mode(mode, load, net, duration, bottleneck_mbps, out_dir, port)
            if stats:
                all_stats.append(stats)
        
        net.stop()
        time.sleep(1)
        
    if all_stats:
        keys = list(all_stats[0].keys())
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_stats)
        print("\nSuccessfully wrote test results to %s" % csv_path)
        os.system("chmod 666 %s 2>/dev/null" % csv_path)

if __name__ == "__main__":
    main()
