# Crypto Coin Scanner ও DCA পরীক্ষাগার (Bangla UI)

## GitHub + Streamlit Cloud-এ প্রকাশ
1. ZIP extract করুন।
2. `app.py` এবং `requirements.txt` GitHub repository-এর root-এ upload/replace করুন।
3. Streamlit Community Cloud-এ app-এর main file `app.py` দিন এবং deploy করুন।

## Windows-এ চালানো
`run_windows.bat` চালান, অথবা:
```bash
pip install -r requirements.txt
streamlit run app.py
```

## সতর্কতা
এটি research/backtesting tool; বিনিয়োগ পরামর্শ নয়। Exchange API hosting region থেকে blocked হতে পারে। DCA ফলাফল OHLC candle approximation; fee, spread, slippage ও execution risk পুরোপুরি অন্তর্ভুক্ত নয়।
