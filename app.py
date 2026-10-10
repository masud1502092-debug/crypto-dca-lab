import time
from datetime import datetime, timedelta, timezone

import ccxt
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Crypto Quality + DCA Lab", layout="wide")

EXCHANGE_IDS = ["binance", "kucoin", "bybit", "bitget", "htx"]
EXCHANGE_NAMES = dict(zip(EXCHANGE_IDS, ["Binance", "KuCoin", "Bybit", "Bitget", "HTX"]))
STABLES = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "USDD"}
KNOWN_L1 = {"BTC","ETH","SOL","ADA","AVAX","DOT","ATOM","NEAR","SUI","APT","SEI","TON","TRX","XRP","HBAR","ALGO","ICP","FIL","EGLD","KAS","TIA","INJ","XLM","XTZ","EOS","ETC"}
KNOWN_L2 = {"ARB","OP","MATIC","POL","IMX","STRK","ZK","ZKSYNC","MNT","METIS","LRC","BOBA"}

@st.cache_resource(ttl=600)
def get_exchange(exchange_id):
    return getattr(ccxt, exchange_id)({"enableRateLimit": True, "timeout": 20000})

@st.cache_data(ttl=900, show_spinner=False)
def load_all_markets():
    result, errors = {}, {}
    for eid in EXCHANGE_IDS:
        try:
            result[eid] = get_exchange(eid).load_markets()
        except Exception as e:
            errors[eid] = str(e)
    return result, errors

def usdt_spot_symbols(markets):
    out = {}
    for symbol, m in markets.items():
        if not m.get("active", True) or m.get("spot") is not True or m.get("quote") != "USDT":
            continue
        base = m.get("base")
        if base and base not in STABLES:
            out[base] = symbol
    return out

def get_exchange_universe(markets_by_exchange):
    rows = {}
    for eid, markets in markets_by_exchange.items():
        for base, symbol in usdt_spot_symbols(markets).items():
            rows.setdefault(base, {})[eid] = symbol
    return pd.DataFrame([
        {"Coin": b, "Listed_Exchanges": len(mp), **{EXCHANGE_NAMES[e]: e in mp for e in EXCHANGE_IDS}}
        for b, mp in rows.items()
    ]).sort_values(["Listed_Exchanges", "Coin"], ascending=[False, True])

def fetch_ticker(eid, symbol):
    t = get_exchange(eid).fetch_ticker(symbol)
    return {"price": float(t.get("last") or t.get("close") or 0), "change_24h": t.get("percentage"), "volume_24h": t.get("quoteVolume")}

@st.cache_data(ttl=900, show_spinner=False)
def fetch_ohlcv(eid, symbol, timeframe="1h", days=365):
    ex = get_exchange(eid)
    now = datetime.now(timezone.utc)
    since = int((now - timedelta(days=days)).timestamp() * 1000)
    end = int(now.timestamp() * 1000)
    step = ex.parse_timeframe(timeframe) * 1000
    rows, cursor = [], since
    while cursor < end:
        batch = ex.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        nxt = batch[-1][0] + step
        if nxt <= cursor:
            break
        cursor = nxt
        if len(batch) < 1000:
            break
        time.sleep(max(ex.rateLimit / 1000, 0.05))
    df = pd.DataFrame(rows, columns=["timestamp","open","high","low","close","volume"])
    if df.empty:
        return df
    df = df.drop_duplicates("timestamp").sort_values("timestamp")
    df["datetime"] = pd.to_datetime(df.timestamp, unit="ms", utc=True)
    return df.reset_index(drop=True)

def backtest_dca(df, drop_pct=.03, tp_pct=.01, scale=1.10, max_steps=15, initial_qty=1.0):
    if df.empty:
        return pd.DataFrame(), {}
    qty = avg = 0.0; order_qty = initial_qty; buys = 0; next_buy = None; cycle = None; cycles = []
    def start(p, dt):
        nonlocal qty, avg, order_qty, buys, next_buy, cycle
        qty, avg, buys = initial_qty, p, 1
        order_qty = initial_qty * scale; next_buy = p * (1-drop_pct)
        cycle = {"start":dt,"start_price":p,"buys":1,"max_steps_reached":False,"min_price":p}
    def close(p, dt, result):
        nonlocal qty, avg, order_qty, buys, next_buy, cycle
        cycle.update({"end":dt,"exit_price":p,"result":result,"buys":buys,"avg_entry":avg,"return_pct":(p/avg-1)*100})
        cycles.append(cycle.copy()); qty=avg=0; order_qty=initial_qty; buys=0; next_buy=None; cycle=None
    for r in df.itertuples(index=False):
        dt,o,h,l = r.datetime,float(r.open),float(r.high),float(r.low)
        if cycle is None: start(o,dt)
        cycle["min_price"] = min(cycle["min_price"], l)
        while cycle is not None and buys <= max_steps:
            tp = avg*(1+tp_pct)
            if l <= next_buy:
                p=next_buy; old_qty=qty; add_qty=order_qty
                qty += add_qty; avg=((old_qty*avg)+(add_qty*p))/qty; buys += 1
                order_qty *= scale; next_buy=p*(1-drop_pct)
                if buys > max_steps: cycle["max_steps_reached"]=True; break
                continue
            if h >= tp:
                close(tp,dt,"PASS"); break
            break
    if cycle is not None:
        cycle["max_steps_reached"] = buys > max_steps
        close(float(df.iloc[-1].close), df.iloc[-1].datetime, "FAIL_UNRECOVERED")
    trades=pd.DataFrame(cycles)
    if trades.empty: return trades, {}
    s={"cycles":len(trades),"pass":int((trades.result=="PASS").sum()),"fail":int((trades.result=="FAIL_UNRECOVERED").sum()),"pass_rate":float((trades.result=="PASS").mean()*100),"max_buys":int(trades.buys.max()),"avg_buys":float(trades.buys.mean()),"worst_end_return":float(trades.return_pct.min())}
    return trades,s

def coingecko_info(symbol, api_key=""):
    headers={"x-cg-demo-api-key":api_key} if api_key else {}
    try:
        r=requests.get("https://api.coingecko.com/api/v3/search",params={"query":symbol},headers=headers,timeout=15); r.raise_for_status()
        coins=r.json().get("coins",[]); exact=[x for x in coins if x.get("symbol","").upper()==symbol.upper()]
        if not exact: return {}
        cid=exact[0]["id"]
        r=requests.get(f"https://api.coingecko.com/api/v3/coins/{cid}",params={"localization":"false","tickers":"false","market_data":"true","community_data":"false","developer_data":"false"},headers=headers,timeout=15); r.raise_for_status()
        d=r.json(); md=d.get("market_data",{})
        return {"id":cid,"name":d.get("name"),"description":d.get("description",{}).get("en","")[:600],"categories":d.get("categories",[]),"market_cap":md.get("market_cap",{}).get("usd"),"market_cap_rank":md.get("market_cap_rank"),"ath":md.get("ath",{}).get("usd"),"current":md.get("current_price",{}).get("usd")}
    except Exception:
        return {}

def classify(symbol,cg):
    cats=" ".join(cg.get("categories",[])).lower()
    if symbol in KNOWN_L2 or "layer 2" in cats or "layer-2" in cats: layer="Layer 2"
    elif symbol in KNOWN_L1 or "layer 1" in cats or "smart contract platform" in cats: layer="Layer 1"
    elif symbol in STABLES or "stablecoin" in cats: layer="Stablecoin"
    else: layer="Other"
    return layer

def quality_score(symbol, layer, cg, listed_count, market_df=None, dca_summary=None):
    # 0-100: Fundamentals 40 + Liquidity/coverage 20 + Market health 20 + DCA history 20.
    fund=0; reasons=[]; rank=cg.get("market_cap_rank"); mcap=cg.get("market_cap") or 0
    if rank and rank<=20: fund+=20; reasons.append("Top-20 market cap")
    elif rank and rank<=50: fund+=16; reasons.append("Top-50 market cap")
    elif rank and rank<=100: fund+=12; reasons.append("Top-100 market cap")
    elif rank and rank<=250: fund+=7; reasons.append("Top-250 market cap")
    if mcap>=10e9: fund+=12; reasons.append("Large market cap")
    elif mcap>=1e9: fund+=9; reasons.append(">$1B market cap")
    elif mcap>=250e6: fund+=5; reasons.append(">$250M market cap")
    if layer in ("Layer 1","Layer 2"): fund+=8; reasons.append(layer)
    if "meme" in " ".join(cg.get("categories",[])).lower(): fund=max(0,fund-12); reasons.append("Meme/speculative category risk")
    coverage=listed_count/5*20
    reasons.append(f"Listed on {listed_count}/5 exchanges")
    market=0
    if market_df is not None and not market_df.empty:
        closes=market_df.close.astype(float); ret=(closes.iloc[-1]/closes.iloc[0]-1)*100
        peak=closes.cummax(); mdd=((closes/peak)-1).min()*100
        vol=closes.pct_change().std()*100*(365**0.5)
        if mdd>-30: market+=8; reasons.append("Moderate max drawdown")
        elif mdd>-60: market+=5; reasons.append("High but recoverable drawdown")
        if vol<80: market+=7; reasons.append("Lower annualized volatility")
        elif vol<120: market+=4; reasons.append("Moderate volatility")
        if ret>0: market+=5; reasons.append("Positive 1Y return")
        market_metrics={"1Y return %":ret,"Max drawdown %":mdd,"Annualized volatility %":vol}
    else: market_metrics={}
    dca=0
    if dca_summary:
        pr=dca_summary.get("pass_rate",0); fail=dca_summary.get("fail",0); cycles=dca_summary.get("cycles",0)
        if cycles>=10:
            dca=round(min(20,max(0,pr*0.20)),1)
            if fail==0: reasons.append("No unrecovered cycles in test")
            elif pr>=80: reasons.append("Strong DCA historical recovery")
            elif pr<60: reasons.append("Frequent unrecovered DCA cycles")
        else: dca=round(min(20,max(0,pr*0.15)),1)
    total=round(min(100,fund+coverage+market+dca),1)
    verdict="A — STRONG" if total>=80 else "B — GOOD" if total>=65 else "C — WATCH" if total>=50 else "D — HIGH RISK"
    return total,verdict,"; ".join(reasons),market_metrics

st.title("🪙 Crypto Quality + DCA Lab")
st.caption("Research/backtesting tool only. Scores are transparent heuristics, not investment advice.")
with st.sidebar:
    st.header("DCA Settings")
    drop_pct=st.number_input("Buy trigger: drop from latest buy (%)",.1,50.,3.,.1)/100
    tp_pct=st.number_input("Take profit above weighted average (%)",.1,50.,1.,.1)/100
    scale=st.number_input("DCA amount multiplier",1.,5.,1.10,.05)
    max_steps=st.number_input("Maximum DCA additions",1,50,15,1)
    timeframe=st.selectbox("Historical candle",["1h","4h","1d"],0)
    days=st.number_input("Historical period (days)",30,730,365,30)
    min_exchanges=st.slider("Minimum exchanges listed",1,5,5)
    cg_key=st.text_input("CoinGecko Demo API key (optional)",type="password")

markets,errors=load_all_markets()
if errors: st.warning("Some exchange APIs failed: "+" | ".join(f"{EXCHANGE_NAMES[k]}: {v[:80]}" for k,v in errors.items()))
universe=get_exchange_universe(markets)
if universe.empty: st.error("No USDT spot markets loaded."); st.stop()
filtered=universe[universe.Listed_Exchanges>=min_exchanges].copy()
if filtered.empty: st.warning("No coin matches the exchange filter."); st.stop()

c1,c2,c3=st.columns(3); c1.metric("Coins found",len(universe)); c2.metric("Listed on all 5",int((universe.Listed_Exchanges==5).sum())); c3.metric("Working exchanges",len(markets))
selected=st.selectbox("Select coin",filtered.Coin.tolist())
row=filtered[filtered.Coin==selected].iloc[0]

prices=[]
for eid in EXCHANGE_IDS:
    sym=usdt_spot_symbols(markets.get(eid,{})).get(selected)
    if sym:
        try:
            t=fetch_ticker(eid,sym); prices.append({"Exchange":EXCHANGE_NAMES[eid],"Pair":sym,"Listed":"YES","Current Price":t["price"],"24h %":t["change_24h"],"24h Quote Volume":t["volume_24h"]})
        except Exception: prices.append({"Exchange":EXCHANGE_NAMES[eid],"Pair":sym,"Listed":"YES","Current Price":None,"24h %":None,"24h Quote Volume":None})
    else: prices.append({"Exchange":EXCHANGE_NAMES[eid],"Pair":"-","Listed":"NO","Current Price":None,"24h %":None,"24h Quote Volume":None})
price_df=pd.DataFrame(prices)
cg=coingecko_info(selected,cg_key); layer=classify(selected,cg)
base_score,base_verdict,base_reason,_=quality_score(selected,layer,cg,int(row.Listed_Exchanges))

st.subheader(f"{selected} — Coin Profile")
a,b,c,d=st.columns(4); a.metric("Layer",layer); b.metric("Base Score",f"{base_score}/100"); c.metric("Base Rating",base_verdict); d.metric("Exchange Coverage",f"{int(row.Listed_Exchanges)}/5")
st.write("**Why this score?**",base_reason)
if cg: st.caption(f"{cg.get('name','')} | Market-cap rank: {cg.get('market_cap_rank','N/A')} | Market cap: ${cg.get('market_cap',0):,.0f}")
st.dataframe(price_df,use_container_width=True,hide_index=True)

st.subheader("Historical DCA Test")
source_options=[EXCHANGE_NAMES[e] for e in EXCHANGE_IDS if bool(row[EXCHANGE_NAMES[e]])]
source=st.selectbox("Historical data source",source_options)
eid=next(e for e in EXCHANGE_IDS if EXCHANGE_NAMES[e]==source); symbol=usdt_spot_symbols(markets[eid])[selected]
st.write(f"**Strategy:** first buy → every {drop_pct*100:.2f}% fall from latest buy → next order {scale:.2f}× → TP at {tp_pct*100:.2f}% above weighted average → max {max_steps} DCA additions. No recovery by the end = FAIL_UNRECOVERED.")
if st.button("▶ Run / Refresh Backtest",type="primary"):
    with st.spinner(f"Downloading {days} days of {symbol} from {source}..."):
        hist=fetch_ohlcv(eid,symbol,timeframe,days)
    if hist.empty: st.error("No historical data returned.")
    else:
        trades,s=backtest_dca(hist,drop_pct,tp_pct,scale,max_steps)
        total,verdict,reasons,mm=quality_score(selected,layer,cg,int(row.Listed_Exchanges),hist,s)
        st.session_state["last_result"]=(trades,s,total,verdict,reasons,mm,hist)

if "last_result" in st.session_state:
    trades,s,total,verdict,reasons,mm,hist=st.session_state["last_result"]
    st.success("Backtest completed")
    a,b,c,d,e=st.columns(5); a.metric("Cycles",s.get("cycles",0)); b.metric("PASS",s.get("pass",0)); c.metric("FAIL",s.get("fail",0)); d.metric("Pass rate",f"{s.get('pass_rate',0):.1f}%"); e.metric("UPDATED SCORE",f"{total}/100")
    st.markdown(f"### Rating: **{verdict}**")
    st.write("**Updated score reasoning:**",reasons)
    if mm:
        m1,m2,m3=st.columns(3); m1.metric("1Y Return",f"{mm.get('1Y return %',0):.1f}%"); m2.metric("Max Drawdown",f"{mm.get('Max drawdown %',0):.1f}%"); m3.metric("Annualized Volatility",f"{mm.get('Annualized volatility %',0):.1f}%")
    st.info("Score composition: Fundamentals 40 + 5-exchange coverage 20 + market health 20 + DCA history 20. DCA component is stronger when there are enough cycles; insufficient history is intentionally penalized by lower confidence.")
    if not trades.empty:
        view=trades.copy(); view["start"]=pd.to_datetime(view.start,utc=True).dt.strftime("%Y-%m-%d %H:%M"); view["end"]=pd.to_datetime(view.end,utc=True).dt.strftime("%Y-%m-%d %H:%M")
        st.dataframe(view,use_container_width=True,hide_index=True)
        st.download_button("Download DCA CSV",trades.to_csv(index=False).encode(),f"{selected}_DCA_backtest.csv","text/csv")

st.divider()
st.subheader("How to interpret the score")
st.markdown("""**A 80–100:** strong profile + liquidity/coverage + healthier market behavior + good DCA history.  
**B 65–79:** generally good, but has meaningful weaknesses.  
**C 50–64:** watchlist only; investigate further.  
**D <50:** high-risk/speculative profile.

The score is not a prediction of future price or profit. Fees, spread, slippage, delisting and execution latency are not included unless added to the model.""")
