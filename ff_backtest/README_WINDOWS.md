# Forward Factor Backtest (Windows Quick Start)

## 1) Create venv & install deps
```powershell
cd C:\path\to\ff_backtest
python -m venv venv
.env\Scriptsctivate
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
