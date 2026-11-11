"""iperf3 background-load definitions used to create congestion.

A "load" is a named scenario expressed as a fraction of the bottleneck
capacity, so the experiments scale if you change ``--bottleneck-mbps``.

    idle      no background traffic (reference)
    udp_half  UDP at 50 % of capacity            - link busy, not saturated
    udp_sat   UDP at 200 % of capacity           - link saturated, drops guaranteed
    tcp_sat   4 parallel TCP streams             - elastic traffic fills the queue

Manual equivalents (inside the Mininet CLI):
    bgdst  iperf3 -s -p 5201 &
    bgsrc  iperf3 -c 10.0.0.4 -p 5201 -u -b 20M -t 20       # udp_sat
    bgsrc  iperf3 -c 10.0.0.4 -p 5201 -P 4 -t 20            # tcp_sat
"""
import json

IPERF_PORT = 5201

LOADS = {
    "idle":     None,
    "udp_half": {"proto": "udp", "frac": 0.5, "streams": 1},
    "udp_sat":  {"proto": "udp", "frac": 2.0, "streams": 1},
    "tcp_sat":  {"proto": "tcp", "frac": None, "streams": 4},
}


def server_cmd(port=IPERF_PORT):
    return ["iperf3", "-s", "-1", "-p", str(port)]       # -1: exit after one test


def client_cmd(load, dst_ip, bottleneck_mbps, duration, port=IPERF_PORT):
    """argv for the iperf3 client, or None for the idle scenario."""
    spec = LOADS[load]
    if spec is None:
        return None
    cmd = ["iperf3", "-c", dst_ip, "-p", str(port), "-t", str(int(duration)), "-J"]
    if spec["proto"] == "udp":
        cmd += ["-u", "-b", "%dK" % int(spec["frac"] * bottleneck_mbps * 1000)]
    else:
        cmd += ["-P", str(spec["streams"])]
    return cmd


def parse_result(text, proto):
    """(delivered_mbps, udp_loss_pct) from iperf3 -J client output; NaN on failure.

    UDP: the client reports what it *sent*; delivered = sent * (1 - loss).
    TCP: receiver-side goodput summed over all parallel streams.
    """
    nan = float("nan")
    try:
        end = json.loads(text)["end"]
        if proto == "udp":
            lost = end["sum"]["lost_percent"]
            return end["sum"]["bits_per_second"] / 1e6 * (1 - lost / 100.0), lost
        return end["sum_received"]["bits_per_second"] / 1e6, nan
    except (ValueError, KeyError, TypeError):
        return nan, nan
