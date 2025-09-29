import time
import pandas as pd
import numpy as np
import streamlit as st
import yfinance as yf

APP_NAME = "🚀 Expanded Universe Scanner v1.3.0 — MACD‑V, Score 0–5, Static NDX Fallback"
st.set_page_config(page_title=APP_NAME, layout="wide")
st.title(APP_NAME)
st.caption("Multi‑source universe (wild cards + indices). MACD‑V only. **Score 0–5** (Trend, MACD‑V, Volume, R/R, Breakout). "
           "NaN‑safe VWAP. Top‑K fallback. Uses **static Nasdaq‑100 list** if Wikipedia fetch fails (fix for 'only 93 tickers').")

# ---------- Sidebar ----------
with st.sidebar:
    st.subheader("Universe Sources")
    use_curated = st.checkbox("Curated Wild Cards (AI/biotech/semis/IPO)", value=True)
    use_ndx100  = st.checkbox("Nasdaq‑100", value=True)
    use_r1000   = st.checkbox("Russell 1000 (experimental)", value=False)
    use_r2000   = st.checkbox("Russell 2000 (experimental)", value=False)
    custom_tickers = st.text_area("Custom tickers (comma‑separated)", "", height=80)
    st.markdown("---")
    st.subheader("Filters")
    vol_mult = st.number_input("Volume multiple (vs 20‑day avg) ≥", min_value=1.0, value=2.0, step=0.1)
    rr_min = st.number_input("Min Risk/Reward (R) ≥", min_value=1.0, value=2.0, step=0.5)
    min_price = st.number_input("Min last price ($) ≥", min_value=0.0, value=10.0, step=1.0)
    min_dollar_vol = st.number_input("Min dollar volume 20d ($M/day) ≥", min_value=0.0, value=5.0, step=1.0)
    max_adr = st.number_input("Max ADR(20) % ≤", min_value=2.0, value=22.0, step=1.0)
    min_adr = st.number_input("Min ADR(20) % ≥", min_value=0.5, value=2.0, step=0.5)
    st.markdown("---")
    st.subheader("Runtime")
    max_universe = st.number_input("Max tickers to scan", min_value=100, value=1200, step=100)
    days = st.slider("Lookback period (days)", 60, 365, 180)
    retries = st.slider("Max retries per ticker", 0, 5, 2)
    sleep_s = st.number_input("Sleep between downloads (sec)", min_value=0.0, value=0.12, step=0.02)
    export_filename = st.text_input("Export base filename", "expanded_universe_v130_score5")
    gate_strict = st.checkbox("Gate to high‑conviction only (Score≥4 AND MACD‑V ✅)", value=True)
    top_k = st.slider("Top K to display", 3, 25, 5)

# ---------- Static Lists (fallbacks) ----------
NDX100_STATIC = [
"ADBE","ADI","ADP","ADSK","AEP","ALGN","AMAT","AMD","AMGN","AMZN","ANSS","ASML","AVGO","AZN","BIDU","BKNG","CDNS","CEG",
"CHTR","CMCSA","COST","CPRT","CRWD","CSCO","CSGP","CSX","CTAS","CTSH","DDOG","DLTR","DOCU","DXCM","EA","EBAY","ENPH",
"EXC","FAST","FTNT","GEHC","GFS","GILD","GOOG","GOOGL","HON","IDXX","ILMN","INTC","INTU","ISRG","JD","KDP","KHC","KLAC",
"KDP","LRCX","LULU","MAR","MCHP","MDLZ","MELI","META","MNST","MRVL","MSFT","MU","NFLX","NVDA","NXPI","ODFL","ORLY","PANW",
"PAYX","PCAR","PDD","PEP","PYPL","QCOM","REGN","RICI","ROST","SBUX","SGEN","SIRI","SNPS","SPLK","TEAM","TMUS","TSLA",
"TSM","TTD","TXN","VRSK","VRTX","WBA","WDAY","XEL","ZM"
]
# de-dup and clean
NDX100_STATIC = sorted(list({s.replace(".","-").upper() for s in NDX100_STATIC}))

CURATED = [
    "NBIS","SMCI","PLTR","ARM","TSM","AEHR","NVAX","AI","IONQ","UPST","SOUN","CELH","NET","DDOG","PATH","U","AFRM",
    "RIOT","MARA","RIVN","LCID","ROKU","HOOD","TOST","COIN","CRNX","ABCM","SANA","RXRX","BMRN","CRSP","TWLO","SNOW","MDB",
    "ZS","OKTA","BILL","ASAN","SHOP","SOFI","BROS","GLBE","BMBL","VRT","ENVX","WOLF","ON","AMBA","RUN","ENPH","FSLR","SEDG",
    "WIX","HIMS","RXST","KNSL","AXON","ESTC","APP","CFLT","MQ","LC","FSLY","PVH","CPNG","PINS","PARA","TTD","ROIV","BABA",
    "JD","PDD","NIO","XPEV","LI","ZIM","GTLB","ELF","TPR","CRWD","DOCN","RBLX","DKNG","BNFT","IOT","INFA","CAVA","SATS","WBD"
]
CURATED = list(dict.fromkeys(CURATED))

# ---------- Helpers ----------
def fetch_table(url, col):
    try:
        tables = pd.read_html(url)
        for t in tables:
            if col in t.columns:
                return t[col].astype(str).tolist()
    except Exception:
        return []
    return []

@st.cache_data(show_spinner=True)
def build_universe(use_curated, use_ndx100, use_r1000, use_r2000, custom):
    symbols = []
    if use_curated:
        symbols += [(s, "Curated") for s in CURATED]
    if use_ndx100:
        syms = fetch_table("https://en.wikipedia.org/wiki/Nasdaq-100", "Ticker")
        if not syms:  # fallback when Wikipedia blocks/changes format
            st.warning("Nasdaq‑100 web fetch failed — using built‑in static list.", icon="⚠️")
            syms = NDX100_STATIC
        symbols += [(s.replace(".", "-").upper(), "NDX100") for s in syms]
    if use_r1000:
        syms = fetch_table("https://en.wikipedia.org/wiki/Russell_1000_Index", "Ticker")
        if not syms:
            st.warning("Russell 1000 fetch failed — disable this source or paste custom tickers.", icon="⚠️")
        symbols += [(s.replace(".", "-").upper(), "R1000") for s in syms]
    if use_r2000:
        syms = fetch_table("https://en.wikipedia.org/wiki/Russell_2000_Index", "Ticker")
        if not syms:
            st.warning("Russell 2000 fetch failed — disable this source or paste custom tickers.", icon="⚠️")
        symbols += [(s.replace(".", "-").upper(), "R2000") for s in syms]
    if custom:
        extra = [x.strip().upper().replace(".", "-") for x in custom.split(",") if x.strip()]
        symbols += [(s, "Custom") for s in extra]
    # de‑dupe, keep first source tag
    seen = set(); out = []
    for s, src in symbols:
        if s and s not in seen:
            seen.add(s); out.append((s, src))
    return out

# Indicators
def vwema(price, volume, span):
    vp = (price * volume).ewm(span=span, adjust=False).mean()
    v = volume.ewm(span=span, adjust=False).mean().replace(0, np.nan)
    return vp / v

def macd_v(price, volume, fast=12, slow=26, signal=9):
    vw_fast = vwema(price, volume, fast)
    vw_slow = vwema(price, volume, slow)
    macd_line = vw_fast - vw_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def safe_vwap(price, volume, window=20):
    df = pd.DataFrame({"p": price, "v": volume}).dropna()
    if len(df) < window or df["v"].sum() == 0:
        return np.nan
    roll = df.iloc[-window:]
    return float((roll["p"] * roll["v"]).sum() / roll["v"].sum())

@st.cache_data(show_spinner=False)
def fetch_one(ticker, period_days, retries, sleep):
    last_err = None
    for i in range(retries + 1):
        try:
            df = yf.download(ticker, period=f"{period_days}d", interval="1d",
                             progress=False, auto_adjust=False, threads=False)
            if df is not None and not df.empty:
                return df
        except Exception as e:
            last_err = e
        time.sleep(sleep * (i + 1))
    return pd.DataFrame()

def macdv_badge(hist_series):
    if len(hist_series) < 2:
        return "⚠️ Weak/Flat"
    last = float(hist_series.iloc[-1]); prev = float(hist_series.iloc[-2])
    if last > 0 and last > prev: return "✅ Bullish"
    if last < 0: return "❌ Bearish"
    return "⚠️ Weak/Flat"

# ---------- Scan ----------
universe_pairs = build_universe(use_curated, use_ndx100, use_r1000, use_r2000, custom_tickers)
if len(universe_pairs) > max_universe:
    universe_pairs = universe_pairs[: int(max_universe)]
st.info(f"Loaded {len(universe_pairs)} tickers from sources. Scanning…")

records, failures = [], []
progress = st.progress(0)
status_box = st.empty()
required_cols = {"Close","Volume","High","Low"}

for idx, (t, source) in enumerate(universe_pairs, start=1):
    try:
        data = fetch_one(t, days, retries, sleep_s)
        if data.empty or len(data) < 30:
            raise ValueError("empty dataframe")
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [c[0] for c in data.columns]
        if not required_cols.issubset(set(map(str, data.columns))):
            raise KeyError(str(list(required_cols)))
        data = data.dropna(subset=list(required_cols))
        if data.empty:
            raise ValueError("no ohlcv after dropna")

        close = data["Close"]; vol = data["Volume"]; high = data["High"]; low = data["Low"]
        last = float(close.iloc[-1])
        if not np.isfinite(last) or last < min_price:
            raise ValueError("price filter")

        adr20 = float((((high - low) / close).rolling(20).mean().iloc[-1]) * 100.0)
        if not np.isfinite(adr20) or adr20 < min_adr or adr20 > max_adr:
            raise ValueError("adr filter")

        dv20 = float((vol.rolling(20).mean().iloc[-1] * last) / 1e6)
        if not np.isfinite(dv20) or dv20 < min_dollar_vol:
            raise ValueError("dollar vol filter")

        ema20 = close.ewm(span=20, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()
        e20, e50 = float(ema20.iloc[-1]), float(ema50.iloc[-1])
        trend_ok = (e20 > e50) and (last > e20)

        _, _, hist_v = macd_v(close, vol)
        macd_note = macdv_badge(hist_v)
        m_last = float(hist_v.iloc[-1]); m_prev = float(hist_v.iloc[-2]) if len(hist_v) >=2 else m_last
        macd_ok = (m_last > 0) and (m_last > m_prev)

        vol_avg20 = vol.rolling(20).mean()
        v_last, v_avg = float(vol.iloc[-1]), float(vol_avg20.iloc[-1])
        vol_ok = (v_avg > 0) and (v_last >= vol_mult * v_avg)

        prev_high = float(high.iloc[-2]) if len(high) >= 2 else np.nan
        vwap20 = safe_vwap(close, vol, 20)
        breakout_ok = (np.isfinite(prev_high) and last > prev_high) and (np.isfinite(vwap20) and last > vwap20)

        entry, stop = last, e50
        if stop > 0 and entry > stop:
            risk = entry - stop
            target = entry + rr_min * risk
            rr = (target - entry) / risk
            rr_ok = rr >= rr_min
        else:
            target, rr, rr_ok = np.nan, np.nan, False

        # -------- Score 0–5 --------
        score = int(trend_ok) + int(macd_ok) + int(vol_ok) + int(rr_ok) + int(breakout_ok)

        records.append({
            "Ticker": t, "Source": source, "Price": round(last,2),
            "ADR20%": round(adr20,1), "DollarVol20d($M)": round(dv20,1),
            "Entry": round(entry,2), "Stop(EMA50)": round(stop,2),
            "Target": round(target,2) if np.isfinite(target) else None,
            "R/R": round(rr,2) if np.isfinite(rr) else None,
            "Score (0-5)": int(score),
            "TrendOK": bool(trend_ok), "MACD‑V": macd_note,
            "VolOK": bool(vol_ok), "BreakoutOK": bool(breakout_ok)
        })

    except Exception as e:
        failures.append((t, str(e)))

    if idx % 20 == 0 or idx == len(universe_pairs):
        progress.progress(idx / len(universe_pairs))
        status_box.info(f"Scanning {idx}/{len(universe_pairs)}…")

# ---------- Output ----------
def rank_df(df):
    sort_cols = ["Score (0-5)", "R/R", "DollarVol20d($M)"]
    return df.sort_values(by=sort_cols, ascending=[False, False, False]).reset_index(drop=True)

if records:
    df_all = pd.DataFrame(records)
    df_gate = df_all.copy()
    if gate_strict:
        df_gate = df_gate[(df_gate["Score (0-5)"] >= 4) & (df_gate["MACD‑V"] == "✅ Bullish")]

    if len(df_gate) == 0:
        st.warning("No strict passes. Showing **Top‑K fallback** ranked from all candidates (below strict threshold).")
        df_show = rank_df(df_all).head(top_k)
    else:
        df_show = rank_df(df_gate).head(top_k)

    st.subheader(f"Top {len(df_show)} Picks")
    st.dataframe(df_show, use_container_width=True)

    st.download_button("⬇️ Download ALL candidates (pre‑gate) CSV",
                       data=df_all.to_csv(index=False).encode("utf-8"),
                       file_name=f"{export_filename}_all.csv", mime="text/csv")
    if len(df_gate):
        st.download_button("⬇️ Download RANKED (post‑gate) CSV",
                           data=rank_df(df_gate).to_csv(index=False).encode("utf-8"),
                           file_name=f"{export_filename}_ranked.csv", mime="text/csv")
else:
    st.error("No usable data fetched from any ticker (sources returned empty). Try toggling sources or loosening filters.")

if failures:
    with st.expander("Fetch errors / skips (for transparency)"):
        for t, msg in failures[:300]:
            st.write(f"- {t}: {msg}")
