import time
from datetime import datetime, timedelta, timezone
import ccxt, pandas as pd, requests, streamlit as st

st.set_page_config(page_title="Crypto Coin ও DCA Lab", page_icon="🪙", layout="wide")
st.title("🪙 Crypto Coin Scanner ও DCA Lab")
st.caption("বাংলা dashboard | Coin ranking, exchange listing, price ও DCA historical test")
EX = ["binance","kucoin","bybit","bitget","htx"]
EN = {"binance":"Binance","kucoin":"KuCoin","bybit":"Bybit","bitget":"Bitget","htx":"HTX"}
STABLE={"USDT","USDC","DAI","FDUSD","TUSD","USDE","USDD","USDP","PYUSD"}
L1={"BTC","ETH","SOL","ADA","AVAX","DOT","ATOM","NEAR","SUI","APT","SEI","TON","TRX","XRP","HBAR","ALGO","ICP","FIL","EGLD","KAS","TIA","INJ","XLM","XTZ","EOS","ETC"}
L2={"ARB","OP","MATIC","POL","IMX","STRK","ZK","ZKSYNC","MNT","METIS","LRC","BOBA"}
CG="https://api.coingecko.com/api/v3"

with st.sidebar:
    st.header("⚙️ DCA সেটিংস")
    drop=st.number_input("দাম কত % কমলে Buy? (%)",.1,50.,3.,.1)/100
    tp=st.number_input("গড় Buy price-এর ওপরে লক্ষ্য লাভ (%)",.1,50.,1.,.1)/100
    scale=st.number_input("প্রতি ধাপে Buy amount multiplier",1.,5.,1.10,.05)
    steps=int(st.number_input("প্রথম Buy-এর পর সর্বোচ্চ অতিরিক্ত Buy",1,50,15,1))
    tf=st.selectbox("Historical candle",["1h","4h","1d"],index=1)
    days=int(st.number_input("কত দিনের data?",30,730,365,30))
    min_ex=st.slider("কমপক্ষে confirmed listing",0,5,2)
    cgkey=st.text_input("CoinGecko Demo API key (ঐচ্ছিক)",type="password")

@st.cache_resource(ttl=600)
def exobj(e):
    opts={"enableRateLimit":True,"timeout":20000,"options":{"defaultType":"spot"}}
    if e=="binance":
        opts["urls"]={"api":{"public":"https://api.binance.vision/api/v3","private":"https://api.binance.com/api/v3"}}
    return getattr(ccxt,e)(opts)

@st.cache_data(ttl=900,show_spinner=False)
def markets_load():
    good,err={},{}
    for e in EX:
        try: good[e]=exobj(e).load_markets()
        except Exception as x: err[e]=f"{type(x).__name__}: {str(x)[:160]}"
    return good,err

def pairs(mk):
    d={}
    for s,m in (mk or {}).items():
        if m.get("active") is False or m.get("spot") is not True or m.get("quote")!="USDT": continue
        b=m.get("base")
        if b and b not in STABLE: d[b]=s
    return d

@st.cache_data(ttl=1800,show_spinner=False)
def cg_top(key=""):
    headers={"x-cg-demo-api-key":key} if key else {}
    rows=[]
    try:
        for page in range(1,6):
            r=requests.get(CG+"/coins/markets",params={"vs_currency":"usd","order":"market_cap_desc","per_page":250,"page":page,"sparkline":"false"},headers=headers,timeout=20)
            r.raise_for_status(); data=r.json()
            if not data: break
            rows+=data; time.sleep(.1)
    except Exception as e: return pd.DataFrame(),str(e)[:180]
    if not rows: return pd.DataFrame(),"No market data"
    d=pd.DataFrame(rows)
    d["symbol"]=d.symbol.astype(str).str.upper()
    return d.drop_duplicates("symbol",keep="first"),None

@st.cache_data(ttl=1800,show_spinner=False)
def cg_detail(cid,key=""):
    try:
        r=requests.get(f"{CG}/coins/{cid}",params={"localization":"false","tickers":"false","market_data":"true","community_data":"false","developer_data":"false"},headers={"x-cg-demo-api-key":key} if key else {},timeout=15)
        r.raise_for_status(); d=r.json(); md=d.get("market_data",{})
        return {"categories":d.get("categories",[]),"description":d.get("description",{}).get("en","")[:500]}
    except Exception: return {}

@st.cache_data(ttl=1800,show_spinner=False)
def cg_exchange_listings(cid,key=""):
    """Fetch CoinGecko tickers and identify USDT spot markets on target exchanges.
    Returns per-exchange status, matching pairs, source, and completeness/error info.
    """
    headers={"x-cg-demo-api-key":key} if key else {}
    aliases={
        "binance":{"binance"},
        "kucoin":{"kucoin"},
        "bybit":{"bybit"},
        "bitget":{"bitget"},
        "htx":{"htx","huobi","huobi global"},
    }
    found={e:[] for e in EX}
    pages_checked=0
    try:
        # CoinGecko returns up to 100 tickers per page. Stop when a short page is returned.
        for page in range(1,11):
            r=requests.get(f"{CG}/coins/{cid}/tickers",params={"page":page,"order":"trust_score_desc"},headers=headers,timeout=20)
            r.raise_for_status()
            payload=r.json()
            ticks=payload.get("tickers",[]) if isinstance(payload,dict) else []
            pages_checked=page
            for t in ticks:
                market=(t.get("market") or {})
                market_name=str(market.get("name") or "").strip().lower()
                market_id=str(market.get("identifier") or "").strip().lower()
                base=str(t.get("base") or "").upper()
                target=str(t.get("target") or "").upper().replace(" ","")
                # Only count quoted USDT markets; ignore derivatives where type is explicitly non-spot.
                if target!="USDT":
                    continue
                if t.get("trade_url") is None and not market_name and not market_id:
                    continue
                for e in EX:
                    if market_name in aliases[e] or market_id in aliases[e] or any(a in market_name for a in aliases[e]):
                        pair=f"{base}/{target}"
                        if pair not in found[e]: found[e].append(pair)
            if len(ticks)<100:
                break
        # If all ten pages were full, the feed may be truncated; don't claim a definitive NO.
        complete=pages_checked<10
        result={}
        for e in EX:
            result[e]={"status":"YES" if found[e] else ("NO" if complete else "UNKNOWN"),
                       "pairs":", ".join(found[e]) if found[e] else "—",
                       "source":"CoinGecko tickers"}
        return {"results":result,"complete":complete,"pages":pages_checked,"error":None}
    except Exception as ex:
        return {"results":{},"complete":False,"pages":pages_checked,
                "error":f"{type(ex).__name__}: {str(ex)[:180]}"}

def layer(coin,cats=None):
    c=" ".join(cats or []).lower()
    if coin in L2 or "layer 2" in c or "layer-2" in c:return "Layer 2"
    if coin in L1 or "layer 1" in c or "smart contract platform" in c:return "Layer 1"
    if coin in STABLE or "stablecoin" in c:return "Stablecoin"
    return "Other / যাচাই প্রয়োজন"

def make_table(mks,cgdf):
    maps={e:pairs(mks.get(e,{})) for e in EX}
    cgmap={r["symbol"]:r for r in cgdf.to_dict("records")} if not cgdf.empty else {}
    allcoins=set(cgmap)
    for x in maps.values(): allcoins.update(x)
    out=[]
    for coin in allcoins:
        c=cgmap.get(coin,{})
        row={"Rank":c.get("market_cap_rank"),"Coin":coin,"Name":c.get("name",coin),
             "Current price (USD)":c.get("current_price"),"Market cap (USD)":c.get("market_cap"),
             "24h volume (USD)":c.get("total_volume"),"24h change (%)":c.get("price_change_percentage_24h"),
             "Layer":layer(coin,[]),"Confirmed listings":sum(coin in maps[e] for e in EX),
             "_cg_id":c.get("id")}
        for e in EX: row[EN[e]]=("YES" if coin in maps[e] else "NO") if e in mks else "UNKNOWN"
        out.append(row)
    d=pd.DataFrame(out)
    if not d.empty:
        d["_sort"]=pd.to_numeric(d.Rank,errors="coerce").fillna(10**9)
        d=d.sort_values(["_sort","Coin"]).drop(columns="_sort").reset_index(drop=True)
    return d

def ticker(e,s):
    t=exobj(e).fetch_ticker(s)
    return {"Price":t.get("last") or t.get("close"),"24h change %":t.get("percentage"),"24h volume":t.get("quoteVolume")}

@st.cache_data(ttl=900,show_spinner=False)
def history(e,s,tf,days):
    x=exobj(e); now=datetime.now(timezone.utc); cur=int((now-timedelta(days=days)).timestamp()*1000); end=int(now.timestamp()*1000); step=x.parse_timeframe(tf)*1000; rows=[]
    for _ in range(1500):
        if cur>=end: break
        batch=x.fetch_ohlcv(s,timeframe=tf,since=cur,limit=1000)
        if not batch: break
        rows+=batch; nxt=int(batch[-1][0])+step
        if nxt<=cur: break
        cur=nxt
        if len(batch)<1000: break
        time.sleep(max(getattr(x,"rateLimit",1000)/1000,.05))
    if not rows:return pd.DataFrame()
    d=pd.DataFrame(rows,columns=["timestamp","open","high","low","close","volume"]).drop_duplicates("timestamp").sort_values("timestamp")
    d=d[d.timestamp<=end]; d["datetime"]=pd.to_datetime(d.timestamp,unit="ms",utc=True)
    return d.reset_index(drop=True)

def backtest(d,drop,tp,scale,steps):
    if d is None or d.empty or len(d)<2:return pd.DataFrame(),{}
    trades=[]; state=None
    def start(p,dt):return {"start":dt,"first":p,"avg":p,"qty":1.,"nextqty":scale,"buys":1,"adds":0,"next":p*(1-drop),"min":p}
    def finish(p,dt,res,why):
        nonlocal state
        trades.append({"শুরু সময়":state["start"],"শেষ সময়":dt,"প্রথম Buy দাম":state["first"],"Exit/শেষ দাম":p,"Weighted average entry":state["avg"],"মোট Buy":state["buys"],"অতিরিক্ত DCA":state["adds"],"সর্বনিম্ন দাম":state["min"],"শেষ return (%)":(p/state["avg"]-1)*100,"ফলাফল":res,"ব্যাখ্যা":why});state=None
    for r in d.itertuples(index=False):
        o,h,l,c=map(float,(r.open,r.high,r.low,r.close))
        if state is None:state=start(o,r.datetime)
        state["min"]=min(state["min"],l)
        if l<=state["next"] and state["adds"]<steps:
            p=state["next"]; add=state["nextqty"]; old=state["qty"]
            state["qty"]+=add;state["avg"]=(old*state["avg"]+add*p)/state["qty"];state["buys"]+=1;state["adds"]+=1;state["nextqty"]*=scale;state["next"]=p*(1-drop);continue
        if h>=state["avg"]*(1+tp):finish(state["avg"]*(1+tp),r.datetime,"PASS","লক্ষ্য দাম hit")
    if state is not None:
        last=d.iloc[-1];why="পরীক্ষার সময় শেষ, লক্ষ্য দামে ফেরেনি"
        if state["adds"]>=steps:why="সর্বোচ্চ DCA ব্যবহার; period শেষে target hit হয়নি"
        finish(float(last.close),last.datetime,"FAIL / UNRECOVERED",why)
    t=pd.DataFrame(trades);passed=int((t["ফলাফল"]=="PASS").sum())
    return t,{"cycles":len(t),"pass":passed,"fail":int((t["ফলাফল"]!="PASS").sum()),"pass_rate":passed/len(t)*100}

def score(coin,cg,cov,hist=None,s=None,cats=None):
    why=[]; f=0; m=0; dc=0; metrics={}
    rank=cg.get("market_cap_rank");cap=cg.get("market_cap") or 0
    p=20 if rank and rank<=20 else 16 if rank and rank<=50 else 12 if rank and rank<=100 else 7 if rank and rank<=250 else 0
    f+=p;why.append(f"Market-cap rank: {p}/20")
    p=12 if cap>=10e9 else 9 if cap>=1e9 else 5 if cap>=250e6 else 0
    f+=p;why.append(f"Market cap: {p}/12")
    lay=layer(coin,cats)
    if lay in ("Layer 1","Layer 2"):f+=8
    if "meme" in " ".join(cats or []).lower():f=max(0,f-12);why.append("Meme-category penalty -12")
    covpts=cov/5*20
    if hist is not None and len(hist)>2:
        c=hist.close.astype(float);ret=(c.iloc[-1]/c.iloc[0]-1)*100;dd=((c/c.cummax())-1).min()*100;rs=c.pct_change().dropna();span=max((hist.datetime.iloc[-1]-hist.datetime.iloc[0]).total_seconds()/86400,1);vol=rs.std()*((len(rs)*365/span)**.5)*100
        m+=(8 if dd>-30 else 5 if dd>-60 else 0)+(7 if vol<80 else 4 if vol<120 else 0)+(5 if ret>0 else 0)
        metrics={"Period return %":ret,"Max drawdown %":dd,"Annualized volatility %":vol}
    if s and s.get("cycles"):dc=round(min(20,s["pass_rate"]*.2)*min(s["cycles"]/10,1),1)
    total=round(min(100,f+covpts+m+dc),1)
    rating="A — তুলনামূলক শক্তিশালী" if total>=80 else "B — ভালো, ঝুঁকি যাচাই করুন" if total>=65 else "C — পর্যবেক্ষণ করুন" if total>=50 else "D — উচ্চ ঝুঁকি"
    why += [f"Exchange listing: {cov}/5 = {covpts:.0f}/20",f"Market health: {m}/20",f"DCA history: {dc}/20"]
    return total,rating,why,metrics

with st.spinner("Exchange এবং market-cap ranking data আনা হচ্ছে..."):
    mks,errors=markets_load()
    cgdf,cgerr=cg_top(cgkey)
if errors:
    with st.expander("⚠️ Exchange API status"):
        for e,msg in errors.items():st.warning(f"{EN[e]}: {msg}")
        st.info("Binance public API-তে api.binance.vision fallback চেষ্টা হয়। Bybit 403 বা Binance 451 যদি hosting region/network-এ block হয়, code তা নিশ্চিতভাবে bypass করতে পারে না। ওই exchange-এর listing UNKNOWN দেখানো হবে, ভুল করে NO নয়।")
if cgerr:st.warning("CoinGecko ranking data পাওয়া যায়নি: "+cgerr)
coins=make_table(mks,cgdf)
if coins.empty:st.error("Coin list পাওয়া যায়নি। API/network পরে আবার চেষ্টা করুন।");st.stop()

st.info("কাজের ধাপ: Tab 1-এ rank অনুযায়ী shortlist → Tab 2-এ সব তথ্য table-এ তুলনা → Tab 3-এ DCA backtest।")
t1,t2,t3,t4=st.tabs(["১. Coin ranking","২. Coin তথ্য table","৩. DCA ফলাফল table","৪. বাংলা ব্যাখ্যা"])

with t1:
    st.subheader("Market-cap rank অনুযায়ী কয়েন")
    maxrank=st.slider("সর্বোচ্চ market-cap rank",50,1250,500,50)
    covmin=st.slider("কমপক্ষে confirmed exchange listing",0,5,min_ex,key="rankcov")
    q=coins.copy();q["_r"]=pd.to_numeric(q.Rank,errors="coerce")
    if not cgdf.empty:q=q[(q["_r"].isna())|(q["_r"]<=maxrank)]
    q=q[q["Confirmed listings"]>=covmin]
    st.caption("Rank 1 = market cap অনুযায়ী তালিকার শীর্ষ coin। এটি quality বা লাভের ranking নয়। UNKNOWN মানে API ব্যর্থ; NO নয়।")
    cols=["Rank","Coin","Name","Current price (USD)","Market cap (USD)","24h volume (USD)","24h change (%)","Layer","Confirmed listings",*EN.values()]
    st.dataframe(q[cols],use_container_width=True,hide_index=True)
    st.download_button("Ranking CSV download",q[cols].to_csv(index=False).encode("utf-8-sig"),"coin_ranking.csv","text/csv")

with t2:
    st.subheader("সব coin-এর তথ্য একসাথে")
    st.markdown("""
| Column | মানে |
|---|---|
| Rank | CoinGecko market-cap rank; 1 সবচেয়ে বড় |
| Current price | CoinGecko-এর USD price; exchange price নিচে আলাদা table-এ |
| Market cap | circulating supply × price ভিত্তিক আনুমানিক market value |
| 24h volume | গত ২৪ ঘণ্টার reported trading volume; order-book depth নয় |
| 24h change | গত ২৪ ঘণ্টায় দামের শতকরা পরিবর্তন |
| Layer | পরিচিত symbol/category থেকে আনুমানিক Layer 1/2 |
| Confirmed listings | সফল API-গুলোর মধ্যে কয়টিতে USDT spot pair পাওয়া গেছে |
| YES / NO / UNKNOWN | YES=pair আছে; NO=API সফল, pair নেই; UNKNOWN=API load হয়নি |
""")
    search=st.text_input("Coin name বা symbol দিয়ে খুঁজুন")
    view=coins.copy()
    if search:view=view[view.Coin.str.contains(search,case=False,na=False)|view.Name.astype(str).str.contains(search,case=False,na=False)]
    cols=["Rank","Coin","Name","Current price (USD)","Market cap (USD)","24h volume (USD)","24h change (%)","Layer","Confirmed listings",*EN.values()]
    st.dataframe(view[cols],use_container_width=True,hide_index=True)
    st.download_button("Coin table CSV download",view[cols].to_csv(index=False).encode("utf-8-sig"),"coin_information.csv","text/csv")
    if not view.empty:
        selected=st.selectbox("Exchange-wise price দেখতে coin বাছুন",view.Coin.tolist())
        rows=[]
        for e in EX:
            pair=pairs(mks.get(e,{})).get(selected) if e in mks else None
            if e not in mks:rows.append({"Exchange":EN[e],"Listing":"UNKNOWN (API unavailable)","Pair":"—","Price":None,"24h change %":None,"24h volume":None})
            elif not pair:rows.append({"Exchange":EN[e],"Listing":"NO","Pair":"—","Price":None,"24h change %":None,"24h volume":None})
            else:
                try:rows.append({"Exchange":EN[e],"Listing":"YES","Pair":pair,**ticker(e,pair)})
                except Exception:rows.append({"Exchange":EN[e],"Listing":"YES, price API failed","Pair":pair,"Price":None,"24h change %":None,"24h volume":None})
        st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)

        st.markdown("#### CoinGecko দিয়ে exchange listing cross-check")
        st.caption("CoinGecko-এর market/ticker তথ্য ব্যবহার করে selected coin-এর USDT market যাচাই করে। এটি exchange-এর নিজস্ব API নয়; pair/coverage অসম্পূর্ণ হলে UNKNOWN দেখাবে।")
        selected_row=view[view.Coin==selected].iloc[0]
        cg_id=selected_row.get("_cg_id")
        if cg_id:
            if st.button("🔎 CoinGecko থেকে ৫ exchange listing যাচাই",key="cg_verify_listing"):
                with st.spinner(f"{selected} এর CoinGecko market pairs আনা হচ্ছে..."):
                    st.session_state["cg_listing_check"]=(selected,cg_exchange_listings(cg_id,cgkey))
            check=st.session_state.get("cg_listing_check")
            if check and check[0]==selected:
                payload=check[1]
                if payload.get("error"):
                    st.warning("CoinGecko ticker data পাওয়া যায়নি: "+payload["error"])
                    st.info("API rate limit বা network error হলে কিছুক্ষণ পরে আবার চেষ্টা করুন।")
                else:
                    result_rows=[]
                    for e in EX:
                        item=payload["results"][e]
                        result_rows.append({"Exchange":EN[e],"CoinGecko status":item["status"],"USDT pair(s)":item["pairs"],"Source":item["source"]})
                    st.dataframe(pd.DataFrame(result_rows),use_container_width=True,hide_index=True)
                    if payload["complete"]:
                        st.success(f"CoinGecko ticker scan complete ({payload['pages']} page(s)). NO মানে scan করা ticker list-এ USDT market পাওয়া যায়নি; এটা exchange-এর সম্পূর্ণ delisting প্রমাণ নয়।")
                    else:
                        st.warning("CoinGecko ticker data 10 page-এ পৌঁছেছে; listing feed অসম্পূর্ণ হতে পারে। তাই যেসব exchange-এ pair মেলেনি সেগুলো UNKNOWN দেখানো হয়েছে।")
                    st.download_button("Listing verification CSV download",pd.DataFrame(result_rows).to_csv(index=False).encode("utf-8-sig"),f"{selected}_exchange_listing_check.csv","text/csv")
        else:
            st.info("এই coin-এর CoinGecko ID নেই, তাই aggregator listing check চালানো যাবে না।")

with t3:
    st.subheader("Historical DCA cycle-গুলোর table")
    choices=coins[coins["Confirmed listings"]>0].Coin.tolist()
    if not choices:st.warning("কোনো working exchange-এ historical pair পাওয়া যায়নি।")
    else:
        coin=st.selectbox("Backtest coin",choices)
        available=[e for e in EX if e in mks and coin in pairs(mks[e])]
        if not available:st.warning("এই coin-এর জন্য working historical source নেই।")
        else:
            source=st.selectbox("Historical data source",available,format_func=lambda e:EN[e])
            st.write(f"Strategy: drop {drop*100:.1f}% | TP {tp*100:.1f}% | multiplier {scale:.2f}× | max {steps} additional buys | {days} days | candle {tf}")
            st.caption("PASS=target hit. FAIL/UNRECOVERED=selected period শেষে target hit হয়নি। OHLC approximation; fee, spread ও slippage নেই।")
            if st.button("▶ DCA backtest চালান",type="primary"):
                try:
                    with st.spinner("Historical candles আনা হচ্ছে..."):hist=history(source,pairs(mks[source])[coin],tf,days)
                    if hist.empty or len(hist)<2:st.error("পর্যাপ্ত historical candle পাওয়া যায়নি।")
                    else:
                        trades,s=backtest(hist,drop,tp,scale,steps)
                        row=coins[coins.Coin==coin].iloc[0]
                        cg={"market_cap_rank":row.Rank,"market_cap":row["Market cap (USD)"]}
                        detail=cg_detail(row.get("_cg_id"),cgkey) if row.get("_cg_id") else {}
                        total,rating,why,metrics=score(coin,cg,int(row["Confirmed listings"]),hist,s,detail.get("categories",[]))
                        st.session_state["result"]=(trades,s,total,rating,why,metrics,coin,EN[source],len(hist))
                except Exception as err:st.error(f"Backtest error: {type(err).__name__}: {str(err)[:250]}")
            if "result" in st.session_state:
                trades,s,total,rating,why,metrics,coinname,src,n=st.session_state["result"]
                st.success(f"{coinname} | {src} | {n:,} candles")
                a,b,c,d,e=st.columns(5);a.metric("মোট cycle",s["cycles"]);b.metric("PASS",s["pass"]);c.metric("FAIL",s["fail"]);d.metric("PASS rate",f'{s["pass_rate"]:.1f}%');e.metric("Updated score",f"{total}/100")
                st.write("Rating: "+rating)
                st.markdown("**Summary column-এর মানে:** মোট cycle=পরীক্ষিত cycle; PASS=target hit; FAIL=period শেষে target hit হয়নি; PASS rate=PASS ÷ মোট cycle।")
                if metrics:st.dataframe(pd.DataFrame([metrics]),use_container_width=True,hide_index=True)
                st.markdown("#### প্রতিটি cycle-এর বিস্তারিত table")
                for col in ["শুরু সময়","শেষ সময়"]:trades[col]=pd.to_datetime(trades[col],utc=True).dt.strftime("%Y-%m-%d %H:%M UTC")
                st.dataframe(trades,use_container_width=True,hide_index=True)
                st.download_button("DCA cycle CSV download",trades.to_csv(index=False).encode("utf-8-sig"),f"{coinname}_DCA_cycles.csv","text/csv")

with t4:
    st.subheader("এতে কী লাভ?")
    st.markdown("""
- **Coin shortlist:** market-cap rank ধরে coin সাজানো।
- **Exchange যাচাই:** exchange API + selected coin-এর জন্য CoinGecko ticker cross-check; অসম্পূর্ণ data হলে UNKNOWN।
- **Price তুলনা:** একই coin-এর exchange-wise current price।
- **DCA পরীক্ষা:** আপনার নিয়মে historical PASS/FAIL এবং unrecovered cycle দেখা।
- **ঝুঁকি বোঝা:** drawdown, volatility ও period return দেখা।
""")
    st.dataframe(pd.DataFrame([
        {"Score অংশ":"Fundamentals","সর্বোচ্চ":"40","মানে":"Market-cap rank/size, Layer এবং meme category penalty"},
        {"Score অংশ":"Exchange coverage","সর্বোচ্চ":"20","মানে":"পাঁচ exchange-এ listing coverage"},
        {"Score অংশ":"Market health","সর্বোচ্চ":"20","মানে":"Return, maximum drawdown, volatility"},
        {"Score অংশ":"DCA history","সর্বোচ্চ":"20","মানে":"Historical PASS rate; কম cycle হলে কম weight"},
    ]),use_container_width=True,hide_index=True)
    st.warning("Market-cap rank আর quality score এক জিনিস নয়। Score heuristic; future profit guarantee করে না। FAIL মানে শুধু নির্বাচিত period-এ recovery হয়নি।")
