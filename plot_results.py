#!/usr/bin/env python3
"""Turn results/results.csv into charts + results/summary.md.

    python3 scripts/plot_results.py [--results results] [--layer wire]

Produces in <results>/plots/:
  loss.png, latency.png, jitter.png      grouped bars: load x controller mode
  timeline_<load>.png                    per-packet delay over time (run 1),
                                         baseline vs prioritized, load window shaded
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from sdnperf import report  # noqa: E402

COLORS = {"baseline": "#d95f02", "priority": "#1b9e77", "dynamic": "#7570b3"}
LABELS = {"baseline": "SDN, no prioritization (baseline)",
          "priority": "SDN, static telemetry priority",
          "dynamic": "SDN, dynamic priority on congestion"}


def bars(plt, agg, loads, modes, key, ylabel, title, path):
    fig, ax = plt.subplots(figsize=(8, 4.2))
    w = 0.8 / max(1, len(modes))
    for j, m in enumerate(modes):
        xs = [i + j * w - 0.4 + w / 2 for i in range(len(loads))]
        ys = [agg.get((ld, m), {}).get(key, float("nan")) for ld in loads]
        ax.bar(xs, ys, w * 0.92, label=LABELS.get(m, m), color=COLORS.get(m))
    ax.set_xticks(range(len(loads)))
    ax.set_xticklabels(loads)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def timeline(plt, results, load, modes, path):
    fig, ax = plt.subplots(figsize=(9, 4.2))
    shaded = False
    for m in modes:
        d = os.path.join(results, "raw", "%s_%s_run1" % (m, load))
        try:
            meta = json.load(open(d + "/meta.json"))
            sent = {}
            with open(d + "/sent_1.csv") as f:
                for r in csv.DictReader(f):
                    sent[int(r["seq"])] = float(r["send_ts"])
            xs, ys = [], []
            with open(d + "/recv.csv") as f:
                for r in csv.DictReader(f):
                    if int(r["node"]) == 1:
                        xs.append(float(r["send_ts"]) - meta["t_send0"])
                        ys.append((float(r["recv_ts"]) - float(r["send_ts"])) * 1000)
        except (OSError, ValueError, KeyError):
            continue
        ax.plot(xs, ys, ".", ms=3, label=LABELS.get(m, m), color=COLORS.get(m))
        if not shaded:
            ax.axvspan(meta["t_bg0"] - meta["t_send0"], meta["t_bg1"] - meta["t_send0"],
                       color="0.9", zorder=0, label="background load on")
            shaded = True
    ax.set_xlabel("time since first telemetry packet (s)")
    ax.set_ylabel("one-way delay (ms)")
    ax.set_yscale("log")
    ax.set_title("Telemetry delay over time - background load: %s" % load)
    ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                      "..", "results"))
    ap.add_argument("--layer", choices=["wire", "app"], default="wire")
    ap.add_argument("--window", choices=["steady", "load"], default="steady")
    a = ap.parse_args()

    rows = report.load_rows(os.path.join(a.results, "results.csv"))
    loads = [l for l in ("idle", "udp_half", "udp_sat", "tcp_sat") if any(r["load"] == l for r in rows)]
    modes = [m for m in ("baseline", "priority", "dynamic") if any(r["mode"] == m for r in rows)]
    open(os.path.join(a.results, "summary.md"), "w").write(report.full_report(rows, loads, modes))
    print("wrote", os.path.join(a.results, "summary.md"))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed - skipped plots (sudo apt install python3-matplotlib)")
        return
    pre = "%s_%s_" % (a.layer, a.window)
    cols = [pre + k for k in report.KEYS]
    agg = report.aggregate(rows, cols)
    out = os.path.join(a.results, "plots")
    os.makedirs(out, exist_ok=True)
    src = {"wire": "TShark capture", "app": "app timestamps"}[a.layer]
    sub = "%s, %s" % (src, a.window)
    bars(plt, agg, loads, modes, pre + "loss_pct", "packet loss (%)",
         "Telemetry packet loss (%s)" % sub, out + "/loss.png")
    bars(plt, agg, loads, modes, pre + "lat_p95_ms", "95th percentile one-way delay (ms)",
         "Telemetry delivery latency, p95 (%s)" % sub, out + "/latency.png")
    bars(plt, agg, loads, modes, pre + "jitter_ms", "jitter, RFC 3550 (ms)",
         "Telemetry jitter (%s)" % sub, out + "/jitter.png")
    for ld in loads:
        if ld != "idle":
            timeline(plt, a.results, ld, modes, out + "/timeline_%s.png" % ld)
    print("wrote plots to", out)


if __name__ == "__main__":
    main()
