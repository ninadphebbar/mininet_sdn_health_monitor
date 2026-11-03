import streamlit as st
import pandas as pd
import os
from PIL import Image

st.set_page_config(
    page_title="SDN Performance & QoS Dashboard",
    page_icon="⚡",
    layout="wide"
)

st.title("⚡ SDN Network Performance & QoS Benchmarking Dashboard")
st.markdown("Automated performance analysis comparing **Baseline (No Prioritization)** vs **QoS Mode** across background traffic loads.")

ROOT = os.path.dirname(os.path.abspath(__file__))
results_csv = os.path.join(ROOT, "results", "results.csv")
plots_dir = os.path.join(ROOT, "results", "plots")

st.header("📊 Key Metrics Summary")

if os.path.exists(results_csv):
    df = pd.read_csv(results_csv)
    display_cols = [c for c in ['mode', 'load', 'wire_steady_lat_p95_ms', 'wire_steady_jitter_ms', 'wire_steady_loss_pct'] if c in df.columns]
    
    if display_cols:
        st.dataframe(df[display_cols], use_container_width=True)
    else:
        st.dataframe(df, use_container_width=True)
        
    st.markdown("---")

    col1, col2, col3 = st.columns(3)
    if 'wire_steady_lat_p95_ms' in df.columns:
        baseline_max = df[df['mode'] == 'baseline']['wire_steady_lat_p95_ms'].max()
        qos_max = df[df['mode'] == 'qos']['wire_steady_lat_p95_ms'].max() if 'qos' in df['mode'].values else 0
        
        col1.metric("Max Baseline Latency (p95)", f"{baseline_max:.2f} ms")
        if qos_max > 0:
            col2.metric("Max QoS Latency (p95)", f"{qos_max:.2f} ms", delta=f"{qos_max - baseline_max:.2f} ms")
        col3.metric("Test Scenarios Run", f"{len(df)}")
else:
    st.warning("No `results/results.csv` file found. Run your benchmark script first!")

st.header("📈 Comparative Performance Plots")

if os.path.exists(plots_dir):
    plot_files = [f for f in os.listdir(plots_dir) if f.endswith('.png')]
    if plot_files:
        cols = st.columns(2)
        for idx, plot_file in enumerate(sorted(plot_files)):
            img_path = os.path.join(plots_dir, plot_file)
            img = Image.open(img_path)
            with cols[idx % 2]:
                st.subheader(plot_file.replace('.png', '').replace('_', ' ').title())
                st.image(img, use_container_width=True)
    else:
        st.info("No `.png` plots found in `results/plots/`.")
else:
    st.info("Plot directory `results/plots/` not found.")
