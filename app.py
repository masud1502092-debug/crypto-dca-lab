import time
from datetime import datetime, timedelta, timezone

import ccxt
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Crypto Quality + DCA Lab", layout="wide")
st.title("🪙 Crypto Quality + DCA Lab")
st.caption("Research/backtesting tool only. Scores are transparent heuristics, not investment advice.")

EXCHANGES = ["binance", "kucoin", "bybit", "bitget", "htx"]
NAMES = dict(zip(EXCHANGES, ["Binance", "KuCoin", "Bybit", "Bitget", "HTX"]))
STABLES = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "USDD", "USDP", "PYUSD"}
L1 = {"BTC","ETH","SOL","ADA","AVAX","DOT","ATOM","NEAR","SUI","APT","SEI","TON","TRX","XRP","HBAR","ALGO","ICP","FIL","EGLD","KAS","TIA","INJ","XLM","XTZ","EOS","ETC"}
L2 = {"ARB","OP","MATIC","POL","IMX","STRK","ZK","ZKSYNC","MNT","METIS","LRC","BOBA"}
CG_API = "https://api.coingecko.com/api/v3"

with st.sidebar:
    st.header("DCA Settings")
    drop = st.number_input("Buy trigger: drop from latest buy (%)", .1, 50., 3., .1) / 100
    tp_pct = st.number_input("Take profit above weighted average (%)", .1, 50., 1., .1) / 100
    scale = st.number_input("DCA amount multiplier", 1., 5., 1.10, .05)
    max_steps = int(st.number_input("Maximum DCA additions", 1, 50, 15, 1))
    timeframe = st.selectbox("Historical candle", ["1h", "4h", "1d"], index=1)
    days = int(st.number_input("Historical period (days)", 30, 730, 365, 30))
    min_exchanges = st.slider("Minimum exchanges listed", 1, 5, 2)
    cg_key = st.text_input("CoinGecko Demo API key (optional)", type="password")

@st.cache_resource(ttl=600)
def exchange(eid):
    return getattr(ccxt, eid)({"enableRateLimit": True, "timeout": 25000,
                               "options": {"defaultType": "spot"}})

@st.cache_data(ttl=900, show_spinner=False)
def load_markets():
    loaded, errors = {}, {}
    for eid in EXCHANGES:
        try:
            loaded[eid] = exchange(eid).load_markets()
        except Exception as exc:
            errors[eid] = f"{type(exc).__name__}: {str(exc)[:180]}"
    return loaded, errors

def symbols(markets):
    out = {}
    for sym, m in (markets or {}).items():
        if m.get("active") is False or m.get("spot") is not True or m.get("quote") != "USDT":
            continue
        base = m.get("base")
        if base and base not in STABLES:
            out[base] = sym
    return out

def universe(markets_by_exchange):
    rows = {}
    for eid, markets in markets_by_exchange.items():
        for base, sym in symbols(markets).items():
            rows.setdefault(base, {})[eid] = sym
    records = []
    for base, mapping in rows.items():
        r = {"Coin": base, "Listed_Exchanges": len(mapping)}
        r.update({NAMES[e]: e in mapping for e in EXCHANGES})
        records.append(r)
    return pd.DataFrame(records, columns=["Coin", "Listed_Exchanges", *NAMES.values()]) if not records else pd.DataFrame(records).sort_values(["Listed_Exchanges", "Coin"], ascending=[False, True]).reset_index(drop=True)

def ticker(eid, sym):
    t = exchange(eid).fetch_ticker(sym)
    return {"price": t.get("last") or t.get("close"), "change": t.get("percentage"), "volume": t.get("quoteVolume")}

@st.cache_data(ttl=900, show_spinner=False)
def ohlcv(eid, sym, tf, days):
    ex = exchange(eid)
    now = datetime.now(timezone.utc)
    cursor = int((now - timedelta(days=int(days))).timestamp() * 1000)
    end = int(now.timestamp() * 1000)
    step = ex.parse_timeframe(tf) * 1000
    rows = []
    for _ in range(1500):
        if cursor >= end:
            break
        batch = ex.fetch_ohlcv(sym, timeframe=tf, since=cursor, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        nxt = int(batch[-1][0]) + step
        if nxt <= cursor:
            break
        cursor = nxt
        if len(batch) < 1000:
            break
        time.sleep(max(float(getattr(ex, "rateLimit", 1000)) / 1000, .05))
    if not rows:
        return pd.DataFrame(columns=["timestamp","open","high","low","close","volume","datetime"])
    df = pd.DataFrame(rows, columns=["timestamp","open","high","low","close","volume"])
    df = df.drop_duplicates("timestamp").sort_values("timestamp")
    df = df[df.timestamp <= end]
    df["datetime"] = pd.to_datetime(df.timestamp, unit="ms", utc=True)
    return df.reset_index(drop=True)

@st.cache_data(ttl=1800, show_spinner=False)
def cg_info(symbol, api_key=""):
    headers = {"x-cg-demo-api-key": api_key} if api_key else {}
    try:
        r = requests.get(f"{CG_API}/search", params={"query": symbol}, headers=headers, timeout=15)
        r.raise_for_status()
        coins = [x for x in r.json().get("coins", []) if x.get("symbol", "").upper() == symbol.upper()]
        if not coins:
            return {}
        coins.sort(key=lambda x: (x.get("market_cap_rank") is None, x.get("market_cap_rank") or 10**9))
        cid = coins[0]["id"]
        r = requests.get(f"{CG_API}/coins/{cid}", params={
            "localization":"false", "tickers":"false", "market_data":"true",
            "community_data":"false", "developer_data":"false", "sparkline":"false"
        }, headers=headers, timeout=15)
        r.raise_for_status()
        d = r.json()
        md = d.get("market_data", {})
        return {"id":cid, "name":d.get("name"), "description":d.get("description",{}).get("en","")[:600],
                "categories":d.get("categories",[]), "market_cap":md.get("market_cap",{}).get("usd"),
                "rank":md.get("market_cap_rank"), "ath":md.get("ath",{}).get("usd"),
                "current":md.get("current_price",{}).get("usd")}
    except Exception:
        return {}

def layer_for(symbol, cg):
    cats = " ".join(cg.get("categories", [])).lower()
    if symbol in L2 or "layer 2" in cats or "layer-2" in cats: return "Layer 2"
    if symbol in L1 or "layer 1" in cats or "smart contract platform" in cats: return "Layer 1"
    if symbol in STABLES or "stablecoin" in cats: return "Stablecoin"
    return "Other / Unverified"

def score_coin(layer, cg, coverage, hist=None, dca=None):
    reasons, fundamentals, market_pts, dca_pts = [], 0, 0, 0
    rank, cap = cg.get("rank"), cg.get("market_cap") or 0
    if rank:
        points = 20 if rank <= 20 else 16 if rank <= 50 else 12 if rank <= 100 else 7 if rank <= 250 else 0
        fundamentals += points
        reasons.append(f"Market-cap rank {rank}: +{points}/20")
    else: reasons.append("Market-cap rank unavailable: +0")
    points = 12 if cap >= 10e9 else 9 if cap >= 1e9 else 5 if cap >= 250e6 else 0
    fundamentals += points
    reasons.append(f"Market-cap size: +{points}/12")
    if layer in ("Layer 1", "Layer 2"):
        fundamentals += 8; reasons.append(f"{layer} classification: +8")
    if "meme" in " ".join(cg.get("categories", [])).lower():
        fundamentals = max(0, fundamentals - 12); reasons.append("Meme-category risk: -12")
    fundamentals = min(40, fundamentals)
    coverage_pts = coverage / 5 * 20
    reasons.append(f"Listed on {coverage}/5 exchanges: +{coverage_pts:.0f}/20")

    metrics = {}
    if hist is not None and not hist.empty and len(hist) > 2:
        c = hist.close.astype(float)
        ret = (c.iloc[-1] / c.iloc[0] - 1) * 100
        mdd = ((c / c.cummax()) - 1).min() * 100
        rets = c.pct_change().dropna()
        span_days = max((hist.datetime.iloc[-1] - hist.datetime.iloc[0]).total_seconds() / 86400, 1)
        periods_year = len(rets) * 365 / span_days
        vol = rets.std() * (periods_year ** .5) * 100
        market_pts += 8 if mdd > -30 else 5 if mdd > -60 else 0
        market_pts += 7 if vol < 80 else 4 if vol < 120 else 0
        market_pts += 5 if ret > 0 else 0
        metrics = {"Period return %":ret, "Max drawdown %":mdd, "Annualized volatility %":vol}
        reasons.append(f"Market health: drawdown {mdd:.1f}%, volatility {vol:.1f}%, return {ret:.1f}% (+{market_pts}/20)")
    else: reasons.append("Market health not scored until backtest history is loaded")
    if dca and dca.get("cycles", 0):
        sample_factor = min(dca["cycles"] / 10, 1)
        dca_pts = round(min(20, max(0, dca["pass_rate"] * .20)) * sample_factor, 1)
        reasons.append(f"DCA PASS {dca['pass_rate']:.1f}% over {dca['cycles']} cycles (+{dca_pts}/20)")
    else: reasons.append("DCA score awaits a completed backtest")
    total = round(min(100, fundamentals + coverage_pts + market_pts + dca_pts), 1)
    rating = "A — STRONG" if total >= 80 else "B — GOOD" if total >= 65 else "C — WATCH" if total >= 50 else "D — HIGH RISK"
    return total, rating, "; ".join(reasons), metrics

def backtest(df, drop=.03, tp=.01, scale=1.1, max_steps=15, initial_qty=1.0):
    """OHLC approximation. At most one DCA fill per candle; if DCA and TP both possible, DCA wins."""
    if df is None or df.empty or len(df) < 2: return pd.DataFrame(), {}
    trades, state = [], None
    data = df.sort_values("timestamp").reset_index(drop=True)
    def start(price, dt):
        return {"start":dt, "start_price":price, "avg_entry":price, "qty":initial_qty,
                "next_qty":initial_qty*scale, "buys":1, "dca_additions":0,
                "next_buy":price*(1-drop), "min_price":price, "cash_invested":price*initial_qty}
    def close(price, dt, result, reason):
        nonlocal state
        trades.append({"start":state["start"], "end":dt, "start_price":state["start_price"],
            "exit_price":price, "avg_entry":state["avg_entry"], "buys":state["buys"],
            "dca_additions":state["dca_additions"], "min_price":state["min_price"],
            "max_steps_reached":state["dca_additions"] >= max_steps,
            "cash_invested":state["cash_invested"],
            "return_pct":(price/state["avg_entry"]-1)*100, "result":result, "reason":reason})
        state = None
    for r in data.itertuples(index=False):
        o,h,l,c = float(r.open),float(r.high),float(r.low),float(r.close)
        if state is None: state = start(o, r.datetime)
        state["min_price"] = min(state["min_price"], l)
        dca_hit = l <= state["next_buy"] and state["dca_additions"] < max_steps
        tp_hit = h >= state["avg_entry"]*(1+tp)
        if dca_hit:
            p = state["next_buy"]; add = state["next_qty"]; old_qty = state["qty"]
            state["qty"] += add
            state["avg_entry"] = (old_qty*state["avg_entry"] + add*p) / state["qty"]
            state["cash_invested"] += add*p
            state["buys"] += 1; state["dca_additions"] += 1
            state["next_qty"] *= scale; state["next_buy"] = p*(1-drop)
            continue
        if tp_hit:
            close(state["avg_entry"]*(1+tp), r.datetime, "PASS", "Take-profit hit")
    if state is not None:
        last = data.iloc[-1]
        reason = "Period ended before recovery"
        if state["dca_additions"] >= max_steps: reason = "Maximum DCA additions reached; not recovered by period end"
        close(float(last.close), last.datetime, "FAIL_UNRECOVERED", reason)
    trades = pd.DataFrame(trades)
    if trades.empty: return trades, {}
    passes = int((trades.result == "PASS").sum())
    return trades, {"cycles":len(trades), "pass":passes, "fail":int((trades.result=="FAIL_UNRECOVERED").sum()),
                    "pass_rate":passes/len(trades)*100, "max_buys":int(trades.buys.max()),
                    "avg_buys":float(trades.buys.mean()), "worst_end_return":float(trades.return_pct.min())}

with st.spinner("Loading exchange markets independently..."):
    markets, errors = load_markets()
if errors:
    with st.expander(f"Exchange API warnings ({len(errors)})"):
        for eid, err in errors.items(): st.warning(f"{NAMES[eid]}: {err}")
        st.caption("403/451 may indicate hosting-region or API restrictions. Failed exchanges do not block the others.")
all_coins = universe(markets)
if all_coins.empty:
    st.error("No exchange USDT spot markets loaded. The host may be blocked by all configured exchange APIs. Try again later or deploy elsewhere.")
    st.stop()
filtered = all_coins[all_coins.Listed_Exchanges >= min_exchanges]
if filtered.empty:
    st.warning("No coins match the exchange filter. Reduce 'Minimum exchanges listed' in the sidebar.")
    st.stop()

a,b,c = st.columns(3)
a.metric("Coins found", len(all_coins)); b.metric("Listed on all 5", int((all_coins.Listed_Exchanges==5).sum())); c.metric("Working exchanges", len(markets))
coin = st.selectbox("Select coin", filtered.Coin.tolist())
row = filtered[filtered.Coin == coin].iloc[0]
prices = []
for eid in EXCHANGES:
    sym = symbols(markets.get(eid, {})).get(coin)
    if not sym:
        prices.append({"Exchange":NAMES[eid],"Pair":"-","Listed":"NO","Current Price":None,"24h %":None,"24h Quote Volume":None})
    else:
        try:
            t = ticker(eid, sym)
            prices.append({"Exchange":NAMES[eid],"Pair":sym,"Listed":"YES","Current Price":t["price"],"24h %":t["change"],"24h Quote Volume":t["volume"]})
        except Exception:
            prices.append({"Exchange":NAMES[eid],"Pair":sym,"Listed":"YES","Current Price":None,"24h %":None,"24h Quote Volume":None})
price_df = pd.DataFrame(prices)
cg = cg_info(coin, cg_key)
layer = layer_for(coin, cg)
base_score, base_rating, base_reason, _ = score_coin(layer, cg, int(row.Listed_Exchanges))
st.subheader(f"{coin} — Coin Profile")
a,b,c,d = st.columns(4)
a.metric("Layer", layer); b.metric("Base Score", f"{base_score}/100"); c.metric("Base Rating", base_rating); d.metric("Exchange Coverage", f"{int(row.Listed_Exchanges)}/5")
st.write("**Why this score?**", base_reason)
if cg:
    cap = cg.get("market_cap")
    st.caption(f"{cg.get('name') or coin} | Market-cap rank: {cg.get('rank') or 'N/A'} | Market cap: {('$'+format(cap, ',.0f')) if isinstance(cap,(int,float)) else 'N/A'}")
    if cg.get("description"):
        with st.expander("Project description"): st.write(cg["description"])
else: st.info("CoinGecko data unavailable/rate-limited; fundamental score may be understated.")
st.dataframe(price_df, use_container_width=True, hide_index=True)

st.subheader("Historical DCA Test")
sources = [NAMES[e] for e in EXCHANGES if bool(row.get(NAMES[e], False)) and e in markets]
if not sources:
    st.warning("No working exchange available for this coin's historical data."); st.stop()
source = st.selectbox("Historical data source", sources)
eid = next(e for e in EXCHANGES if NAMES[e] == source)
sym = symbols(markets[eid])[coin]
st.write(f"**Strategy:** initial buy → every {drop*100:.2f}% fall from latest buy → order multiplier {scale:.2f}× → TP {tp_pct*100:.2f}% above weighted average → max {max_steps} additional DCA buys.")
st.caption("OHLC backtest approximation: if DCA and TP could both hit in one candle, DCA is assumed first. Fees, slippage, spread and exact intrabar path are not modelled. Open cycle at period end is FAIL_UNRECOVERED, not proof it will never recover.")
if st.button("▶ Run / Refresh Backtest", type="primary"):
    try:
        with st.spinner(f"Downloading {days} days of {sym} from {source}..."):
            hist = ohlcv(eid, sym, timeframe, days)
        if hist.empty or len(hist) < 2: st.error("Not enough historical candles returned.")
        else:
            trades, summary = backtest(hist, drop, tp_pct, scale, max_steps)
            updated_score, updated_rating, reasons, metrics = score_coin(layer, cg, int(row.Listed_Exchanges), hist, summary)
            st.session_state["result"] = (trades, summary, updated_score, updated_rating, reasons, metrics, hist, coin, source, days, timeframe)
    except Exception as exc:
        st.error(f"Backtest failed: {type(exc).__name__}: {str(exc)[:300]}")

if "result" in st.session_state:
    trades, s, total, rating, reasons, metrics, hist, tested_coin, tested_source, tested_days, tested_tf = st.session_state["result"]
    st.success(f"Backtest completed: {tested_coin} on {tested_source} ({tested_days} days, {tested_tf})")
    a,b,c,d,e = st.columns(5)
    a.metric("Cycles", s["cycles"]); b.metric("PASS", s["pass"]); c.metric("FAIL / Unrecovered", s["fail"])
    d.metric("Pass rate", f'{s["pass_rate"]:.1f}%'); e.metric("UPDATED SCORE", f"{total}/100")
    st.markdown(f"### Rating: **{rating}**")
    st.write("**Updated score reasoning:**", reasons)
    if metrics:
        a,b,c = st.columns(3)
        a.metric("Period return", f'{metrics["Period return %"]:.1f}%')
        b.metric("Maximum drawdown", f'{metrics["Max drawdown %"]:.1f}%')
        c.metric("Annualized volatility", f'{metrics["Annualized volatility %"]:.1f}%')
    st.info("Score = fundamentals (40) + five-exchange coverage (20) + market health (20) + DCA history (20). Heuristic score, not a future-profit probability.")
    if not trades.empty:
        view = trades.copy()
        for col in ("start","end"): view[col] = pd.to_datetime(view[col], utc=True).dt.strftime("%Y-%m-%d %H:%M UTC")
        st.dataframe(view, use_container_width=True, hide_index=True)
        st.download_button("Download DCA CSV", trades.to_csv(index=False).encode("utf-8"),
                           f"{tested_coin}_DCA_backtest.csv", "text/csv")
    with st.expander("Last 100 historical candles"):
        st.write(f"{len(hist):,} candles fetched.")
        st.dataframe(hist.tail(100), use_container_width=True, hide_index=True)

st.divider()
st.subheader("Score guide")
st.markdown("**A (80–100):** stronger profile under this heuristic.  \n**B (65–79):** generally good but with weaknesses.  \n**C (50–64):** watchlist / investigate.  \n**D (<50):** higher risk under this heuristic.  \n\nThe score is not a prediction. It excludes fees, slippage, spread, token unlocks, audited code verification, and delisting/execution risks.")
