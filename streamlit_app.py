import time
import pandas as pd
import numpy as np
import streamlit as st
import yfinance as yf

APP_NAME = "🚀 Expanded Universe Scanner v1.2 — MACD‑V + Weighted Scoring (Top‑5)"
st.set_page_config(page_title=APP_NAME, layout="wide")
st.title(APP_NAME)
st.caption("Multi‑source universe (wild cards + indices). MACD‑V only. Weighted 0–8 score. Auto Top‑5. Full CSV available.")

# ---------------- Sidebar ----------------
with st.sidebar:
    st.subheader("Universe Sources")
    use_curated = st.checkbox("Curated Wild Cards (AI/biotech/semis/IPO)", value=True)
    use_ndx100  = st.checkbox("Nasdaq‑100", value=True)
    use_r1000   = st.checkbox("Russell 1000", value=False)
    use_r2000   = st.checkbox("Russell 2000", value=True)
    custom_tickers = st.text_area("Custom tickers (comma‑separated)", "", height=80)
    st.markdown("---")
    st.subheader("Filters")
    vol_mult = st.number_input("Volume multiple (vs 20‑day avg) ≥", min_value=1.0, value=2.5, step=0.1)
    rr_min = st.number_input("Min Risk/Reward (R) ≥", min_value=1.0, value=2.0, step=0.5)
    min_price = st.number_input("Min last price ($) ≥", min_value=0.0, value=10.0, step=1.0)
    min_dollar_vol = st.number_input("Min dollar volume 20d ($M/day) ≥", min_value=0.0, value=20.0, step=1.0)
    max_adr = st.number_input("Max ADR(20) % ≤", min_value=1.0, value=18.0, step=1.0)
    min_adr = st.number_input("Min ADR(20) % ≥", min_value=0.5, value=3.0, step=0.5)
    st.markdown("---")
    st.subheader("Runtime")
    max_universe = st.number_input("Max tickers to scan", min_value=100, value=1200, step=100)
    days = st.slider("Lookback period (days)", 60, 365, 180)
    retries = st.slider("Max retries per ticker", 0, 5, 2)
    sleep_s = st.number_input("Sleep between downloads (sec)", min_value=0.0, value=0.12, step=0.02)
    export_filename = st.text_input("Export base filename", "expanded_universe_v12_weighted")
    gate_strict = st.checkbox("Gate to high‑conviction only (WeightedScore≥5 AND MACD‑V ✅)", value=True)
    show_full_table = st.checkbox("Also show full candidates table", value=False)
    top_k = st.slider("Top K to display", 3, 25, 5)

# ---------------- Universe builders ----------------
def fetch_table(url, col, rename=None):
    try:
        tables = pd.read_html(url)
        for t in tables:
            if col in t.columns:
                s = t[col].astype(str)
                if rename:
                    s = s.str.replace(rename[0], rename[1], regex=False)
                return s.tolist()
    except Exception:
        return []
    return []

# Curated wild‑card seed list
CURATED = [
    "NBIS","SMCI","PLTR","AMD","ARM","TSM","AEHR","NVAX","AI","IONQ","UPST","SOUN","CELH","NET","DDOG","PATH","U","AFRM",
    "RIOT","MARA","RIVN","LCID","ROKU","HOOD","TOST","COIN","CRNX","ABCM","SANA","RXRX","BMRN","CRSP","TWLO","SNOW","MDB",
    "ZS","OKTA","BILL","ASAN","SHOP","SOFI","BROS","GLBE","BMBL","VRT","ENVX","WOLF","ON","AMBA","RUN","ENPH","FSLR","SEDG",
    "WIX","HIMS","RXST","KNSL","AXON","ESTC","APP","CFLT","MQ","LC","FSLY","PVH","CPNG","PINS","PARA","TTD","ROIV","BABA",
    "JD","PDD","NIO","XPEV","LI","ZIM","GTLB","ELF","TPR","CRWD","DOCN","RBLX","DKNG","BNFT","IOT","INFA","CAVA","SATS","WBD",
    "BESIY","BEKE","KVYO","ROIV","KVYO"
]
CURATED = list(dict.fromkeys(CURATED))

@st.cache_data(show_spinner=True)
def build_universe(use_curated, use_ndx100, use_r1000, use_r2000, custom):
    symbols = []
    if use_curated:
        symbols += [(s, "Curated") for s in CURATED]
    if use_ndx100:
        syms = fetch_table("https://en.wikipedia.org/wiki/Nasdaq-100", "Ticker")
        symbols += [(s.replace(".", "-").upper(), "NDX100") for s in syms]
    if use_r1000:
        syms = fetch_table("https://en.wikipedia.org/wiki/Russell_1000_Index", "Ticker")
        symbols += [(s.replace(".", "-").upper(), "R1000") for s in syms]
    if use_r2000:
        syms = fetch_table("https://en.wikipedia.org/wiki/Russell_2000_Index", "Ticker")
        symbols += [(s.replace(".", "-").upper(), "R2000") for s in syms]
    if custom:
        extra = [x.strip().upper().replace(".", "-") for x in custom.split(",") if x.strip()]
        symbols += [(s, "Custom") for s in extra]
    # de‑dupe (keep first source tag encountered)
    seen = set()
    out = []
    for s, src in symbols:
        if not s or s in seen:
            continue
        seen.add(s)
        out.append((s, src))
    return out

universe_pairs = build_universe(use_curated, use_ndx100, use_r1000, use_r2000, custom_tickers)
if len(universe_pairs) > max_universe:
    universe_pairs = universe_pairs[: int(max_universe)]

st.info(f"Loaded {len(universe_pairs)} tickers from sources. Scanning…")

# ---------------- Indicators ----------------
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

def macdv_badge_and_weight(hist_series):
    if len(hist_series) < 2:
        return "⚠️ Weak/Flat", 1
    last = float(hist_series.iloc[-1])
    prev = float(hist_series.iloc[-2])
    if last > 0 and last > prev:
        return "✅ Bullish", 2
    if last < 0:
        return "❌ Bearish", 0
    return "⚠️ Weak/Flat", 1

def macdv_slope(hist_series, span=3):
    if len(hist_series) < span+1:
        return 0.0
    return float(hist_series.iloc[-1] - hist_series.iloc[-span-1])

def consistency_score(close, vol, days_window=5):
    # Count how many of last N days met core gates: trend_ok & macdv rising
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    _, _, hist_v = macd_v(close, vol)
    count = 0
    for i in range(1, min(days_window+1, len(close))):
        c = float(close.iloc[-i])
        e20 = float(ema20.iloc[-i])
        e50 = float(ema50.iloc[-i])
        trend_ok = (e20 > e50) and (c > e20)
        if len(hist_v) >= i+1:
            last = float(hist_v.iloc[-i])
            prev = float(hist_v.iloc[-i-1])
            macdv_up = (last > 0) and (last > prev)
        else:
            macdv_up = False
        if trend_ok and macdv_up:
            count += 1
    return count

# ---------------- Scan loop ----------------
records, failures = [], []
progress = st.progress(0)
status_box = st.empty()

for idx, (t, source) in enumerate(universe_pairs, start=1):
    try:
        data = fetch_one(t, days, retries, sleep_s)
        if data.empty or len(data) < 30:
            continue

        close = data["Close"]
        vol = data["Volume"].fillna(0)
        high = data["High"]; low = data["Low"]

        last = float(close.iloc[-1])
        if not np.isfinite(last) or last < min_price:
            continue

        # ADR(20)
        adr20 = float(((high - low) / close).rolling(20).mean().iloc[-1] * 100.0)
        if not np.isfinite(adr20) or adr20 < min_adr or adr20 > max_adr:
            continue

        # Dollar volume 20d
        dv20 = float((vol.rolling(20).mean().iloc[-1] * last) / 1e6)  # in $M
        if not np.isfinite(dv20) or dv20 < min_dollar_vol:
            continue

        # EMAs and trend
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()
        e20, e50 = float(ema20.iloc[-1]), float(ema50.iloc[-1])
        trend_ok = (e20 > e50) and (last > e20)

        # MACD‑V and slope
        _, _, hist_v = macd_v(close, vol)
        macd_note, macd_weight = macdv_badge_and_weight(hist_v)
        m_last = float(hist_v.iloc[-1])
        m_prev = float(hist_v.iloc[-2]) if len(hist_v) >= 2 else m_last
        macd_ok = (m_last > 0) and (m_last > m_prev)
        slope3 = macdv_slope(hist_v, span=3)

        # Volume relative
        vol_avg20 = vol.rolling(20).mean()
        v_last, v_avg = float(vol.iloc[-1]), float(vol_avg20.iloc[-1])
        vol_ok = (v_avg > 0) and (v_last >= vol_mult * v_avg)

        # Breakout confirm: close above yesterday's high and > 20‑day VWAP
        prev_high = float(high.iloc[-2]) if len(high) >= 2 else np.nan
        vwap20 = float((close.rolling(20).apply(lambda s: np.average(s, weights=vol.loc[s.index]), raw=False)).iloc[-1])
        breakout_ok = (np.isfinite(prev_high) and last > prev_high) and (np.isfinite(vwap20) and last > vwap20)

        # R/R with stop at EMA50
        entry, stop = last, e50
        if stop > 0 and entry > stop:
            risk = entry - stop
            target = entry + rr_min * risk
            rr = (target - entry) / risk
            rr_ok = rr >= rr_min
        else:
            target, rr, rr_ok = None, None, False

        # Weighted scoring (0–8)
        score = 0
        score += 2 if trend_ok else 0                      # Trend
        score += (2 if macd_note.startswith("✅") else (1 if macd_note.startswith("⚠️") else 0))  # MACD‑V badge
        score += 1 if vol_ok else 0                        # Volume
        score += 1 if rr_ok else 0                         # R/R
        score += 1 if breakout_ok else 0                   # Breakout confirm
        catalyst_pts = 0                                   # placeholder for future news hook
        score += catalyst_pts

        # Consistency over last 5 sessions (count of days meeting trend+macdv_up)
        cons = consistency_score(close, vol, days_window=5)

        records.append({
            "Ticker": t,
            "Source": source,
            "Price": round(last, 2),
            "ADR20%": round(adr20, 1),
            "DollarVol20d($M)": round(dv20, 1),
            "Entry": round(entry, 2),
            "Stop(EMA50)": round(stop, 2) if stop else None,
            "Target": round(target, 2) if target else None,
            "R/R": round(rr, 2) if rr else None,
            "WeightedScore (0-8)": score,
            "TrendOK": bool(trend_ok),
            "MACD‑V": macd_note,
            "VolOK": bool(vol_ok),
            "BreakoutOK": bool(breakout_ok),
            "MACD_Slope3": round(slope3, 4),
            "Consistency(5d)": int(cons)
        })

    except Exception as e:
        failures.append((t, str(e)))

    if idx % 20 == 0 or idx == len(universe_pairs):
        progress.progress(idx / len(universe_pairs))
        status_box.info(f"Scanning {idx}/{len(universe_pairs)}…")

# ---------------- Output & Ranking ----------------
if records:
    df = pd.DataFrame(records)
    # Gate if enabled
    if gate_strict:
        df = df[(df["WeightedScore (0-8)"] >= 5) & (df["MACD‑V"] == "✅ Bullish")]
    # Ranking columns: Score desc → R/R desc → DollarVol desc → MACD_Slope3 desc → Consistency desc
    sort_cols = ["WeightedScore (0-8)", "R/R", "DollarVol20d($M)", "MACD_Slope3", "Consistency(5d)"]
    df_ranked = df.sort_values(by=sort_cols, ascending=[False, False, False, False, False]).reset_index(drop=True)

    st.subheader(f"Top {min(top_k, len(df_ranked))} Picks")
    st.dataframe(df_ranked.head(top_k), use_container_width=True)

    # CSVs
    csv_all = pd.DataFrame(records).to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download ALL candidates (pre‑gate) CSV", data=csv_all, file_name=f"{export_filename}_all.csv", mime="text/csv")

    csv_ranked = df_ranked.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download RANKED (post‑gate) CSV", data=csv_ranked, file_name=f"{export_filename}_ranked.csv", mime="text/csv")

    if show_full_table:
        st.subheader("Full Candidates (post‑gate)")
        st.dataframe(df_ranked, use_container_width=True)
else:
    st.warning("No candidates passed filters. Consider loosening thresholds or sources.")

if failures:
    with st.expander("Fetch errors / skips"):
        for t, msg in failures:
            st.write(f"- {t}: {msg}")
