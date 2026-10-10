import time
from datetime import datetime, timedelta, timezone

import ccxt
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Crypto Coin ও DCA বিশ্লেষণ", page_icon="🪙", layout="wide")

EXCHANGES = ["binance", "kucoin", "bybit", "bitget", "htx"]
EXCHANGE_BN = {"binance": "Binance", "kucoin": "KuCoin", "bybit": "Bybit", "bitget": "Bitget", "htx": "HTX"}
STABLES = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "USDD", "USDP", "PYUSD"}
L1 = {"BTC","ETH","SOL","ADA","AVAX","DOT","ATOM","NEAR","SUI","APT","SEI","TON","TRX","XRP","HBAR","ALGO","ICP","FIL","EGLD","KAS","TIA","INJ","XLM","XTZ","EOS","ETC"}
L2 = {"ARB","OP","MATIC","POL","IMX","STRK","ZK","ZKSYNC","MNT","METIS","LRC","BOBA"}
CG_API = "https://api.coingecko.com/api/v3"

st.title("🪙 Crypto Coin Scanner ও DCA পরীক্ষাগার")
st.caption("উদ্দেশ্য: কয়েন যাচাই, এক্সচেঞ্জে listing দেখা, এবং আপনার DCA নিয়ম অতীতের দামে পরীক্ষা করা। এটি লাভের নিশ্চয়তা বা বিনিয়োগ পরামর্শ নয়।")

with st.sidebar:
    st.header("⚙️ আপনার DCA নিয়ম")
    st.markdown("এখানে সংখ্যা বদলালে পরের backtest-এ সেই নিয়ম ব্যবহার হবে।")
    drop_pct = st.number_input("কত % দাম কমলে পরের Buy? (%)", 0.1, 50.0, 3.0, 0.1) / 100
    tp_pct = st.number_input("গড় Buy price-এর ওপরে লাভের লক্ষ্য (%)", 0.1, 50.0, 1.0, 0.1) / 100
    scale = st.number_input("প্রতিবার Buy amount কত গুণ হবে?", 1.0, 5.0, 1.10, 0.05)
    max_steps = int(st.number_input("প্রথম Buy-এর পর সর্বোচ্চ অতিরিক্ত Buy", 1, 50, 15, 1))
    timeframe = st.selectbox("প্রতি candle-এর সময়", ["1h", "4h", "1d"], index=1)
    days = int(st.number_input("কত দিনের পুরোনো data পরীক্ষা করবেন?", 30, 730, 365, 30))
    min_exchanges = st.slider("কমপক্ষে কয়টি exchange-এ থাকতে হবে?", 1, 5, 2)
    cg_key = st.text_input("CoinGecko Demo API key (ঐচ্ছিক)", type="password")
    st.caption("কোনো exchange-এর API ব্যর্থ হলে অন্য exchange-এর data দিয়ে কাজ চালানোর চেষ্টা হবে।")

@st.cache_resource(ttl=600)
def get_exchange(eid):
    return getattr(ccxt, eid)({"enableRateLimit": True, "timeout": 25000,
                               "options": {"defaultType": "spot"}})

@st.cache_data(ttl=900, show_spinner=False)
def load_markets():
    loaded, errors = {}, {}
    for eid in EXCHANGES:
        try:
            loaded[eid] = get_exchange(eid).load_markets()
        except Exception as exc:
            errors[eid] = f"{type(exc).__name__}: {str(exc)[:150]}"
    return loaded, errors

def spot_symbols(markets):
    result = {}
    for symbol, m in (markets or {}).items():
        if m.get("active") is False or m.get("spot") is not True or m.get("quote") != "USDT":
            continue
        base = m.get("base")
        if base and base not in STABLES:
            result[base] = symbol
    return result

def build_universe(markets_by_exchange):
    combined = {}
    for eid, markets in markets_by_exchange.items():
        for coin, pair in spot_symbols(markets).items():
            combined.setdefault(coin, {})[eid] = pair
    records = []
    for coin, pairs in combined.items():
        item = {"কয়েন": coin, "কয়টি এক্সচেঞ্জ": len(pairs)}
        for eid in EXCHANGES:
            item[EXCHANGE_BN[eid]] = "হ্যাঁ" if eid in pairs else "না"
        records.append(item)
    if not records:
        return pd.DataFrame(columns=["কয়েন", "কয়টি এক্সচেঞ্জ", *EXCHANGE_BN.values()])
    return pd.DataFrame(records).sort_values(["কয়টি এক্সচেঞ্জ", "কয়েন"], ascending=[False, True]).reset_index(drop=True)

def fetch_ticker(eid, pair):
    t = get_exchange(eid).fetch_ticker(pair)
    return {"price": t.get("last") or t.get("close"), "change": t.get("percentage"), "volume": t.get("quoteVolume")}

@st.cache_data(ttl=900, show_spinner=False)
def fetch_history(eid, pair, tf, days):
    ex = get_exchange(eid)
    now = datetime.now(timezone.utc)
    cursor = int((now - timedelta(days=int(days))).timestamp() * 1000)
    end = int(now.timestamp() * 1000)
    step = ex.parse_timeframe(tf) * 1000
    rows = []
    for _ in range(1500):
        if cursor >= end:
            break
        batch = ex.fetch_ohlcv(pair, timeframe=tf, since=cursor, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        next_cursor = int(batch[-1][0]) + step
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(batch) < 1000:
            break
        time.sleep(max(float(getattr(ex, "rateLimit", 1000)) / 1000, 0.05))
    if not rows:
        return pd.DataFrame(columns=["timestamp","open","high","low","close","volume","datetime"])
    df = pd.DataFrame(rows, columns=["timestamp","open","high","low","close","volume"])
    df = df.drop_duplicates("timestamp").sort_values("timestamp")
    df = df[df.timestamp <= end]
    df["datetime"] = pd.to_datetime(df.timestamp, unit="ms", utc=True)
    return df.reset_index(drop=True)

@st.cache_data(ttl=1800, show_spinner=False)
def get_coingecko(symbol, api_key=""):
    headers = {"x-cg-demo-api-key": api_key} if api_key else {}
    try:
        r = requests.get(f"{CG_API}/search", params={"query": symbol}, headers=headers, timeout=15)
        r.raise_for_status()
        exact = [x for x in r.json().get("coins", []) if x.get("symbol", "").upper() == symbol.upper()]
        if not exact:
            return {}
        exact.sort(key=lambda x: (x.get("market_cap_rank") is None, x.get("market_cap_rank") or 10**9))
        coin_id = exact[0]["id"]
        r = requests.get(f"{CG_API}/coins/{coin_id}", params={
            "localization":"false", "tickers":"false", "market_data":"true",
            "community_data":"false", "developer_data":"false", "sparkline":"false"
        }, headers=headers, timeout=15)
        r.raise_for_status()
        d = r.json()
        md = d.get("market_data", {})
        return {"name": d.get("name"), "categories": d.get("categories", []),
                "rank": md.get("market_cap_rank"), "market_cap": md.get("market_cap", {}).get("usd"),
                "description": d.get("description", {}).get("en", "")[:700]}
    except Exception:
        return {}

def classify(coin, cg):
    cats = " ".join(cg.get("categories", [])).lower()
    if coin in L2 or "layer 2" in cats or "layer-2" in cats: return "Layer 2"
    if coin in L1 or "layer 1" in cats or "smart contract platform" in cats: return "Layer 1"
    if coin in STABLES or "stablecoin" in cats: return "Stablecoin"
    return "Other / যাচাই প্রয়োজন"

def score_coin(layer, cg, coverage, hist=None, summary=None):
    points_f, points_market, points_dca = 0, 0, 0
    why = []
    rank, cap = cg.get("rank"), cg.get("market_cap") or 0
    if rank:
        p = 20 if rank <= 20 else 16 if rank <= 50 else 12 if rank <= 100 else 7 if rank <= 250 else 0
        points_f += p
        why.append(f"Market-cap rank: {p}/20")
    else: why.append("Market-cap rank পাওয়া যায়নি: 0/20")
    p = 12 if cap >= 10e9 else 9 if cap >= 1e9 else 5 if cap >= 250e6 else 0
    points_f += p
    why.append(f"Market cap size: {p}/12")
    if layer in ("Layer 1", "Layer 2"):
        points_f += 8
        why.append(f"{layer} শ্রেণিবিন্যাস: 8/8")
    if "meme" in " ".join(cg.get("categories", [])).lower():
        points_f = max(0, points_f - 12)
        why.append("Meme category ঝুঁকি: -12")
    points_f = min(40, points_f)
    points_exchange = coverage / 5 * 20
    why.append(f"৫টি exchange-এর মধ্যে {coverage}টিতে listing: {points_exchange:.0f}/20")

    metrics = {}
    if hist is not None and not hist.empty and len(hist) > 2:
        closes = hist.close.astype(float)
        ret = (closes.iloc[-1] / closes.iloc[0] - 1) * 100
        mdd = ((closes / closes.cummax()) - 1).min() * 100
        returns = closes.pct_change().dropna()
        span_days = max((hist.datetime.iloc[-1] - hist.datetime.iloc[0]).total_seconds()/86400, 1)
        annual_vol = returns.std() * ((len(returns)*365/span_days) ** .5) * 100
        points_market += 8 if mdd > -30 else 5 if mdd > -60 else 0
        points_market += 7 if annual_vol < 80 else 4 if annual_vol < 120 else 0
        points_market += 5 if ret > 0 else 0
        metrics = {"period_return": ret, "drawdown": mdd, "volatility": annual_vol}
        why.append(f"Market health: {points_market}/20 (period return, drawdown, volatility)")
    else:
        why.append("Historical test না হওয়া পর্যন্ত Market health score নেই")
    if summary and summary.get("cycles", 0):
        confidence = min(summary["cycles"] / 10, 1)
        points_dca = round(min(20, summary["pass_rate"] * .2) * confidence, 1)
        why.append(f"DCA PASS rate {summary['pass_rate']:.1f}%: {points_dca}/20; cycle সংখ্যা {summary['cycles']}")
    else:
        why.append("DCA backtest না হওয়া পর্যন্ত DCA score নেই")
    total = round(min(100, points_f + points_exchange + points_market + points_dca), 1)
    rating = "A — তুলনামূলক শক্তিশালী" if total >= 80 else "B — ভালো, তবে ঝুঁকি যাচাই করুন" if total >= 65 else "C — পর্যবেক্ষণ করুন" if total >= 50 else "D — উচ্চ ঝুঁকি"
    return total, rating, why, metrics

def run_backtest(df, drop=.03, tp=.01, scale=1.1, max_steps=15):
    """OHLC approximation: at most one DCA buy per candle; if DCA and TP both possible, DCA is assumed first."""
    if df is None or df.empty or len(df) < 2:
        return pd.DataFrame(), {}
    trades, state = [], None
    data = df.sort_values("timestamp").reset_index(drop=True)
    def start(price, dt):
        return {"start":dt, "start_price":price, "avg":price, "qty":1.0, "next_qty":scale,
                "buys":1, "adds":0, "next_buy":price*(1-drop), "min_price":price}
    def finish(price, dt, result, reason):
        nonlocal state
        trades.append({"শুরু":state["start"], "শেষ":dt, "প্রথম Buy":state["start_price"],
            "শেষ দাম":price, "গড় Buy price":state["avg"], "মোট Buy":state["buys"],
            "অতিরিক্ত DCA":state["adds"], "সর্বনিম্ন দাম":state["min_price"],
            "শেষ Return %":(price/state["avg"]-1)*100, "ফলাফল":result, "কারণ":reason})
        state = None
    for r in data.itertuples(index=False):
        o,h,l,c = float(r.open),float(r.high),float(r.low),float(r.close)
        if state is None: state = start(o, r.datetime)
        state["min_price"] = min(state["min_price"], l)
        dca_hit = l <= state["next_buy"] and state["adds"] < max_steps
        tp_hit = h >= state["avg"]*(1+tp)
        if dca_hit:
            p, add, old = state["next_buy"], state["next_qty"], state["qty"]
            state["qty"] += add
            state["avg"] = (old*state["avg"] + add*p) / state["qty"]
            state["buys"] += 1
            state["adds"] += 1
            state["next_qty"] *= scale
            state["next_buy"] = p*(1-drop)
            continue
        if tp_hit:
            finish(state["avg"]*(1+tp), r.datetime, "PASS", "লক্ষ্য লাভের দাম স্পর্শ করেছে")
    if state is not None:
        last = data.iloc[-1]
        reason = "পরীক্ষার সময় শেষ; লক্ষ্য লাভে ফেরেনি"
        if state["adds"] >= max_steps:
            reason = "সর্বোচ্চ DCA ব্যবহার; সময় শেষেও লক্ষ্য লাভে ফেরেনি"
        finish(float(last.close), last.datetime, "FAIL / UNRECOVERED", reason)
    trades = pd.DataFrame(trades)
    if trades.empty: return trades, {}
    passed = int((trades["ফলাফল"] == "PASS").sum())
    return trades, {"cycles":len(trades), "pass":passed, "fail":int((trades["ফলাফল"] != "PASS").sum()),
                    "pass_rate":passed/len(trades)*100, "avg_buys":float(trades["মোট Buy"].mean())}

st.markdown("### শুরু করার সহজ নিয়ম")
st.info("১) কয়েন বাছুন → ২) পাঁচটি exchange-এ listing ও দাম দেখুন → ৩) DCA নিয়ম ঠিক করুন → ৪) Backtest চালান → ৫) PASS/FAIL এবং score দেখে ঝুঁকি বুঝুন।")

with st.spinner("Exchange-গুলোর বাজার তালিকা আনা হচ্ছে..."):
    markets, errors = load_markets()

if errors:
    with st.expander(f"⚠️ Exchange API সমস্যা ({len(errors)}টি) — এখানে দেখুন"):
        for eid, err in errors.items():
            st.warning(f"{EXCHANGE_BN[eid]}: {err}")
        st.caption("403/451 error hosting location বা exchange policy-এর কারণে হতে পারে। এই ক্ষেত্রে ওই exchange-এর তথ্য অনুপস্থিত থাকতে পারে।")

coins = build_universe(markets)
if coins.empty:
    st.error("কোনো exchange থেকে USDT spot market পাওয়া যায়নি। কিছুক্ষণ পরে আবার চেষ্টা করুন অথবা অন্য hosting ব্যবহার করুন।")
    st.stop()

tab1, tab2, tab3, tab4 = st.tabs(["১. Coin খুঁজুন", "২. Coin বিস্তারিত", "৩. DCA Backtest", "৪. Score ও নিয়মের বাংলা ব্যাখ্যা"])

with tab1:
    st.subheader("কোন কয়েনগুলো আপনার শর্ত পূরণ করে?")
    eligible = coins[coins["কয়টি এক্সচেঞ্জ"] >= min_exchanges].copy()
    st.metric("মোট পাওয়া কয়েন", len(coins))
    st.caption("‘হ্যাঁ’ মানে exchange-এর public market list-এ ওই USDT spot pair পাওয়া গেছে। এটি coin-এর quality বা নিরাপত্তার নিশ্চয়তা নয়।")
    st.dataframe(eligible, use_container_width=True, hide_index=True)
    st.download_button("এই coin list CSV ডাউনলোড", eligible.to_csv(index=False).encode("utf-8-sig"), "coin_listing.csv", "text/csv")

if len(coins[coins["কয়টি এক্সচেঞ্জ"] >= min_exchanges]) == 0:
    st.warning("এই exchange সংখ্যার শর্তে কোনো coin নেই। বাম পাশ থেকে minimum exchange কমান।")
    st.stop()

eligible = coins[coins["কয়টি এক্সচেঞ্জ"] >= min_exchanges]
with tab2:
    coin = st.selectbox("বিশ্লেষণের জন্য কয়েন বাছুন", eligible["কয়েন"].tolist(), key="coin_detail")
    cg = get_coingecko(coin, cg_key)
    layer = classify(coin, cg)
    coinrow = eligible[eligible["কয়েন"] == coin].iloc[0]
    score, rating, why, _ = score_coin(layer, cg, int(coinrow["কয়টি এক্সচেঞ্জ"]))
    a,b,c = st.columns(3)
    a.metric("Coin type", layer)
    b.metric("প্রাথমিক score", f"{score}/100")
    c.metric("প্রাথমিক rating", rating)
    st.markdown("**এই প্রাথমিক score কেন?**")
    for reason in why: st.write("• " + reason)
    if cg:
        cap = cg.get("market_cap")
        st.caption(f"{cg.get('name') or coin} | Market-cap rank: {cg.get('rank') or 'তথ্য নেই'} | Market cap: {('$'+format(cap, ',.0f')) if isinstance(cap,(int,float)) else 'তথ্য নেই'}")
        if cg.get("description"):
            with st.expander("প্রজেক্টের সংক্ষিপ্ত বিবরণ"): st.write(cg["description"])
    else:
        st.warning("CoinGecko তথ্য পাওয়া যায়নি। তাই Layer/market-cap ভিত্তিক মূল্যায়ন অসম্পূর্ণ হতে পারে।")
    ticker_rows = []
    for eid in EXCHANGES:
        pair = spot_symbols(markets.get(eid, {})).get(coin)
        if not pair:
            ticker_rows.append({"Exchange":EXCHANGE_BN[eid],"Pair":"—","Listing":"না","দাম":None,"২৪ ঘণ্টা পরিবর্তন %":None,"২৪ ঘণ্টার volume":None})
        else:
            try:
                t = fetch_ticker(eid, pair)
                ticker_rows.append({"Exchange":EXCHANGE_BN[eid],"Pair":pair,"Listing":"হ্যাঁ","দাম":t["price"],"২৪ ঘণ্টা পরিবর্তন %":t["change"],"২৪ ঘণ্টার volume":t["volume"]})
            except Exception:
                ticker_rows.append({"Exchange":EXCHANGE_BN[eid],"Pair":pair,"Listing":"হ্যাঁ, কিন্তু price API ব্যর্থ","দাম":None,"২৪ ঘণ্টা পরিবর্তন %":None,"২৪ ঘণ্টার volume":None})
    st.markdown("#### পাঁচটি exchange-এ listing ও বর্তমান market price")
    st.dataframe(pd.DataFrame(ticker_rows), use_container_width=True, hide_index=True)
    st.caption("Price API ব্যর্থ হলে ‘Listing হ্যাঁ’ থাকতে পারে কিন্তু দাম ফাঁকা থাকবে।")

with tab3:
    coin = st.selectbox("DCA পরীক্ষা করার কয়েন", eligible["কয়েন"].tolist(), key="coin_backtest")
    row = eligible[eligible["কয়েন"] == coin].iloc[0]
    available = [eid for eid in EXCHANGES if row.get(EXCHANGE_BN[eid]) == "হ্যাঁ" and eid in markets]
    if not available:
        st.warning("এই কয়েনের জন্য কাজ করা exchange-এর historical data পাওয়া যাচ্ছে না।")
    else:
        source = st.selectbox("কোন exchange-এর historical data ব্যবহার করবেন", available, format_func=lambda x: EXCHANGE_BN[x])
        pair = spot_symbols(markets[source])[coin]
        st.markdown("#### আপনার নির্বাচিত strategy")
        st.write(f"প্রথম Buy → সর্বশেষ Buy থেকে দাম {drop_pct*100:.1f}% কমলে পরের Buy → order amount প্রতি ধাপে {scale:.2f} গুণ → weighted-average Buy price-এর {tp_pct*100:.1f}% ওপরে বিক্রির লক্ষ্য → সর্বোচ্চ {max_steps}টি অতিরিক্ত Buy।")
        st.warning("গুরুত্বপূর্ণ: একই candle-এ DCA ও take-profit দুটোই সম্ভব হলে মডেল আগে DCA হয়েছে ধরে। Trading fee, spread ও slippage হিসাব করা হয়নি। Period শেষে খোলা cycle FAIL/UNRECOVERED দেখাবে; ভবিষ্যতেও কখনো recover করবে না—এমন অর্থ নয়।")
        if st.button("▶ Backtest চালান", type="primary"):
            try:
                with st.spinner(f"{days} দিনের historical data আনা হচ্ছে..."):
                    hist = fetch_history(source, pair, timeframe, days)
                if hist.empty or len(hist) < 2:
                    st.error("পর্যাপ্ত historical candle পাওয়া যায়নি। অন্য exchange বা timeframe চেষ্টা করুন।")
                else:
                    trades, summary = run_backtest(hist, drop_pct, tp_pct, scale, max_steps)
                    total, rating, reasons, metrics = score_coin(layer if 'layer' in locals() else classify(coin, get_coingecko(coin, cg_key)),
                                                                  get_coingecko(coin, cg_key), int(row["কয়টি এক্সচেঞ্জ"]), hist, summary)
                    st.session_state["bn_result"] = (trades, summary, total, rating, reasons, metrics, coin, EXCHANGE_BN[source], len(hist))
            except Exception as exc:
                st.error(f"Backtest ব্যর্থ: {type(exc).__name__}: {str(exc)[:250]}")
        if "bn_result" in st.session_state:
            trades, summary, total, rating, reasons, metrics, tested_coin, tested_source, n_candles = st.session_state["bn_result"]
            st.success(f"{tested_coin} — {tested_source}: {n_candles:,}টি candle পরীক্ষা করা হয়েছে।")
            a,b,c,d,e = st.columns(5)
            a.metric("মোট cycle", summary["cycles"])
            b.metric("PASS", summary["pass"])
            c.metric("FAIL / Unrecovered", summary["fail"])
            d.metric("PASS rate", f'{summary["pass_rate"]:.1f}%')
            e.metric("Updated score", f"{total}/100")
            st.markdown(f"### Rating: {rating}")
            st.markdown("**Updated score-এর কারণ**")
            for reason in reasons: st.write("• " + reason)
            if metrics:
                a,b,c = st.columns(3)
                a.metric("পরীক্ষার সময়ের return", f'{metrics["period_return"]:.1f}%')
                b.metric("সর্বোচ্চ পতন (drawdown)", f'{metrics["drawdown"]:.1f}%')
                c.metric("বার্ষিকীকৃত volatility", f'{metrics["volatility"]:.1f}%')
            st.markdown("#### প্রতিটি DCA cycle-এর ফলাফল")
            view = trades.copy()
            for col in ("শুরু","শেষ"):
                view[col] = pd.to_datetime(view[col], utc=True).dt.strftime("%Y-%m-%d %H:%M UTC")
            st.dataframe(view, use_container_width=True, hide_index=True)
            st.download_button("DCA result CSV ডাউনলোড", trades.to_csv(index=False).encode("utf-8-sig"), f"{tested_coin}_DCA_result.csv", "text/csv")

with tab4:
    st.subheader("এই dashboard আপনার কী কাজে লাগবে?")
    st.markdown("""
**১. Coin shortlist:** পাঁচটি exchange-এর মধ্যে কোন coin কোথায় listed আছে তা এক জায়গায় দেখতে পারবেন।  
**২. ঝুঁকি তুলনা:** market-cap rank, layer classification, drawdown ও volatility দিয়ে প্রাথমিকভাবে coin তুলনা করতে পারবেন।  
**৩. আপনার DCA নিয়ম যাচাই:** ৩% drop, ১% target, 1.1× order scale ও ১৫টি অতিরিক্ত Buy—অতীতের candle-এ কতগুলো cycle target-এ পৌঁছেছে তা দেখতে পারবেন।  
**৪. বড় ঝুঁকি আগে চেনা:** যেসব cycle period শেষেও target-এ পৌঁছায়নি, সেগুলো আলাদা করে দেখতে পারবেন।  
**৫. নিজের গবেষণা সংরক্ষণ:** ফলাফল CSV হিসেবে ডাউনলোড করে Excel-এ বিশ্লেষণ করতে পারবেন।
""")
    st.subheader("Score কীভাবে হিসাব হয়? (সর্বোচ্চ ১০০)")
    st.markdown("""
| অংশ | সর্বোচ্চ নম্বর | সহজ অর্থ |
|---|---:|---|
| Fundamentals | ৪০ | Market-cap rank/size, Layer 1/2 এবং meme-category penalty |
| Exchange listing | ২০ | ৫টি exchange-এর কয়টিতে USDT spot pair আছে |
| Market health | ২০ | পরীক্ষার সময়ের return, সর্বোচ্চ drawdown ও volatility |
| DCA history | ২০ | অতীতের DCA cycle-এর PASS rate; কম cycle হলে score কমানো হয় |
""")
    st.subheader("PASS / FAIL-এর মানে")
    st.markdown("""
- **PASS:** মডেল অনুযায়ী weighted-average entry থেকে নির্ধারিত target price ছুঁয়েছে।
- **FAIL / UNRECOVERED:** নির্বাচিত historical period শেষ হয়েছে, কিন্তু খোলা cycle target-এ ফেরেনি।
- **এটি যা বলে না:** ভবিষ্যতে কয়েনটি অবশ্যই লাভ দেবে বা FAIL cycle কখনো recover করবে না—এমন নিশ্চয়তা দেয় না।
""")
    st.subheader("সীমাবদ্ধতা মনে রাখুন")
    st.markdown("""
- Score একটি rule-based estimate; এটি project audit বা নিশ্চিত GOOD/BAD certification নয়।
- Layer classification-এর কিছু অংশ symbol/category-এর rule থেকে আসে; ভুল বা ambiguous symbol হলে হাতে যাচাই করা দরকার।
- Backtest candle-এর ভিতরের সঠিক price path জানে না।
- Trading fee, spread, slippage, token unlock, liquidity depth, delisting ও execution failure পুরোপুরি অন্তর্ভুক্ত নয়।
- API error হলে সংশ্লিষ্ট exchange-এর তথ্য অনুপস্থিত থাকতে পারে।
""")
