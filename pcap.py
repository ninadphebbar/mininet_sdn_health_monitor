"""Extract telemetry packets from a capture and compute wire-level metrics.

Two back ends give identical output:
  * ``tshark``  - Wireshark's CLI (default when installed); this is the
                  "Wireshark/TShark measurement" required by the project.
  * ``python``  - tiny built-in classic-pcap reader (no dependencies); used as
                  a fallback and in the unit tests.

Method: capture on the *sender's* NIC (packet leaves the host, before the
congested link) and on the *monitoring server's* NIC (after it). Matching the
two captures on (node_id, seq) gives per-packet one-way delay and exact loss,
independent of the application's own bookkeeping.
"""
import shutil
import struct
import subprocess

from . import metrics, packet

# ---------------------------------------------------------------- python reader

def _read_pcap_python(path, port):
    out = []
    with open(path, "rb") as f:
        gh = f.read(24)
        if len(gh) < 24:
            return out
        magic = gh[:4]
        if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
            end, nano = "<", magic == b"\x4d\x3c\xb2\xa1"
        elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
            end, nano = ">", magic == b"\xa1\xb2\x3c\x4d"
        else:
            raise ValueError("%s: not a classic pcap (capture with -F pcap)" % path)
        linktype = struct.unpack(end + "I", gh[20:24])[0]
        l2 = {1: 14, 113: 16, 101: 0, 12: 0}.get(linktype)
        if l2 is None:
            raise ValueError("unsupported link type %d" % linktype)
        while True:
            ph = f.read(16)
            if len(ph) < 16:
                break
            sec, frac, incl, _orig = struct.unpack(end + "IIII", ph)
            frame = f.read(incl)
            ts = sec + frac / (1e9 if nano else 1e6)
            p = l2
            if linktype in (1, 113):
                etype = struct.unpack("!H", frame[p - 2:p])[0]
                if etype == 0x8100 and linktype == 1:       # VLAN tag
                    p += 4
                    etype = struct.unpack("!H", frame[p - 2:p])[0]
                if etype != 0x0800:
                    continue
            if len(frame) < p + 20 or frame[p] >> 4 != 4:
                continue
            ihl = (frame[p] & 0x0F) * 4
            if frame[p + 9] != 17:
                continue
            u = p + ihl
            if len(frame) < u + 8:
                continue
            dport = struct.unpack("!H", frame[u + 2:u + 4])[0]
            if dport != port:
                continue
            hdr = packet.parse_header(frame[u + 8:])
            if hdr:
                out.append((ts,) + hdr)          # (ts, node_id, seq, send_ts)
    return out


# ---------------------------------------------------------------- tshark reader

def _read_pcap_tshark(path, port):
    cmd = ["tshark", "-r", path, "-d", "udp.port==%d,data" % port,
           "-Y", "udp.dstport==%d" % port, "-T", "fields",
           "-E", "separator=/t", "-e", "frame.time_epoch", "-e", "data.data"]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if res.returncode != 0:
        raise RuntimeError("tshark failed: " + res.stderr.strip()[:300])
    out = []
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or not parts[1]:
            continue
        raw = bytes.fromhex(parts[1].replace(":", "").replace(" ", ""))
        hdr = packet.parse_header(raw)
        if hdr:
            out.append((float(parts[0]),) + hdr)
    return out


def read_packets(path, port, parser="auto"):
    """Return [(capture_ts, node_id, seq, send_ts), ...] for telemetry datagrams."""
    if parser == "auto":
        parser = "tshark" if shutil.which("tshark") else "python"
    if parser == "tshark":
        return _read_pcap_tshark(path, port)
    return _read_pcap_python(path, port)


# ---------------------------------------------------------------- wire metrics

def wire_summary(tx_pcap, rx_pcap, port, node_id=None, windows=None, parser="auto"):
    """Match sender-side and receiver-side captures and summarize each window.

    windows: {"name": (t0, t1)} on the sender capture clock.
    returns {"name": summary_dict}
    """
    tx = read_packets(tx_pcap, port, parser)
    rx = read_packets(rx_pcap, port, parser)
    if node_id is not None:
        tx = [p for p in tx if p[1] == node_id]
        rx = [p for p in rx if p[1] == node_id]
    sent = [(seq, ts) for ts, _n, seq, _s in tx]
    send_ts = dict(sent)
    recv = [(seq, send_ts.get(seq, ts), ts) for ts, _n, seq, _s in rx]
    windows = windows or {"all": (None, None)}
    return {name: metrics.summarize(sent, recv, a, b)
            for name, (a, b) in windows.items()}
