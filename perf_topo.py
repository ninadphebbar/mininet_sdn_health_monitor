#!/usr/bin/env python3
"""Mininet topology + Open vSwitch QoS for the congestion experiments.

    agent1..agentN ─┐
                    ├─ s1 ══════ s2 ─┬─ monitor  (10.0.0.3, telemetry server)
    bgsrc ──────────┘  bottleneck    └─ bgdst    (10.0.0.4, iperf3 server)
    (10.0.0.2, iperf3 client)  (default 10 Mbit/s)

The bottleneck is s1's egress port towards s2. It is rate-limited by an Open
vSwitch ``linux-htb`` QoS object with two queues, so the *same* link and the
*same* queues exist in every experiment - only the controller's behaviour
(which queue a packet is steered into) changes:

    queue 0  best effort : max = bottleneck, min 1 Mbit/s, lower priority
    queue 1  telemetry   : max = bottleneck, min 2 Mbit/s, higher priority

Manual use (opens the Mininet CLI; start a controller first):
    sudo python3 topology/perf_topo.py --cli --agents 2
"""
import argparse
import subprocess
from functools import partial

from mininet.cli import CLI
from mininet.link import Link
from mininet.log import info, setLogLevel
from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController
from mininet.topo import Topo

BG_SRC_IP, MONITOR_IP, BG_DST_IP = "10.0.0.2", "10.0.0.3", "10.0.0.4"


def agent_ip(i):                       # agent1 -> 10.0.0.11 ...
    return "10.0.0.%d" % (10 + i)


class PerfTopo(Topo):
    def build(self, agents=1):
        s1 = self.addSwitch("s1")
        s2 = self.addSwitch("s2")
        for i in range(1, agents + 1):
            self.addLink(self.addHost("agent%d" % i, ip=agent_ip(i) + "/24"), s1)
        self.addLink(self.addHost("bgsrc", ip=BG_SRC_IP + "/24"), s1)
        self.addLink(s1, s2)                                   # the bottleneck
        self.addLink(self.addHost("monitor", ip=MONITOR_IP + "/24"), s2)
        self.addLink(self.addHost("bgdst", ip=BG_DST_IP + "/24"), s2)


def build_network(agents=1, controller_ip="127.0.0.1", controller_port=6653):
    net = Mininet(topo=PerfTopo(agents=agents),
                  switch=partial(OVSSwitch, protocols="OpenFlow13"),
                  controller=None, link=Link, autoSetMacs=True, waitConnected=False)
    net.addController("c0", controller=RemoteController,
                      ip=controller_ip, port=controller_port)
    return net


def bottleneck_intf(net):
    """Name of s1's interface facing s2 (e.g. 's1-eth3')."""
    s1, s2 = net.get("s1"), net.get("s2")
    return s1.connectionsTo(s2)[0][0].name


def _vsctl(*args):
    subprocess.run(["ovs-vsctl"] + list(args), check=True)


def configure_qos(intf, mbps=10.0, tele_min_mbps=2.0, be_min_mbps=1.0):
    """Shape ``intf`` to ``mbps`` with a best-effort and a telemetry queue."""
    cap = str(int(mbps * 1e6))
    _vsctl("--", "set", "port", intf, "qos=@qos",
           "--", "--id=@qos", "create", "qos", "type=linux-htb",
           "other-config:max-rate=" + cap, "queues:0=@q0", "queues:1=@q1",
           "--", "--id=@q0", "create", "queue",
           "other-config:min-rate=%d" % int(be_min_mbps * 1e6),
           "other-config:max-rate=" + cap, "other-config:priority=1",
           "--", "--id=@q1", "create", "queue",
           "other-config:min-rate=%d" % int(tele_min_mbps * 1e6),
           "other-config:max-rate=" + cap, "other-config:priority=0")
    info("*** QoS on %s: %.1f Mbit/s, q0=best-effort q1=telemetry\n" % (intf, mbps))


def clear_qos(intf):
    subprocess.run(["ovs-vsctl", "clear", "port", intf, "qos"], check=False)
    subprocess.run(["ovs-vsctl", "--all", "destroy", "qos"], check=False)
    subprocess.run(["ovs-vsctl", "--all", "destroy", "queue"], check=False)


def start_network(net, mbps, warmup=True):
    """net.start(), wait for the controller, shape the bottleneck, learn MACs."""
    net.start()
    if not net.waitConnected(timeout=30):
        raise RuntimeError("switches did not connect to the controller on %s:%d - is it running?"
                           % (net.controllers[0].ip, net.controllers[0].port))
    configure_qos(bottleneck_intf(net), mbps)
    if warmup:
        net.pingAll(timeout=2)         # lets the controller learn every host
    return bottleneck_intf(net)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agents", type=int, default=1)
    ap.add_argument("--bottleneck-mbps", type=float, default=10.0)
    ap.add_argument("--controller-ip", default="127.0.0.1")
    ap.add_argument("--controller-port", type=int, default=6653)
    ap.add_argument("--cli", action="store_true", help="open the Mininet CLI")
    a = ap.parse_args()
    setLogLevel("info")
    net = build_network(a.agents, a.controller_ip, a.controller_port)
    try:
        intf = start_network(net, a.bottleneck_mbps)
        info("*** bottleneck interface: %s\n" % intf)
        if a.cli:
            CLI(net)
    finally:
        net.stop()


if __name__ == "__main__":
    main()
