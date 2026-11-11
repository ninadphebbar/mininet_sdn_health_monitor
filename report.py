"""Aggregate results.csv into comparison tables (pure Python)."""
import csv
import math

KEYS = ["loss_pct", "lat_avg_ms", "lat_p95_ms", "lat_max_ms", "jitter_ms"]


def load_rows(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            for k, v in r.items():
                if k not in ("mode", "load"):
                    try:
                        r[k] = float(v)
                    except (TypeError, ValueError):
                        r[k] = float("nan")
            rows.append(r)
    return rows


def _mean(vals):
    vals = [v for v in vals if not math.isnan(v)]
    return sum(vals) / len(vals) if vals else float("nan")


def aggregate(rows, columns):
    """{(load, mode): {column: mean over runs}} plus run counts."""
    groups = {}
    for r in rows:
        groups.setdefault((r["load"], r["mode"]), []).append(r)
    return {k: dict({c: _mean([r.get(c, float("nan")) for r in g]) for c in columns},
                    runs=len(g)) for k, g in groups.items()}


def _fmt(v, nd=2):
    return "n/a" if v is None or math.isnan(v) else ("%.*f" % (nd, v))


def markdown(rows, layer="wire", window="steady", load_order=None, mode_order=None):
    cols = ["%s_%s_%s" % (layer, window, k) for k in KEYS] + ["bg_mbps"]
    agg = aggregate(rows, cols)
    loads = load_order or sorted({k[0] for k in agg})
    modes = mode_order or sorted({k[1] for k in agg})
    out = ["| load | mode | runs | loss % | avg latency ms | p95 latency ms | max latency ms "
           "| jitter ms | background Mbit/s |",
           "|---|---|---|---|---|---|---|---|---|"]
    for ld in loads:
        for m in modes:
            a = agg.get((ld, m))
            if not a:
                continue
            c = lambda k: _fmt(a["%s_%s_%s" % (layer, window, k)])
            out.append("| %s | %s | %d | %s | %s | %s | %s | %s | %s |" % (
                ld, m, a["runs"], c("loss_pct"), c("lat_avg_ms"), c("lat_p95_ms"),
                c("lat_max_ms"), c("jitter_ms"), _fmt(a["bg_mbps"], 1)))
    return "\n".join(out)


def full_report(rows, load_order=None, mode_order=None):
    parts = ["# Benchmark summary (mean over runs)\n"]
    for layer, lname in (("wire", "TShark capture, sender NIC -> monitor NIC"),
                         ("app", "application timestamps")):
        for window, wname in (("steady", "steady state (after the SDN reaction period)"),
                              ("load", "whole load window (includes SDN reaction time)")):
            parts.append("## %s - %s\n" % (lname, wname))
            parts.append(markdown(rows, layer, window, load_order, mode_order) + "\n")
    return "\n".join(parts)
