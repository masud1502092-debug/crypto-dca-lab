# Crypto Coin Scanner ও DCA Lab (Bangla) — V6

## নতুন কী আছে
- আগের V5 dashboard-এর ranking, exchange listing status, exchange-wise price, DCA backtest এবং CSV export রাখা হয়েছে।
- Tab 2-এ selected coin-এর জন্য **CoinGecko ticker/market-pair listing cross-check** যোগ করা হয়েছে।
- Binance, KuCoin, Bybit, Bitget, HTX-এ USDT market pair খোঁজে।
- CoinGecko feed অসম্পূর্ণ বা API error হলে অনিশ্চিত ফলকে `UNKNOWN` দেখায়; জোর করে `NO` বলে না।
- V5-এ থাকা DCA settings variable mismatch-ও ঠিক করা হয়েছে।

## Run locally
1. Python 3.10+ install করুন।
2. ZIP extract করুন।
3. Terminal/CMD-তে project folder খুলুন:
   `pip install -r requirements.txt`
4. Run:
   `streamlit run app.py`
5. Windows-এ `run_windows.bat`-এ double-click করেও চালাতে পারেন।

## Streamlit Community Cloud
GitHub-এ project files upload করুন, Streamlit Community Cloud-এ repository connect করে `app.py` select করুন।

## গুরুত্বপূর্ণ সীমাবদ্ধতা
- CoinGecko ticker list aggregator data; এটি exchange-এর সম্পূর্ণ official listing registry নয়। `NO` মানে scan করা ticker data-তে USDT pair পাওয়া যায়নি, delisting-এর চূড়ান্ত প্রমাণ নয়।
- CoinGecko public API rate limit করতে পারে; প্রয়োজন হলে Demo API key sidebar-এ দিন।
- Exchange API status network/hosting region-এর কারণে unavailable হলে `UNKNOWN` থাকবে।
- DCA OHLCV backtest approximate: fees, spread, slippage, order-book liquidity এবং candle-এর ভেতরের exact price path অন্তর্ভুক্ত নয়।
- `FAIL / UNRECOVERED` মানে নির্বাচিত test period শেষ হওয়ার আগে target hit হয়নি; ভবিষ্যতেও কখনো recover করবে না—এমন নয়।
- Quality score heuristic, profit guarantee বা financial advice নয়।
