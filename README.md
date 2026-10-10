# Crypto Quality + DCA Lab v2

A Streamlit web app that scans Binance, KuCoin, Bybit, Bitget and HTX USDT spot markets, confirms listing coverage, shows current prices, classifies Layer 1/Layer 2/Other, and runs a configurable historical DCA backtest.

## Updated score
The 0–100 score is intentionally transparent:
- Fundamentals: 40 points — market-cap rank, market cap, Layer classification, meme/speculative penalty.
- 5-exchange coverage: 20 points — listing on Binance/KuCoin/Bybit/Bitget/HTX.
- Market health: 20 points — 1Y return, maximum drawdown and annualized volatility.
- DCA history: 20 points — historical PASS rate, with fewer cycles receiving lower confidence.

Ratings: A Strong (80+), B Good (65–79), C Watch (50–64), D High Risk (<50).

## DCA defaults
- Initial buy
- Buy after every 3% decline from the latest buy
- Next order = 1.10x previous order
- Take profit = 1% above weighted average entry
- Maximum 15 DCA additions
- If TP is not reached before the test window ends: FAIL_UNRECOVERED

The backtester uses OHLCV candles and assumes the adverse event occurs first if a candle can touch both DCA and TP levels. This is conservative but cannot reproduce exact intrabar execution.

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Free online hosting — easiest method: Streamlit Community Cloud
1. Create a GitHub account.
2. Create a new repository, e.g. `crypto-dca-lab`.
3. Upload `app.py` and `requirements.txt` from this folder.
4. Open Streamlit Community Cloud and connect GitHub.
5. Choose the repository, branch `main`, and file `app.py`.
6. Choose an app subdomain and deploy.
7. You get a public `streamlit.app` URL that works from Android/iPhone/PC.

Community Cloud is free and connects directly to GitHub repositories. Code changes can be deployed automatically.

## Recommended architecture for future tools
GitHub = code storage/version control
→ Streamlit Community Cloud = free web hosting
→ APIs = live market/data sources
→ SQLite/Google Sheets/Supabase = persistent data if needed
→ Android Chrome = mobile access

For private API keys, use Streamlit Secrets rather than hard-coding keys into GitHub.

## Important production improvements
Add exchange fees, spread, slippage, liquidity filters, delisting handling, minimum coin age, API retry/backoff, and a more rigorous fundamental data source before using the score for live trading decisions.
