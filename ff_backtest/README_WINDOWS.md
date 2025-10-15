# Forward Factor Backtest (Windows Quick Start)

## 1) Create venv & install deps
```powershell
cd C:\path\to\ff_backtest
python -m venv venv
## 2) Add your AlphaVantage key
ALPHAVANTAGE_API_KEY=YOUR_REAL_KEY
The free tier allows 5 requests per minute. The fetch script automatically
throttles to stay within that limit.
pip install -r requirements.txt
```

## 2) Add your Polygon key
Edit `.env` and set:
```
POLYGON_API_KEY=YOUR_REAL_KEY
```

## 3) Fetch data
```powershell
python fetch_daily.py
```
This writes `sample_data\iv_snapshots.csv` in the same folder.

## 4) Run the backtest
```powershell
python run_example.py
```
