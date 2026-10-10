# Crypto Quality + DCA Lab V3

## Deploy to Streamlit Community Cloud
1. Extract this ZIP.
2. Upload `app.py` and `requirements.txt` to the root of a GitHub repository.
3. On Streamlit Community Cloud, create an app from that repository and set main file to `app.py`.

## Run on Windows
Run `run_windows.bat`, or:
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Notes
- Market listings and tickers are read from public CCXT exchange APIs.
- A 403/451 API block may depend on the hosting network/region; other exchanges continue loading.
- CoinGecko metadata may be unavailable or rate-limited. An optional demo key can be entered in the sidebar.
- Backtesting uses candle OHLC data. Same-candle DCA/TP ambiguity is treated conservatively (DCA first).
- Open cycles at the end of the selected period are marked FAIL_UNRECOVERED; this does not prove they will never recover.
- Fees, spread, slippage, token unlocks and delisting risks are not included.
- Scores are transparent heuristics, not financial advice.
