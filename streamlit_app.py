import time
import pandas as pd
import numpy as np
import streamlit as st
import yfinance as yf

APP_NAME = "🚀 Expanded Universe Scanner v1.0 — MACD‑V + Badges (Wild Cards)"
st.set_page_config(page_title=APP_NAME, layout="wide")
st.title(APP_NAME)
st.caption("Curated high‑volatility universe outside the S&P 500. MACD‑V‑only, stricter volume filter, badges, and Source tagging. Autostarts on load.")

# Sidebar
with st.sidebar:
    st.subheader("Controls")
    vol_mult = st.number_input("Volume multiple (vs 20‑day avg) ≥", min_value=1.0, value=2.0, step=0.1)
    rr_min = st.number_input("Min Risk/Reward (R)", min_value=1.0, value=2.0, step=0.5)
    max_universe = st.number_input("Max tickers to scan", min_value=50, value=300, step=50)
    sleep_s = st.number_input("Sleep between downloads (sec)", min_value=0.0, value=0.25, step=0.05)
    retries = st.slider("Max retries per ticker", 0, 5, 2)
    days = st.slider("Lookback period (days)", 90, 365, 180)
    export_filename = st.text_input("Export base filename", "expanded_universe_v10_macdv")
    gate_strict = st.checkbox("Gate to high‑conviction only (Score≥3 AND MACD‑V ✅)", value=True)
    show_losers = st.checkbox("Also show gated‑out names at bottom", value=False)

# Indicators (MACD‑V only)
def vwema(price: pd.Series, volume: pd.Series, span: int) -> pd.Series:
    vp = (price * volume).ewm(span=span, adjust=False).mean()
    v = volume.ewm(span=span, adjust=False).mean().replace(0, np.nan)
    return vp / v

def macd_v(price: pd.Series, volume: pd.Series, fast=12, slow=26, signal=9):
    vw_fast = vwema(price, volume, fast)
    vw_slow = vwema(price, volume, slow)
    macd_line = vw_fast - vw_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

@st.cache_data(show_spinner=False)
def fetch_one(ticker: str, period_days: int, retries: int, sleep: float):
    last_err = None
    for i in range(retries + 1):
        try:
            df = yf.download(
                ticker,
                period=f"{period_days}d",
                interval="1d",
                progress=False,
                auto_adjust=False,
                threads=False,
            )
            if df is not None and not df.empty:
                return df
        except Exception as e:
            last_err = e
        time.sleep(sleep * (i + 1))
    return pd.DataFrame()

# Curated Wild Card universe (US‑listed only for Yahoo compatibility)
WILD_CARDS = [
    "NBIS","SMCI","PLTR","AMD","ARM","TSM","AEHR","NVAX","AI","IONQ","UPST","SOUN","CELH","NET","DDOG","PATH","U","AFRM",
    "RIOT","MARA","RIVN","LCID","ROKU","HOOD","TOST","COIN","CRNX","ABCM","SANA","RXRX","BMRN","CRSP","TWLO","SNOW","MDB",
    "ZS","OKTA","BILL","ASAN","SHOP","SOFI","BROS","GLBE","BMBL","VRT","ENVX","WOLF","ON","AMBA","RUN","ENPH","FSLR","SEDG",
    "WIX","HIMS","RXST","KNSL","AXON","ESTC","APP","CFLT","MQ","LC","FSLY","PVH","CPNG","PINS","PARA","TTD","ROIV","BABA",
    "JD","PDD","NIO","XPEV","LI","ZIM","GTLB","ELF","TPR","CRWD","DOCN","RBLX","DKNG","BNFT","IOT","INFA","CAVA","SATS","WBD"
]
WILD_CARDS = list(dict.fromkeys(WILD_CARDS))  # de‑dupe

@st.cache_data(show_spinner=True)
def load_symbols(max_n: int):
    syms = [s for s in WILD_CARDS if isinstance(s, str) and s.strip()]
    return syms[: int(max_n)]

symbols = load_symbols(max_universe)

st.info(f"Scanning {len(symbols)} wild‑card tickers… (MACD‑V only, stricter filters)")
rows, losers, failures = [], [], []
progress = st.progress(0)
status_box = st.empty()

def macdv_badge(hist_series):
    if len(hist_series) < 2:
        return "⚠️ Weak/Flat", 1
    last = float(hist_series.iloc[-1])
    prev = float(hist_series.iloc[-2])
    if last > 0 and last > prev:
        return "✅ Bullish", 2
    if last < 0:
        return "❌ Bearish", 0
    return "⚠️ Weak/Flat", 1

for idx, t in enumerate(symbols, start=1):
    try:
        data = fetch_one(t, days, retries, sleep_s)
        if data.empty or len(data) < 60:
            continue

        close = data["Close"]
        vol = data["Volume"].fillna(0)

        ema20 = close.ewm(span=20, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()

        c_last = float(close.iloc[-1])
        e20, e50 = float(ema20.iloc[-1]), float(ema50.iloc[-1])
        trend_ok = (e20 > e50) and (c_last > e20)

        _, _, hist_v = macd_v(close, vol)
        macd_note, macd_weight = macdv_badge(hist_v)
        m_last = float(hist_v.iloc[-1])
        m_prev = float(hist_v.iloc[-2]) if len(hist_v) >= 2 else m_last
        macd_ok = (m_last > 0) and (m_last > m_prev)

        vol_avg20 = vol.rolling(20).mean()
        v_last, v_avg = float(vol.iloc[-1]), float(vol_avg20.iloc[-1])
        vol_ok = (v_avg > 0) and (v_last >= vol_mult * v_avg)  # stricter default 2.0+

        entry, stop = c_last, e50
        if stop > 0 and entry > stop:
            risk = entry - stop
            target = entry + rr_min * risk
            rr = (target - entry) / risk
            rr_ok = rr >= rr_min
        else:
            target, rr, rr_ok = None, None, False

        catalyst = False  # placeholder
        score = int(trend_ok) + int(macd_ok) + int(vol_ok) + int(rr_ok) + int(catalyst)

        row = {
            "Ticker": t,
            "Source": "WildCard",
            "Entry": round(entry, 2),
            "Stop(EMA50)": round(stop, 2) if stop else None,
            "Target": round(target, 2) if target else None,
            "R/R": round(rr, 2) if rr else None,
            "Score (0-5)": score,
            "Status": ("PRIME" if score == 5 else "Strong TA" if score == 4 else "Candidate" if score == 3 else "Weak/Skip"),
            "MACD‑V": macd_note,
            "_MACD_Weight": macd_weight
        }

        if gate_strict and not (score >= 3 and macd_note.startswith("✅")):
            losers.append(row)
        else:
            rows.append(row)

    except Exception as e:
        failures.append((t, str(e)))

    if idx % 10 == 0 or idx == len(symbols):
        progress.progress(idx / len(symbols))
        status_box.info(f"Scanning {idx}/{len(symbols)}…")

# Output
def render_table(title, data_rows, filename_stub):
    df = pd.DataFrame(data_rows)
    if df.empty:
        st.warning(f"No rows for {title}.")
        return
    df = df.sort_values(["Score (0-5)", "Status", "R/R", "_MACD_Weight"],
                        ascending=[False, True, False, False]).drop(columns=["_MACD_Weight"])
    st.subheader(title)
    st.dataframe(df, use_container_width=True)
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download CSV", data=csv, file_name=f"{export_filename}_{filename_stub}.csv", mime="text/csv")

if rows:
    render_table("High‑conviction Candidates", rows, "candidates")
else:
    st.warning("No high‑conviction names met gating today. Consider loosening filters or disabling 'Gate to high‑conviction only'.")

if show_losers and losers:
    render_table("Gated‑out (context only)", losers, "gated_out")

if failures:
    with st.expander("Fetch errors"):
        for t, msg in failures:
            st.write(f"- {t}: {msg}")
