#!/usr/bin/env python3
"""UDP health-telemetry agent (the "monitored server").

Sends one datagram every 1/rate seconds carrying CPU, memory, process-count
and network counters. Every datagram carries a sequence number and send time
so loss / latency / jitter can be computed downstream.

    python3 apps/telemetry_sender.py --dst 10.0.0.3 --port 9901 --rate 50 \
            --duration 30 --node-id 1 --out sent_1.csv
"""
import argparse
import os
import signal
import socket
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from sdnperf import packet  # noqa: E402


def _cpu_times():
    with open("/proc/stat") as f:
        v = [int(x) for x in f.readline().split()[1:]]
    return sum(v), v[3] + (v[4] if len(v) > 4 else 0)       # total, idle(+iowait)


def collect(prev):
    """Real host statistics from /proc (Mininet hosts share the VM's kernel)."""
    total, idle = _cpu_times()
    cpu = 0.0
    if prev and total > prev[0]:
        cpu = 100.0 * (1 - (idle - prev[1]) / (total - prev[0]))
    mem = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":")
            mem[k] = int(v.split()[0])
    used = 100.0 * (1 - mem["MemAvailable"] / mem["MemTotal"])
    procs = sum(1 for d in os.listdir("/proc") if d.isdigit())
    rx = tx = 0
    with open("/proc/net/dev") as f:
        for line in list(f)[2:]:
            name, rest = line.split(":")
            if name.strip() != "lo":
                c = rest.split()
                rx, tx = rx + int(c[0]), tx + int(c[8])
    return (total, idle), {"cpu": round(cpu, 1), "mem": round(used, 1),
                           "procs": procs, "net_rx": rx, "net_tx": tx}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dst", required=True, help="monitoring-server IP")
    ap.add_argument("--port", type=int, default=9901)
    ap.add_argument("--rate", type=float, default=50, help="packets per second")
    ap.add_argument("--duration", type=float, default=30, help="seconds")
    ap.add_argument("--node-id", type=int, default=1)
    ap.add_argument("--size", type=int, default=200, help="pad datagram to N bytes")
    ap.add_argument("--out", help="CSV of (node,seq,send_ts) actually sent")
    ap.add_argument("--synthetic", action="store_true",
                    help="send fake stats instead of reading /proc")
    ap.add_argument("--dscp", type=int, default=0,
                    help="optional DSCP marking (e.g. 46 = EF); controller matches on port")
    a = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if a.dscp:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, a.dscp << 2)
    dst = (a.dst, a.port)

    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(flag=True))

    interval = 1.0 / a.rate
    n_total = int(a.duration * a.rate)
    sent = []
    prev, body, last_stats = None, {}, 0.0
    start = time.time()
    for seq in range(n_total):
        target = start + seq * interval
        delay = target - time.time()
        if delay > 0:
            time.sleep(delay)
        if stop["flag"]:
            break
        now = time.time()
        if now - last_stats >= 1.0:                      # refresh stats once a second
            if a.synthetic:
                body = {"cpu": 10 + seq % 40, "mem": 40.0, "procs": 120,
                        "net_rx": seq * 100, "net_tx": seq * 100}
            else:
                prev, body = collect(prev)
            last_stats = now
        ts = time.time()
        sock.sendto(packet.build(seq, a.node_id, body, send_ts=ts, pad_to=a.size), dst)
        sent.append((a.node_id, seq, ts))

    if a.out:
        with open(a.out, "w") as f:
            f.write("node,seq,send_ts\n")
            f.writelines("%d,%d,%.9f\n" % r for r in sent)
    print("[sender node=%d] sent %d datagrams to %s:%d" % (a.node_id, len(sent), a.dst, a.port),
          flush=True)


if __name__ == "__main__":
    main()
