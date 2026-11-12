"""
SDN Network Performance & QoS Health Monitor
============================================
NOC-style Streamlit dashboard for the Computer Networks capstone.

Run :  python3 -m streamlit run app.py
Data:  results/results.csv  (mode, load, wire_steady_lat_p95_ms,
                             wire_steady_jitter_ms, wire_steady_loss_pct)
Deps:  streamlit (>= 1.27), pandas, plotly  -- nothing else.
       (Pandas Styler needs jinja2, which Streamlit already pulls in. If it is
       ever missing, the summary table silently falls back to a plain dataframe.)

Tip:   the page forces a dark look with CSS. For pixel-perfect dark widgets and
       table headers, also pick  Settings -> Theme -> Dark  in the app menu.
"""

import html
import math
import os
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# =============================================================================
# 1. PAGE CONFIG  (must be the first Streamlit call)
# =============================================================================
st.set_page_config(
    layout="wide",
    page_title="SDN QoS Health Monitor",
    page_icon="🌐",
    initial_sidebar_state="expanded",
)

# =============================================================================
# 2. CONSTANTS
# =============================================================================
ROOT = os.path.dirname(os.path.abspath(__file__))
RESULTS_CSV = os.path.join(ROOT, "results", "results.csv")  # unchanged data source
RESULTS_REL = "results/results.csv"
PLOTS_DIR = os.path.join(ROOT, "results", "plots")           # optional legacy PNGs

LAT_COL = "wire_steady_lat_p95_ms"
JIT_COL = "wire_steady_jitter_ms"
LOSS_COL = "wire_steady_loss_pct"
REQUIRED_COLS = ["mode", "load", LAT_COL, JIT_COL, LOSS_COL]
NUMERIC_COLS = [LAT_COL, JIT_COL, LOSS_COL]

# Raw CSV column -> human-readable header used in the summary table
COLUMN_LABELS = {
    "mode": "Forwarding Mode",
    "load": "Background Load",
    LAT_COL: "p95 Latency (ms)",
    JIT_COL: "Jitter (ms)",
    LOSS_COL: "Packet Loss (%)",
}

MODE_ORDER = ["baseline", "qos"]
LOAD_ORDER = ["udp_half", "udp_sat", "tcp_sat"]

# Palette: coral for baseline, cyan for QoS; slate for neutrals, emerald for "healthy"
MODE_STYLE = {"baseline": ("Baseline", "#FB7185"), "qos": ("QoS", "#22D3EE")}
FALLBACK_COLORS = ["#A78BFA", "#FBBF24", "#34D399"]
SLA_LINE_COLOR = "#FBBF24"
FONT_STACK = '"Inter","Segoe UI",system-ui,-apple-system,Roboto,"Helvetica Neue",Arial,sans-serif'

SLA_MIN, SLA_MAX, SLA_DEFAULT = 1.0, 5000.0, 250.0
NO_DATA_MSG = (
    "No telemetry data matches your current filter selection. "
    "Please select at least one Forwarding Mode and Traffic Load."
)

# =============================================================================
# 3. CUSTOM CSS  (dark observability look: cards, badges, tabs, architecture)
# =============================================================================
CSS = """
<style>
:root{
  --noc-bg:#0B1220; --noc-panel:#111B2E; --noc-panel2:#0F172A;
  --noc-border:#1E293B; --noc-border2:#2B3B55;
  --noc-text:#E2E8F0; --noc-muted:#94A3B8; --noc-strong:#F1F5F9;
  --noc-cyan:#22D3EE; --noc-emerald:#10B981; --noc-coral:#FB7185;
  --noc-amber:#FBBF24; --noc-violet:#A78BFA;
  --noc-mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;
}

/* ---- base page ---- */
.stApp{background:var(--noc-bg);color:var(--noc-text);
  font-family:"Inter","Segoe UI",system-ui,-apple-system,Roboto,"Helvetica Neue",Arial,sans-serif;}
[data-testid="stHeader"]{background:transparent;}
[data-testid="stAppDeployButton"], footer{display:none !important;}
.block-container{padding-top:1.6rem;padding-bottom:3rem;max-width:1500px;}
.stApp p, .stApp li, .stApp label, .stApp h1, .stApp h2, .stApp h3, .stApp h4,
.stApp [data-testid="stMarkdownContainer"]{color:var(--noc-text);}
.stApp [data-testid="stCaptionContainer"], .stApp [data-testid="stCaptionContainer"] *{color:var(--noc-muted);}
.stApp code{font-family:var(--noc-mono);background:rgba(34,211,238,.10);color:#A5F3FC;
  padding:.1rem .4rem;border-radius:6px;font-size:.85em;}

/* ---- sidebar ---- */
[data-testid="stSidebar"]{background:var(--noc-panel2);border-right:1px solid var(--noc-border);}
[data-testid="stSidebar"] .block-container, [data-testid="stSidebarContent"]{padding-top:1.2rem;}
.noc-brand{display:flex;align-items:center;gap:12px;margin-bottom:14px;}
.noc-brand-logo{width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;
  font-size:22px;background:linear-gradient(135deg,#0EA5E9,#22D3EE 60%,#10B981);box-shadow:0 6px 18px rgba(34,211,238,.25);}
.noc-brand-title{font-weight:800;font-size:1.05rem;color:var(--noc-strong);letter-spacing:.01em;line-height:1.2;}
.noc-brand-sub{font-size:.74rem;color:var(--noc-muted);letter-spacing:.04em;}
.noc-status{background:var(--noc-panel);border:1px solid var(--noc-border);border-radius:12px;padding:12px 14px;margin-bottom:18px;}
.noc-status-meta{margin-top:9px;font-size:.74rem;color:var(--noc-muted);line-height:1.7;}
.noc-status-meta b{color:var(--noc-text);font-weight:600;}
.noc-side-section{font-size:.7rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;
  color:var(--noc-muted);margin:6px 0 4px 0;}

/* ---- badges ---- */
.noc-badge{display:inline-flex;align-items:center;gap:6px;padding:4px 11px;border-radius:999px;
  font-size:.72rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;white-space:nowrap;border:1px solid transparent;}
.noc-badge .dot{width:7px;height:7px;border-radius:50%;background:currentColor;box-shadow:0 0 8px currentColor;}
.noc-badge-ok{color:#6EE7B7;background:rgba(16,185,129,.16);border-color:rgba(16,185,129,.55);}
.noc-badge-warn{color:#FDE68A;background:rgba(251,191,36,.15);border-color:rgba(251,191,36,.55);}
.noc-badge-bad{color:#FDA4AF;background:rgba(251,113,133,.16);border-color:rgba(251,113,133,.55);}
.noc-badge-info{color:#A5F3FC;background:rgba(34,211,238,.14);border-color:rgba(34,211,238,.5);}
.noc-badge-mute{color:#CBD5E1;background:rgba(148,163,184,.12);border-color:rgba(148,163,184,.35);}

/* ---- header banner ---- */
.noc-banner{display:flex;flex-wrap:wrap;gap:16px;align-items:center;justify-content:space-between;
  background:linear-gradient(120deg,#0B2A4A 0%,#0F172A 55%,#0D2B3E 100%);
  border:1px solid #1E3A5F;border-radius:18px;padding:22px 28px;margin-bottom:20px;
  box-shadow:0 10px 30px rgba(0,0,0,.4), inset 0 1px 0 rgba(255,255,255,.05);}
.noc-banner-title{font-size:1.65rem;font-weight:800;color:var(--noc-strong);letter-spacing:-.01em;line-height:1.2;}
.noc-banner-sub{margin-top:5px;font-size:.88rem;color:var(--noc-muted);}
.noc-banner-badges{display:flex;flex-wrap:wrap;gap:8px;}

/* ---- KPI cards (st.metric) ---- */
[data-testid="stMetric"]{background:linear-gradient(160deg,var(--noc-panel) 0%,var(--noc-panel2) 100%);
  border:1px solid var(--noc-border);border-top:3px solid var(--noc-cyan);border-radius:14px;
  padding:16px 18px 14px 18px;box-shadow:0 8px 24px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.04);}
.stApp [data-testid="stMetricLabel"], .stApp [data-testid="stMetricLabel"] *{color:var(--noc-muted);
  font-size:.72rem;font-weight:700;letter-spacing:.07em;text-transform:uppercase;
  white-space:normal !important;overflow:visible !important;text-overflow:clip !important;line-height:1.3;
  min-height:2.6em;align-items:flex-start;}  /* reserve two lines so all four KPI cards stay equal height */
.stApp [data-testid="stMetricValue"], .stApp [data-testid="stMetricValue"] *{color:var(--noc-strong);
  font-weight:800;font-size:clamp(1.05rem,1.35vw,1.55rem);font-variant-numeric:tabular-nums;
  white-space:nowrap !important;overflow:visible !important;text-overflow:clip !important;}
[data-testid="stMetricDelta"]{display:inline-flex;width:fit-content;padding:2px 10px;margin-top:6px;
  border-radius:999px;background:rgba(148,163,184,.10);font-weight:700;font-size:.78rem;}
[data-testid="stTooltipIcon"] svg{color:var(--noc-muted) !important;stroke:var(--noc-muted) !important;}

/* ---- tabs (react-aria DOM in new Streamlit, baseweb DOM in older releases) ---- */
.stApp [role="tablist"]{gap:6px;border-bottom:1px solid var(--noc-border);}
.stApp [role="tab"]{height:46px;padding:0 18px;border-radius:10px 10px 0 0;
  color:var(--noc-muted);font-weight:600;background:transparent;border-bottom:3px solid transparent;}
.stApp [role="tab"] p{color:inherit;font-weight:600;}
.stApp [role="tab"][aria-selected="true"]{color:var(--noc-strong);background:rgba(34,211,238,.08);
  border-bottom:3px solid var(--noc-cyan);}
[data-baseweb="tab-highlight"]{background:var(--noc-cyan);height:3px;}
[data-baseweb="tab-border"]{background:transparent;}

/* ---- widgets: forced dark so they also look right when the browser/app theme is light ---- */
[data-testid="stSidebar"] [data-baseweb="select"] > div,
[data-testid="stSidebar"] [data-baseweb="input"],
[data-testid="stSidebar"] div[data-rac][role="group"],
[data-testid="stSidebar"] [data-testid="stNumberInputContainer"]{
  background:var(--noc-bg) !important;border:1px solid var(--noc-border2) !important;border-radius:10px;}
[data-testid="stSidebar"] [data-testid="stNumberInputContainer"] > div{background:transparent !important;}
[data-testid="stSidebar"] input{color:var(--noc-text) !important;caret-color:var(--noc-cyan);background:transparent !important;}
[data-testid="stSidebar"] [data-testid="stNumberInputStepUp"],
[data-testid="stSidebar"] [data-testid="stNumberInputStepDown"]{background:transparent !important;color:var(--noc-text) !important;}
[data-testid="stSidebar"] [data-testid="stMultiSelect"] svg,
[data-testid="stSidebar"] [data-testid="stNumberInputContainer"] svg{color:var(--noc-muted);fill:var(--noc-muted);}
[data-tag], [data-baseweb="tag"]{background:rgba(34,211,238,.16) !important;
  border:1px solid rgba(34,211,238,.45) !important;border-radius:8px !important;}
[data-tag] *, [data-baseweb="tag"] *{color:#A5F3FC !important;}
/* dropdown panels are rendered in a portal outside .stApp, so they need explicit dark styling too */
[data-testid="stMultiSelectDropdown"], [data-baseweb="popover"] [role="listbox"],
[data-baseweb="popover"] ul, [data-baseweb="menu"]{
  background:var(--noc-panel) !important;border:1px solid var(--noc-border2);border-radius:10px;color:var(--noc-text) !important;}
[role="option"], [role="option"] *{color:var(--noc-text) !important;}
[role="option"][data-focused="true"], [role="option"][aria-selected="true"]{background:rgba(34,211,238,.14) !important;}
.stButton > button, [data-testid^="stBaseButton"]{border-radius:10px;font-weight:700;}
[data-testid="stSidebar"] .stButton > button{background:linear-gradient(135deg,#0EA5E9,#22D3EE);
  color:#04111F;border:0;box-shadow:0 6px 16px rgba(34,211,238,.22);}
[data-testid="stSidebar"] .stButton > button:hover{filter:brightness(1.08);color:#04111F;}
[data-testid="stSidebar"] .stButton > button p{color:#04111F;font-weight:700;}
[data-testid="stDataFrame"]{border:1px solid var(--noc-border);border-radius:12px;overflow:hidden;}
[data-testid="stExpander"]{border:1px solid var(--noc-border);border-radius:12px;background:var(--noc-panel2);}
[data-testid="stExpander"] summary p{color:var(--noc-text);}

/* ---- alerts: translucent dark panels per severity (default pastel panels are unreadable on dark) ---- */
[data-testid="stAlert"]{border-radius:12px;}
[data-testid="stAlertContainer"]{border-radius:12px;border:1px solid var(--noc-border2);background:var(--noc-panel) !important;}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]){
  background:rgba(251,191,36,.12) !important;border-color:rgba(251,191,36,.45);}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]){
  background:rgba(16,185,129,.13) !important;border-color:rgba(16,185,129,.45);}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]){
  background:rgba(251,113,133,.13) !important;border-color:rgba(251,113,133,.5);}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]){
  background:rgba(34,211,238,.10) !important;border-color:rgba(34,211,238,.4);}
[data-testid="stAlertContainer"] p, [data-testid="stAlertContainer"] strong{color:var(--noc-text) !important;}

/* ---- section titles ---- */
.noc-section{display:flex;align-items:baseline;gap:10px;margin:6px 0 10px 0;font-size:1.02rem;font-weight:700;color:var(--noc-strong);}
.noc-section span{font-size:.75rem;font-weight:600;color:var(--noc-muted);letter-spacing:.06em;text-transform:uppercase;}

/* ---- architecture diagram ---- */
.arch{background:radial-gradient(900px 300px at 50% 0%,rgba(34,211,238,.07),transparent 70%),var(--noc-panel2);
  border:1px solid var(--noc-border);border-radius:18px;padding:26px 22px;margin:6px 0 18px 0;}
.arch-grid{display:grid;grid-template-columns:minmax(0,1fr) 96px minmax(0,1.4fr) 96px minmax(0,1fr);
  grid-template-rows:auto 58px auto 58px auto;align-items:center;}
.g-ctrl{grid-column:3;grid-row:1;} .g-v1{grid-column:3;grid-row:2;}
.g-agent{grid-column:1;grid-row:3;} .g-a1{grid-column:2;grid-row:3;}
.g-sw{grid-column:3;grid-row:3;} .g-a2{grid-column:4;grid-row:3;}
.g-mon{grid-column:5;grid-row:3;} .g-v2{grid-column:3;grid-row:4;} .g-load{grid-column:3;grid-row:5;}
.node{height:100%;box-sizing:border-box;background:linear-gradient(160deg,var(--noc-panel),var(--noc-panel2));
  border:1px solid var(--noc-border2);border-radius:14px;padding:16px 18px;box-shadow:0 8px 22px rgba(0,0,0,.35);}
.node-tag{font-size:.64rem;font-weight:800;letter-spacing:.16em;text-transform:uppercase;color:var(--noc-muted);margin-bottom:6px;}
.node-title{font-size:1.08rem;font-weight:800;color:var(--noc-strong);margin-bottom:4px;}
.node-desc{font-size:.82rem;color:#B6C2D4;line-height:1.5;}
.node-chips{margin-top:9px;display:flex;flex-wrap:wrap;gap:6px;}
.chip{font-family:var(--noc-mono);font-size:.7rem;padding:2px 8px;border-radius:6px;background:rgba(148,163,184,.12);color:#CBD5E1;}
.node.src{border-color:rgba(34,211,238,.55);box-shadow:0 8px 22px rgba(0,0,0,.35),0 0 0 1px rgba(34,211,238,.10);}
.node.src .node-tag{color:var(--noc-cyan);}
.node.sw{border-color:rgba(167,139,250,.65);box-shadow:0 10px 28px rgba(0,0,0,.4),0 0 26px rgba(167,139,250,.14);}
.node.sw .node-tag{color:var(--noc-violet);}
.node.sink{border-color:rgba(16,185,129,.6);} .node.sink .node-tag{color:var(--noc-emerald);}
.node.ctrl{border-style:dashed;border-color:rgba(167,139,250,.55);} .node.ctrl .node-tag{color:var(--noc-violet);}
.node.load{border-style:dashed;border-color:rgba(251,113,133,.6);} .node.load .node-tag{color:var(--noc-coral);}
.acell{display:flex;flex-direction:column;align-items:stretch;justify-content:center;padding:0 4px;}
.hlabel{font-size:.64rem;color:var(--noc-muted);text-align:center;margin-bottom:7px;letter-spacing:.05em;line-height:1.2;}
.hline{position:relative;height:3px;border-radius:3px;background:linear-gradient(90deg,#22D3EE,#10B981);margin-right:8px;}
.hline::after{content:"";position:absolute;right:-8px;top:-5px;border-left:10px solid #10B981;
  border-top:6.5px solid transparent;border-bottom:6.5px solid transparent;}
.vcell{display:flex;align-items:center;justify-content:center;height:100%;gap:12px;}
.vline{position:relative;width:3px;height:100%;border-radius:3px;margin-left:0;}
.vline.ctl{background:repeating-linear-gradient(180deg,#A78BFA 0 7px,transparent 7px 12px);}
.vline.bg{background:repeating-linear-gradient(180deg,#FB7185 0 7px,transparent 7px 12px);}
.vline.ctl::after{content:"";position:absolute;left:-5px;bottom:-8px;border-top:10px solid #A78BFA;
  border-left:6.5px solid transparent;border-right:6.5px solid transparent;}
.vline.bg::after{content:"";position:absolute;left:-5px;top:-8px;border-bottom:10px solid #FB7185;
  border-left:6.5px solid transparent;border-right:6.5px solid transparent;}
.vlabel{font-size:.68rem;color:var(--noc-muted);letter-spacing:.05em;max-width:200px;}
.hl-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:14px;margin:6px 0 20px 0;}
.hl{background:var(--noc-panel);border:1px solid var(--noc-border);border-radius:14px;padding:16px 18px;}
.hl-num{width:26px;height:26px;border-radius:8px;display:inline-flex;align-items:center;justify-content:center;
  font-weight:800;font-size:.8rem;color:#04111F;background:var(--noc-cyan);margin-bottom:9px;}
.hl-title{font-weight:700;color:var(--noc-strong);font-size:.95rem;margin-bottom:5px;}
.hl-text{font-size:.83rem;color:#B6C2D4;line-height:1.55;}
.credits{display:flex;flex-wrap:wrap;gap:18px;align-items:center;justify-content:space-between;
  background:linear-gradient(120deg,#0F172A,#0B2A4A);border:1px solid #1E3A5F;border-radius:16px;padding:18px 24px;margin-top:8px;}
.credits-title{font-size:.7rem;font-weight:800;letter-spacing:.16em;text-transform:uppercase;color:var(--noc-cyan);}
.credits-sub{font-size:.8rem;color:var(--noc-muted);margin-top:4px;}
.members{display:flex;flex-wrap:wrap;gap:10px;}
.member{display:inline-flex;align-items:center;gap:9px;padding:6px 14px 6px 6px;border-radius:999px;
  background:rgba(148,163,184,.10);border:1px solid var(--noc-border2);font-weight:700;color:var(--noc-strong);font-size:.9rem;}
.avatar{width:28px;height:28px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;
  font-size:.8rem;font-weight:800;color:#04111F;background:linear-gradient(135deg,#22D3EE,#10B981);}

@media (max-width:1100px){   /* compact KPI cards when the window is narrow */
  .stApp [data-testid="stMetricLabel"], .stApp [data-testid="stMetricLabel"] *{font-size:.62rem;letter-spacing:.03em;}
  .stApp [data-testid="stMetricValue"], .stApp [data-testid="stMetricValue"] *{font-size:1.05rem;white-space:normal !important;}
  [data-testid="stMetric"]{padding:12px 12px 10px 12px;}
  [data-testid="stMetricDelta"], [data-testid="stMetricDelta"] *{font-size:.66rem;white-space:normal !important;
    word-break:normal !important;overflow-wrap:normal !important;}
  [data-testid="stMetricDelta"]{border-radius:10px;padding:3px 8px;}
  [data-testid^="stMetricDeltaIcon"]{display:none;}
}
@media (max-width:900px){
  .arch-grid{grid-template-columns:1fr;grid-template-rows:none;row-gap:12px;}
  .arch-grid > div{grid-column:1 !important;grid-row:auto !important;}
  .g-a1,.g-a2,.g-v1,.g-v2{display:none;}
  .g-agent{order:1;} .g-sw{order:2;} .g-mon{order:3;} .g-ctrl{order:4;} .g-load{order:5;}
  .noc-banner{padding:18px;}
}
</style>
"""


# =============================================================================
# 4. SMALL HELPERS
# =============================================================================
def html_block(markup: str) -> str:
    """Strip indentation and blank lines so Markdown never treats HTML as a code block."""
    return "\n".join(line.strip() for line in markup.splitlines() if line.strip())


def render_html(markup: str) -> None:
    st.markdown(html_block(markup), unsafe_allow_html=True)


def badge(text: str, kind: str = "mute", dot: bool = False) -> str:
    dot_html = '<span class="dot"></span>' if dot else ""
    return f'<span class="noc-badge noc-badge-{kind}">{dot_html}{html.escape(text)}</span>'


def stretch(fn, *args, **kwargs):
    """Call a Streamlit element full-width across Streamlit versions.
    Newer releases use width="stretch"; older ones use use_container_width=True."""
    last_exc = None
    for extra in ({"width": "stretch"}, {"use_container_width": True}, {}):
        try:
            return fn(*args, **kwargs, **extra)
        except Exception as exc:  # noqa: BLE001 - try the next calling convention
            last_exc = exc
    raise last_exc


def ordered(values, preferred):
    """Known values first (in preferred order), then any unexpected ones alphabetically."""
    present = list(dict.fromkeys(values))
    return [v for v in preferred if v in present] + sorted(v for v in present if v not in preferred)


def sanitize_sla(raw):
    """Return (threshold_ms, was_invalid). Falls back to the default for junk input."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return SLA_DEFAULT, True
    if math.isnan(value) or not (SLA_MIN <= value <= SLA_MAX):
        return SLA_DEFAULT, True
    return value, False


def init_multiselect(key, options):
    """Default to 'all selected' and drop stale selections if the CSV's values changed."""
    current = st.session_state.get(key)
    st.session_state[key] = list(options) if current is None else [v for v in current if v in options]


# =============================================================================
# 5. DATA LOADING (same file path as before, now with explicit validation)
# =============================================================================
class TelemetryError(Exception):
    """A data problem we can explain to the user in plain words."""


def load_results(path: str) -> pd.DataFrame:
    if not os.path.isfile(path):
        raise TelemetryError("Telemetry file not found.")
    if os.path.getsize(path) == 0:
        raise TelemetryError("Telemetry file is empty (0 bytes).")

    df = pd.read_csv(path, encoding="utf-8-sig")  # utf-8-sig tolerates Excel's BOM
    if df.empty:
        raise TelemetryError("Telemetry file has a header row but no data rows.")

    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise TelemetryError("Telemetry file is missing required column(s): " + ", ".join(missing) + ".")
    df = df[REQUIRED_COLS].copy()

    if df[["mode", "load"]].isna().any().any():
        raise TelemetryError("Blank values found in the 'mode' or 'load' column.")
    for col in ("mode", "load"):
        df[col] = df[col].astype(str).str.strip().str.lower()

    for col in NUMERIC_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    finite = df[NUMERIC_COLS].apply(lambda s: s.map(lambda v: pd.notna(v) and math.isfinite(v)))
    bad_rows = df.index[~finite.all(axis=1)]
    if len(bad_rows):
        lines = ", ".join(str(i + 2) for i in bad_rows[:5])  # +2 = header row + 1-based
        raise TelemetryError(f"Non-numeric or blank latency/jitter/loss values (CSV line(s): {lines}).")
    return df.reset_index(drop=True)


raw_df = None
load_error = None
try:
    raw_df = load_results(RESULTS_CSV)
except TelemetryError as exc:
    load_error = str(exc)
except Exception as exc:  # noqa: BLE001 - parser errors, permissions, encoding...
    load_error = f"The file could not be parsed ({type(exc).__name__}: {exc})."

# =============================================================================
# 6. STYLES + DEFERRED TOAST (a toast fired right before st.rerun() can be lost,
#    so the refresh button leaves a flag and the *next* run shows the toast)
# =============================================================================
st.markdown(html_block(CSS), unsafe_allow_html=True)

if st.session_state.pop("_toast_refresh", False):
    st.toast("Telemetry data refreshed from results/results.csv!", icon="🔄")

# =============================================================================
# 7. SIDEBAR: branding, status, filters, SLA input, refresh
# =============================================================================
now_str = datetime.now().strftime("%H:%M:%S")
mode_opts, load_opts = MODE_ORDER, LOAD_ORDER
sla_ms, sla_invalid = SLA_DEFAULT, False
sel_modes, sel_loads = [], []

with st.sidebar:
    render_html(
        """
        <div class="noc-brand">
          <div class="noc-brand-logo">🌐</div>
          <div>
            <div class="noc-brand-title">SDN QoS Health Monitor</div>
            <div class="noc-brand-sub">COMPUTER NETWORKS CAPSTONE</div>
          </div>
        </div>
        """
    )

    if raw_df is not None:
        status_badge = badge("Telemetry Online", "ok", dot=True)
        status_meta = f"<b>{len(raw_df)}</b> scenarios loaded &middot; synced <b>{now_str}</b>"
    else:
        status_badge = badge("Telemetry Offline", "bad", dot=True)
        status_meta = f"Cannot read <b>{RESULTS_REL}</b>"
    render_html(
        f"""
        <div class="noc-status">
          {status_badge}
          <div class="noc-status-meta">{status_meta}<br>Controller: <b>POX</b> &middot; OpenFlow port <b>6653</b></div>
        </div>
        """
    )

    if raw_df is not None:
        mode_opts = ordered(raw_df["mode"], MODE_ORDER)
        load_opts = ordered(raw_df["load"], LOAD_ORDER)
        init_multiselect("flt_mode", mode_opts)
        init_multiselect("flt_load", load_opts)

        render_html('<div class="noc-side-section">Filters</div>')
        sel_modes = st.multiselect("Forwarding Mode", options=mode_opts, key="flt_mode")
        sel_loads = st.multiselect("Traffic Load", options=load_opts, key="flt_load")

        render_html('<div class="noc-side-section">Service Level</div>')
        sla_input = st.number_input(
            "SLA Latency Threshold (p95, ms)",
            min_value=SLA_MIN,
            max_value=SLA_MAX,
            value=SLA_DEFAULT,
            step=10.0,
            format="%.1f",
            key="sla_ms",
            help=f"Target p95 latency. Valid range {SLA_MIN:.0f}-{SLA_MAX:.0f} ms. "
                 "Scenarios above it are flagged on the charts and in the alert banner.",
        )
        sla_ms, sla_invalid = sanitize_sla(sla_input)

    if stretch(st.button, "🔄 Refresh Telemetry Data", key="btn_refresh"):
        st.session_state["_toast_refresh"] = True   # shown by the next run (see section 6)
        st.session_state.pop("_sla_toast_sig", None)  # let the SLA toast re-announce
        st.rerun()

    st.caption(f"Source: {RESULTS_REL}")

# =============================================================================
# 8. HEADER BANNER + HARD STOP IF THE CSV IS UNUSABLE
# =============================================================================
if raw_df is not None:
    fdf = raw_df[raw_df["mode"].isin(sel_modes) & raw_df["load"].isin(sel_loads)]
    # Table/chart order: by load, then baseline before qos (stable sorts)
    fdf = (
        fdf.sort_values("mode", key=lambda s: s.map({m: i for i, m in enumerate(mode_opts)}), kind="stable")
        .sort_values("load", key=lambda s: s.map({m: i for i, m in enumerate(load_opts)}), kind="stable")
        .reset_index(drop=True)
    )
    has_data = not fdf.empty
    breach_df = fdf[fdf[LAT_COL] > sla_ms] if has_data else fdf
else:
    fdf, has_data, breach_df = pd.DataFrame(), False, pd.DataFrame()

if load_error:
    header_badges = badge("Offline", "bad", dot=True) + badge("POX :6653", "info")
elif not has_data:
    header_badges = badge("Live", "ok", dot=True) + badge("POX :6653", "info") + badge("SLA: no data", "mute")
else:
    sla_badge = (
        badge(f"SLA breach · {len(breach_df)}", "warn") if len(breach_df) else badge("SLA compliant", "ok")
    )
    header_badges = (
        badge("Live", "ok", dot=True) + badge("POX :6653", "info") + sla_badge
        + badge(f"{len(fdf)}/{len(raw_df)} scenarios", "mute")
    )

render_html(
    f"""
    <div class="noc-banner">
      <div>
        <div class="noc-banner-title">SDN Network Performance &amp; QoS Health Monitor</div>
        <div class="noc-banner-sub">Baseline (no prioritization) vs OpenFlow QoS across background traffic loads
        &middot; wire-level steady-state telemetry</div>
      </div>
      <div class="noc-banner-badges">{header_badges}</div>
    </div>
    """
)

if load_error:
    st.error(
        f"**Telemetry data unavailable: {load_error}**\n\n"
        f"Expected file: `{RESULTS_CSV}`  (project-relative: `{RESULTS_REL}`)\n\n"
        f"Required columns: `{', '.join(REQUIRED_COLS)}`. "
        "Run the benchmark script to (re)generate the file, then press **Refresh Telemetry Data**."
    )
    st.stop()  # halt gracefully: nothing below can work without data

# =============================================================================
# 9. EXECUTIVE KPI ROW
# =============================================================================
k1, k2, k3, k4 = st.columns(4)

if has_data:
    # Worst-case loss across the selected scenarios keeps the "guarantee" honest
    max_loss = float(fdf[LOSS_COL].max())
    delivery = max(0.0, 100.0 - max_loss)
    # Streamlit colours a delta red when it starts with "-", so a real loss turns the badge red
    loss_delta = f"-{max_loss:.1f}% Packet Loss" if max_loss > 0 else "0.0% Packet Loss"
    k1.metric(
        "Telemetry Delivery Guarantee", f"{delivery:.1f}%", delta=loss_delta, delta_color="normal",
        help="100% minus the worst packet-loss figure across the selected scenarios.",
    )

    qos_rows = fdf[fdf["mode"] == "qos"]
    if not qos_rows.empty:
        qos_max = float(qos_rows[LAT_COL].max())
        qos_loss = float(qos_rows[LOSS_COL].max())
        k2.metric(
            "Max QoS Latency (p95)", f"{qos_max:.2f} ms",
            delta=f"Queue Buffered ({qos_loss:g}% Drop)", delta_color="off",  # neutral, not an error colour
            help="Highest p95 latency among the selected QoS scenarios. Queueing delay is the price of zero loss.",
        )
    else:
        k2.metric("Max QoS Latency (p95)", "N/A", delta="QoS mode not selected", delta_color="off")
else:
    k1.metric("Telemetry Delivery Guarantee", "—", delta="No data selected", delta_color="off")
    k2.metric("Max QoS Latency (p95)", "—", delta="No data selected", delta_color="off")

k3.metric(
    "Active SDN Control Plane", "POX (Port 6653)", delta="OpenFlow QoS Active", delta_color="normal",
    help="POX runs qos_controller.py and listens for the OpenFlow switch on port 6653.",
)
k4.metric(
    "Benchmark Scenarios Executed", f"{len(fdf)}", delta=f"of {len(raw_df)} in {RESULTS_REL}", delta_color="off",
    help="Scenarios matching the sidebar filters, out of all rows in the results file.",
)

st.write("")  # breathing room

# =============================================================================
# 10. ALERTS: SLA validation + breach warning (+ de-duplicated toast)
# =============================================================================
if sla_invalid:
    st.warning(
        f"SLA threshold must be a number between {SLA_MIN:.1f} and {SLA_MAX:.1f} ms. "
        f"Using the default of {SLA_DEFAULT:.1f} ms instead."
    )

if has_data and len(breach_df):
    worst = breach_df.sort_values(LAT_COL, ascending=False)
    offenders = "; ".join(
        f"`{m} / {l}` at **{v:.2f} ms** (+{(v / sla_ms - 1) * 100:.0f}%)"
        for m, l, v in zip(worst["mode"].head(3), worst["load"].head(3), worst[LAT_COL].head(3))
    )
    extra = f", plus {len(worst) - 3} more" if len(worst) > 3 else ""
    st.warning(
        f"**SLA breach:** {len(breach_df)} of {len(fdf)} selected scenarios exceed the "
        f"{sla_ms:.1f} ms p95 latency target. Worst: {offenders}{extra}.",
        icon="⚠️",
    )

# Fire the toast only when the breach situation changes, so it never nags on every rerun
sla_sig = (round(sla_ms, 3), tuple(zip(breach_df["mode"], breach_df["load"])) if has_data else ())
if st.session_state.get("_sla_toast_sig") != sla_sig:
    st.session_state["_sla_toast_sig"] = sla_sig
    if len(breach_df):
        st.toast("⚠️ High latency detected above SLA threshold!", icon="⚠️")

# =============================================================================
# 11. CHART BUILDER
# =============================================================================
def build_bar_chart(frame, value_col, title, y_title, hover_extra, sla=None):
    """Grouped bar chart (Baseline vs QoS per load) with labels, rich hover and optional SLA line."""
    loads = ordered(frame["load"], LOAD_ORDER)
    # One bar per (mode, load); average if the CSV ever contains repeated runs
    agg = frame.groupby(["mode", "load"], as_index=False, sort=False)[NUMERIC_COLS].mean()
    fig = go.Figure()

    for idx, mode in enumerate(ordered(agg["mode"], MODE_ORDER)):
        label, color = MODE_STYLE.get(mode, (mode.upper(), FALLBACK_COLORS[idx % len(FALLBACK_COLORS)]))
        sub = agg[agg["mode"] == mode].set_index("load").reindex(loads)
        y = sub[value_col]

        hover_cols = {name: sub[col] for name, col in hover_extra}
        if sla is not None:
            hover_cols["vs SLA"] = y - sla
        custom = pd.DataFrame(hover_cols).to_numpy()
        rows = [f"{name}: %{{customdata[{i}]:.2f}}" for i, name in enumerate(hover_cols)]
        if sla is not None:
            rows[-1] = f"vs SLA ({sla:.0f} ms): %{{customdata[{len(hover_cols) - 1}]:+.2f}} ms"
        hover = (
            f"<b>%{{x}}</b><br>Mode: <b>{label}</b><br>{y_title}: <b>%{{y:.2f}}</b><br>"
            + "<br>".join(rows) + "<extra></extra>"
        )

        # Amber outline marks bars that breach the SLA line
        outline = [SLA_LINE_COLOR if (sla is not None and pd.notna(v) and v > sla) else "rgba(0,0,0,0)" for v in y]
        fig.add_trace(
            go.Bar(
                x=loads, y=y, name=label, customdata=custom, hovertemplate=hover,
                marker=dict(color=color, line=dict(color=outline, width=2.5)),
                # "auto": label sits inside tall bars (clear of the SLA line), outside short ones
                text=y, texttemplate="%{y:.2f}", textposition="auto", textangle=0, cliponaxis=False,
                insidetextanchor="end",
                insidetextfont=dict(color="#04111F", size=12),
                outsidetextfont=dict(color="#E2E8F0", size=12),
            )
        )

    top = float(agg[value_col].max()) if len(agg) else 0.0
    y_max = max(top * 1.22, (sla * 1.15) if sla is not None else 0.0, 1.0)
    if sla is not None:
        fig.add_hline(
            y=sla, line_dash="dash", line_color=SLA_LINE_COLOR, line_width=2, layer="below",  # keeps bar labels readable
            annotation_text=f"SLA {sla:.0f} ms", annotation_position="top left",
            annotation_font=dict(color=SLA_LINE_COLOR, size=12),
        )

    fig.update_layout(
        title=dict(text=title, x=0.0, xanchor="left", font=dict(size=16, color="#F1F5F9")),
        template="plotly_dark", barmode="group", bargap=0.28, bargroupgap=0.08, height=450,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",   # transparent: card shows through
        font=dict(family=FONT_STACK, color="#CBD5E1", size=13),
        margin=dict(l=10, r=10, t=80, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor="#0F172A", bordercolor="#334155", font=dict(color="#E2E8F0", size=13)),
    )
    fig.update_xaxes(
        title_text="Background load", type="category", categoryorder="array", categoryarray=loads,
        showgrid=False, linecolor="#334155",
    )
    fig.update_yaxes(
        title_text=y_title, range=[0, y_max], gridcolor="rgba(148,163,184,.14)", zeroline=False,
    )
    return fig


# =============================================================================
# 12. TABS
# =============================================================================
tab_summary, tab_charts, tab_arch = st.tabs(
    ["📊 Key Metrics & Summary", "📈 Performance Charts", "🏗️ SDN Architecture & Topology"]
)

# ---- Tab 1: summary table ---------------------------------------------------
with tab_summary:
    if not has_data:
        st.warning(NO_DATA_MSG)
    else:
        render_html(f'<div class="noc-section">Benchmark results <span>{len(fdf)} scenarios</span></div>')

        disp = fdf[REQUIRED_COLS].rename(columns=COLUMN_LABELS)
        lat_label, loss_label = COLUMN_LABELS[LAT_COL], COLUMN_LABELS[LOSS_COL]
        BASE = "background-color:#111B2E;color:#E2E8F0"
        OK = "background-color:#0E4A3A;color:#6EE7B7;font-weight:700"      # soft emerald: 0% loss
        BAD = "background-color:#4C1D2B;color:#FDA4AF;font-weight:700"     # coral: loss or SLA breach

        def cell_styles(frame):
            styles = pd.DataFrame(BASE, index=frame.index, columns=frame.columns)
            styles[lat_label] = frame[lat_label].map(lambda v: BAD if v > sla_ms else BASE)
            styles[loss_label] = frame[loss_label].map(lambda v: OK if v == 0 else BAD)
            return styles

        try:  # Pandas Styler needs jinja2; fall back to a plain table if unavailable
            table = disp.style.apply(cell_styles, axis=None).format(
                {lat_label: "{:.2f}", COLUMN_LABELS[JIT_COL]: "{:.2f}", loss_label: "{:.2f}"}
            )
        except Exception:  # noqa: BLE001
            table = disp.round(2)
        stretch(st.dataframe, table, hide_index=True, height=(len(disp) + 1) * 35 + 3)
        st.caption(
            f"Emerald = 0% packet loss · Coral = loss detected or p95 latency above the {sla_ms:.0f} ms SLA threshold."
        )

        if max_loss == 0:
            st.success(
                "**Zero packet loss by design.** OpenFlow priority queues intentionally buffer telemetry packets "
                "under heavy saturation to guarantee 0% packet drops. The bounded rise in p95 latency is the "
                "deliberate trade-off for reliable delivery.",
                icon="✅",
            )
        else:
            st.warning(
                f"Packet loss of up to {max_loss:.2f}% was recorded in the selected scenarios, "
                "so the zero-drop guarantee does not hold for this selection.",
                icon="⚠️",
            )

# ---- Tab 2: Plotly charts ---------------------------------------------------
with tab_charts:
    if not has_data:
        st.warning(NO_DATA_MSG)
    else:
        c1, c2 = st.columns(2)
        try:
            lat_fig = build_bar_chart(
                fdf, LAT_COL, "p95 Latency: Baseline vs QoS", "p95 latency (ms)",
                hover_extra=[("Jitter (ms)", JIT_COL), ("Packet loss (%)", LOSS_COL)], sla=sla_ms,
            )
            jit_fig = build_bar_chart(
                fdf, JIT_COL, "RFC 3550 Jitter: Baseline vs QoS", "Jitter (ms)",
                hover_extra=[("p95 latency (ms)", LAT_COL), ("Packet loss (%)", LOSS_COL)],
            )
            plot_cfg = {"displaylogo": False}
            with c1:
                stretch(st.plotly_chart, lat_fig, theme=None, config=plot_cfg)
            with c2:
                stretch(st.plotly_chart, jit_fig, theme=None, config=plot_cfg)
            st.caption(
                f"Dashed amber line = SLA threshold ({sla_ms:.0f} ms, set in the sidebar). "
                "Bars with an amber outline exceed it. Hover any bar for jitter, loss and SLA headroom."
            )
        except Exception as exc:  # noqa: BLE001 - never let a chart error take the page down
            st.error(f"Could not render the performance charts: {exc}")

        # Legacy PNG plots from earlier versions of this dashboard (optional)
        try:
            pngs = sorted(f for f in os.listdir(PLOTS_DIR) if f.lower().endswith(".png")) if os.path.isdir(PLOTS_DIR) else []
            if pngs:
                with st.expander("🖼️ Archived benchmark plots (results/plots)"):
                    cols = st.columns(2)
                    for i, name in enumerate(pngs):
                        with cols[i % 2]:
                            st.caption(name[:-4].replace("_", " ").title())
                            stretch(st.image, os.path.join(PLOTS_DIR, name))
        except Exception:  # noqa: BLE001
            pass

# ---- Tab 3: architecture ----------------------------------------------------
with tab_arch:
    render_html('<div class="noc-section">End-to-end packet pipeline <span>telemetry path &amp; control plane</span></div>')
    render_html(
        """
        <div class="arch"><div class="arch-grid">
          <div class="node ctrl g-ctrl">
            <div class="node-tag">Control plane</div>
            <div class="node-title">🧠 POX Controller</div>
            <div class="node-desc">Runs <code>qos_controller.py</code> and programs the switch over OpenFlow.</div>
            <div class="node-chips"><span class="chip">TCP 6653</span><span class="chip">OpenFlow</span></div>
          </div>
          <div class="vcell g-v1"><div class="vline ctl"></div><div class="vlabel">flow rules &amp;<br>queue mapping</div></div>

          <div class="node src g-agent">
            <div class="node-tag">Telemetry source</div>
            <div class="node-title">📡 agent1</div>
            <div class="node-desc">Samples host metrics with <b>psutil</b> and streams them as UDP telemetry.</div>
            <div class="node-chips"><span class="chip">psutil</span><span class="chip">UDP</span></div>
          </div>
          <div class="acell g-a1"><div class="hlabel">UDP<br>telemetry</div><div class="hline"></div></div>

          <div class="node sw g-sw">
            <div class="node-tag">Data plane</div>
            <div class="node-title">🔀 OpenFlow Switch s1</div>
            <div class="node-desc">Priority queues managed by POX <code>qos_controller.py</code> on Port 6653.
            Telemetry rides the priority queue; background load shares the rest.</div>
            <div class="node-chips"><span class="chip">priority queues</span><span class="chip">flow table</span></div>
          </div>
          <div class="acell g-a2"><div class="hlabel">prioritized<br>delivery</div><div class="hline"></div></div>

          <div class="node sink g-mon">
            <div class="node-tag">Telemetry sink</div>
            <div class="node-title">🖥️ Monitor Server</div>
            <div class="node-desc">Real-Time Analytics: collects telemetry and measures latency, jitter and loss.</div>
            <div class="node-chips"><span class="chip">analytics</span></div>
          </div>

          <div class="vcell g-v2"><div class="vline bg"></div><div class="vlabel">congestion injected<br>into s1</div></div>
          <div class="node load g-load">
            <div class="node-tag">Background congestion</div>
            <div class="node-title">🌊 Load generators</div>
            <div class="node-desc">Competing traffic at <code>udp_half</code>, <code>udp_sat</code> and <code>tcp_sat</code> levels.</div>
          </div>
        </div></div>
        """
    )

    qos_all = raw_df[raw_df["mode"] == "qos"]
    if len(qos_all):
        peak = f"QoS p95 peaks at {qos_all[LAT_COL].max():.2f} ms with {qos_all[LOSS_COL].max():g}% loss"
    else:
        peak = "QoS rows are not present in the results file"

    render_html('<div class="noc-section">How OpenFlow isolates telemetry from congestion <span>technical highlights</span></div>')
    render_html(
        f"""
        <div class="hl-grid">
          <div class="hl"><div class="hl-num">1</div><div class="hl-title">Classify at the switch</div>
            <div class="hl-text">Flow rules match telemetry packets so they are told apart from background traffic
            the moment they enter s1.</div></div>
          <div class="hl"><div class="hl-num">2</div><div class="hl-title">Dedicated priority queue</div>
            <div class="hl-text">Matched traffic is enqueued on a high-priority queue, so saturating UDP or TCP
            load cannot starve it of egress bandwidth.</div></div>
          <div class="hl"><div class="hl-num">3</div><div class="hl-title">Buffer, don't drop</div>
            <div class="hl-text">Under saturation the queue holds packets rather than discarding them. {html.escape(peak)}:
            bounded latency in exchange for zero loss.</div></div>
          <div class="hl"><div class="hl-num">4</div><div class="hl-title">Centralised control</div>
            <div class="hl-text">POX installs and updates the rules over port 6653, so policy lives in
            <code>qos_controller.py</code> and the switch simply enforces it.</div></div>
        </div>
        """
    )

    render_html(
        """
        <div class="credits">
          <div>
            <div class="credits-title">Capstone Team</div>
            <div class="credits-sub">Computer Networks Capstone &middot; SDN Network Performance &amp; QoS Health Monitor</div>
          </div>
          <div class="members">
            <span class="member"><span class="avatar">N</span>Ninad</span>
            <span class="member"><span class="avatar">M</span>Nishant</span>
            <span class="member"><span class="avatar">N</span>Mridul</span>
          </div>
        </div>
        """
    )
