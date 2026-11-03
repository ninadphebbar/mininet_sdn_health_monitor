#!/usr/bin/env python3
"""Centralized monitoring server: receives telemetry datagrams.

* writes every datagram to a CSV (node,seq,send_ts,recv_ts)
* prints a one-line live status every --interval seconds (loss, latency, jitter)
  so a viewer can watch what the SDN prioritization does during the demo.

Stop with Ctrl-C / SIGTERM; the CSV is flushed on exit.

    python3 apps/telemetry_receiver.py --port 9901 --out recv.csv --expected-pps 50
"""
import argparse
import os
import signal
import socket
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from sdnperf import metrics, packet  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=9901)
    ap.add_argument("--out", help="CSV file (node,seq,send_ts,recv_ts)")
    ap.add_argument("--interval", type=float, default=1.0, help="live status period (s)")
    ap.add_argument("--expected-pps", type=float, default=0,
                    help="total expected packets/s (all agents) for the live loss figure")
    ap.add_argument("--expected-duration", type=float, default=0,
                    help="seconds of traffic expected; live lines stop afterwards (0 = never)")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    sock.bind((a.bind, a.port))
    sock.settimeout(0.2)

    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(flag=True))

    rows = []
    win_transit = []                      # transit times (s) received in this window
    win_n = 0
    t_begin = None                        # clock starts at the first datagram
    next_tick = None
    malformed = 0
    print("[receiver] listening on %s:%d" % (a.bind, a.port), flush=True)

    while not stop["flag"]:
        try:
            data, _addr = sock.recvfrom(65535)
        except socket.timeout:
            data = None
        now = time.time()
        if data is not None:
            p = packet.parse(data)
            if p is None:
                malformed += 1
            else:
                seq, send_ts, node, _body = p
                if t_begin is None:
                    t_begin, next_tick = now, now + a.interval
                rows.append((node, seq, send_ts, now))
                win_transit.append(now - send_ts)
                win_n += 1
        if next_tick is not None and now >= next_tick:
            active = not a.expected_duration or next_tick - t_begin <= a.expected_duration + 1e-6
            if not a.quiet and active:
                if win_transit:
                    lat = [t * 1000 for t in win_transit]
                    lat_s = "lat avg %7.2f ms  p95 %7.2f ms  max %7.2f ms  jitter %6.2f ms" % (
                        sum(lat) / len(lat), metrics.percentile(lat, 95), max(lat),
                        metrics.rfc3550_jitter(win_transit) * 1000)
                else:
                    lat_s = "lat      n/a (no packets arrived)"
                if a.expected_pps:
                    exp = a.expected_pps * a.interval
                    loss = max(0.0, 100.0 * (1 - win_n / exp))
                    loss_s = "rx %4d/%-4d loss %5.1f%%" % (win_n, round(exp), loss)
                else:
                    loss_s = "rx %4d" % win_n
                print("[t=%5.1fs] %s | %s" % (now - t_begin, loss_s, lat_s), flush=True)
            win_transit, win_n = [], 0
            next_tick += a.interval

    if a.out:
        with open(a.out, "w") as f:
            f.write("node,seq,send_ts,recv_ts\n")
            f.writelines("%d,%d,%.9f,%.9f\n" % r for r in rows)
    print("[receiver] done: %d datagrams, %d malformed" % (len(rows), malformed), flush=True)


if __name__ == "__main__":
    main()
