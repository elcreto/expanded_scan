
import time, os, io
import pandas as pd
import numpy as np
import streamlit as st
import yfinance as yf

APP_NAME = "🚀 Expanded Universe Scanner v1.3.1 — MACD‑V, Score 0–5, Static S&P/Russell Cache"
st.set_page_config(page_title=APP_NAME, layout="wide")
st.title(APP_NAME)
st.caption("Reliable universes with static on-disk caches. First run can auto-fetch; subsequent runs use local CSVs even if the web breaks. "
           "Scoring 0–5 (Trend, MACD‑V, Volume, R/R, Breakout). NaN‑safe VWAP. Top‑K fallback.")

DATA_DIR = "universes"
os.makedirs(DATA_DIR, exist_ok=True)

# ---------- Sidebar ----------
with st.sidebar:
    st.subheader("Universe Sources (static caches preferred)")
    use_curated = st.checkbox("Curated Wild Cards", value=True)
    use_sp500  = st.checkbox("S&P 500 (cached CSV)", value=True)
    use_ndx100 = st.checkbox("Nasdaq‑100 (cached CSV)", value=True)
    use_r1000  = st.checkbox("Russell 1000 (cached CSV)", value=False)
    use_r2000  = st.checkbox("Russell 2000 (cached CSV)", value=False)
    custom_tickers = st.text_area("Custom tickers (comma‑separated)", "", height=80)

    st.markdown("---")
    st.subheader("Static Cache Control")
    st.write("If a CSV exists in /universes, it will be used. You can (re)build caches below.")
    rebuild = st.button("🔁 Fetch & (Re)build Caches Now")

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
    max_universe = st.number_input("Max tickers to scan", min_value=100, value=2000, step=100)
    days = st.slider("Lookback period (days)", 60, 365, 180)
    retries = st.slider("Max retries per ticker", 0, 5, 2)
    sleep_s = st.number_input("Sleep between downloads (sec)", min_value=0.0, value=0.10, step=0.02)
    export_filename = st.text_input("Export base filename", "expanded_universe_v131_static")
    gate_strict = st.checkbox("Gate to high‑conviction only (Score≥4 AND MACD‑V ✅)", value=True)
    top_k = st.slider("Top K to display", 3, 25, 5)

# ---------- Starter seed lists ----------
CURATED = sorted(list({
    "SMCI","PLTR","AMD","ARM","TSM","AEHR","AI","IONQ","UPST","SOUN","CELH","NET","DDOG","PATH","U","AFRM",
    "RIOT","MARA","RIVN","LCID","ROKU","HOOD","TOST","COIN","CRNX","RXRX","BMRN","CRSP","TWLO","SNOW","MDB",
    "ZS","OKTA","BILL","ASAN","SHOP","SOFI","GLBE","BMBL","VRT","ENVX","WOLF","ON","RUN","ENPH","FSLR","SEDG",
    "HIMS","AXON","APP","CFLT","MQ","FSLY","PVH","CPNG","PINS","TTD","BABA","JD","PDD","NIO","XPEV","LI","GTLB",
    "ELF","CRWD","DOCN","RBLX","DKNG","IOT","INFA","CAVA","SATS","WBD","NBIS"
}))

SP500_STARTER = sorted(list({
    "AAPL","MSFT","AMZN","META","GOOGL","GOOG","NVDA","BRK-B","JPM","TSLA","UNH","XOM","LLY","V","MA","PG",
    "HD","COST","AVGO","ADBE","CRM","PEP","KO","MRK","ABBV","TMO","CSCO","WMT","MCD","BAC","NFLX","ACN","ABT","DHR",
    "LIN","CMCSA","INTC","WFC","TXN","AMD","HON","NEE","PM","UNP","CVX","LOW","ORCL","QCOM","INTU","AMAT","IBM",
    "CAT","AMGN","GS","GE","RTX","MDT","NOW","LMT","BKNG","BLK","MU","ADI","ISRG","REGN","PYPL","GILD","PFE"
}))

NDX100_STARTER = sorted(list({
    "ADBE","ADI","ADP","AMAT","AMD","AMGN","AMZN","ASML","AVGO","CDNS","CMCSA","COST","CPRT","CRWD","CSCO","CSX",
    "CTAS","DDOG","DXCM","EA","ENPH","FTNT","GFS","GILD","GOOG","GOOGL","HON","IDXX","ILMN","INTC","INTU","ISRG","KLAC",
    "LRCX","LULU","MAR","MCHP","META","MNST","MRVL","MSFT","MU","NFLX","NVDA","NXPI","ODFL","ORLY","PANW","PEP",
    "PYPL","QCOM","REGN","ROST","SBUX","SNPS","TMUS","TSLA","TSM","TTD","TXN","VRSK","VRTX","WDAY","XEL","ZM"
}))

# ---------- Cache I/O ----------
DATA_DIR = "universes"
def write_cache(name, symbols):
    path = os.path.join(DATA_DIR, f"{name}.csv")
    pd.Series(sorted(set([s.replace('.','-').upper() for s in symbols if isinstance(s,str) and s.strip()]))).to_csv(path, index=False, header=["Symbol"])
    return path

def read_cache(name):
    path = os.path.join(DATA_DIR, f"{name}.csv")
    if os.path.exists(path):
        s = pd.read_csv(path)["Symbol"].astype(str).tolist()
        return [x.replace(".","-").upper() for x in s]
    return []

def _try_read_html(url, col):
    try:
        tabs = pd.read_html(url)
        for t in tabs:
            if col in t.columns:
                return t[col].astype(str).tolist()
    except Exception:
        return []
    return []

def build_or_load(name, starter, fetch_urls):
    cached = read_cache(name)
    if cached:
        return cached, True
    syms = []
    for (url, col) in fetch_urls:
        syms = _try_read_html(url, col)
        if syms:
            break
    if not syms:
        syms = starter
    write_cache(name, syms)
    return syms, False

if rebuild:
    st.info("Rebuilding caches…")
    sp_syms, _ = build_or_load("sp500", SP500_STARTER, [
        ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "Symbol"),
        ("https://www.slickcharts.com/sp500", "Symbol"),
    ])
    ndx_syms, _ = build_or_load("nasdaq100", NDX100_STARTER, [
        ("https://en.wikipedia.org/wiki/Nasdaq-100", "Ticker"),
    ])
    r1k_syms, _ = build_or_load("russell1000", [], [
        ("https://en.wikipedia.org/wiki/Russell_1000_Index", "Symbol"),
        ("https://en.wikipedia.org/wiki/Russell_1000_Index", "Ticker"),
    ])
    r2k_syms, _ = build_or_load("russell2000", [], [
        ("https://en.wikipedia.org/wiki/Russell_2000_Index", "Symbol"),
        ("https://en.wikipedia.org/wiki/Russell_2000_Index", "Ticker"),
    ])
    st.success(f"Caches saved: SP500={len(sp_syms)}, NDX100={len(ndx_syms)}, R1000={len(r1k_syms)}, R2000={len(r2k_syms)}")

def assemble_universe():
    symbols = []
    if use_curated:
        symbols += [(s, "Curated") for s in CURATED]
    if use_sp500:
        syms, _ = build_or_load("sp500", SP500_STARTER, [
            ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "Symbol"),
            ("https://www.slickcharts.com/sp500", "Symbol"),
        ])
        symbols += [(s, "SP500") for s in syms]
    if use_ndx100:
        syms, _ = build_or_load("nasdaq100", NDX100_STARTER, [
            ("https://en.wikipedia.org/wiki/Nasdaq-100", "Ticker"),
        ])
        symbols += [(s, "NDX100") for s in syms]
    if use_r1000:
        syms, _ = build_or_load("russell1000", [], [
            ("https://en.wikipedia.org/wiki/Russell_1000_Index", "Symbol"),
            ("https://en.wikipedia.org/wiki/Russell_1000_Index", "Ticker"),
        ])
        symbols += [(s, "R1000") for s in syms]
    if use_r2000:
        syms, _ = build_or_load("russell2000", [], [
            ("https://en.wikipedia.org/wiki/Russell_2000_Index", "Symbol"),
            ("https://en.wikipedia.org/wiki/Russell_2000_Index", "Ticker"),
        ])
        symbols += [(s, "R2000") for s in syms]
    if custom_tickers:
        extra = [x.strip().upper().replace(".", "-") for x in custom_tickers.split(",") if x.strip()]
        symbols += [(s, "Custom") for s in extra]
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

# Scan
universe_pairs = assemble_universe()
if len(universe_pairs) > max_universe:
    universe_pairs = universe_pairs[: int(max_universe)]
st.info(f"Loaded {len(universe_pairs)} tickers from caches/sources. Scanning…")

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

    if idx % 50 == 0 or idx == len(universe_pairs):
        progress.progress(idx / len(universe_pairs))
        status_box.info(f"Scanning {idx}/{len(universe_pairs)}…")

def rank_df(df):
    sort_cols = ["Score (0-5)", "R/R", "DollarVol20d($M)"]
    return df.sort_values(by=sort_cols, ascending=[False, False, False]).reset_index(drop=True)

if records:
    df_all = pd.DataFrame(records)
    df_gate = df_all.copy()
    if gate_strict:
        df_gate = df_gate[(df_gate["Score (0-5)"] >= 4) & (df_gate["MACD‑V"] == "✅ Bullish")]

    if len(df_gate) == 0:
        st.warning("No strict passes. Showing Top‑K fallback from all candidates (below strict threshold).")
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
    st.error("No usable data fetched from any ticker. Loosen filters or build caches.")

if failures:
    with st.expander("Fetch errors / skips (up to 400 shown)"):
        for t, msg in failures[:400]:
            st.write(f"- {t}: {msg}")
