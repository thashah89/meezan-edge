# 🕌 Halal Stock Trading System
### Automated Shariah-Compliant Swing Trading · Streamlit Dashboard

---

## 📁 FILE STRUCTURE

```
trading_system/
├── config.py           ← ALL your settings (capital, risk, weeks)
├── scraper.py          ← Scrapes halalstock.in automatically
├── market_data.py      ← Fetches OHLCV + 20+ indicators via yfinance
├── trend_filter.py     ← Classifies stocks as uptrend / downtrend
├── pattern_engine.py   ← Finds similar historical patterns
├── backtester.py       ← 5 strategies × recent-data backtesting
├── app.py              ← Streamlit dashboard (6 pages)
├── requirements.txt    ← Python dependencies
├── run.bat             ← Windows one-click launcher
└── run.sh              ← Mac/Linux one-click launcher
```

---

## 🚀 QUICK START

### Step 1 — Install Python (if needed)
Download Python 3.10+ from https://python.org

### Step 2 — Install dependencies
```bash
pip install -r requirements.txt
```

### Step 3 — Launch the dashboard

**Windows:**
```
Double-click  run.bat
```

**Mac / Linux:**
```bash
bash run.sh
```

**Manual:**
```bash
streamlit run app.py
```

Browser opens automatically at **http://localhost:8501**

---

## ⚙️ CONFIGURATION  (`config.py`)

Edit this file to personalise the system — no other file needs changing.

| Setting | Default | Meaning |
|---------|---------|---------|
| `TOTAL_CAPITAL` | ₹1,00,000 | Your full trading budget |
| `CAPITAL_PER_TRADE` | ₹25,000 | Fixed amount per trade |
| `RISK_PCT_PER_TRADE` | 2.0 | % of capital risked (stop-sizing) |
| `MAX_POSITIONS` | 4 | Simultaneous open trades |
| `BACKTEST_WEEKS` | 4 | Recent weeks to backtest |
| `TREND_ADX_MIN` | 20 | Min ADX to count as "trending" |
| `TREND_RSI_MIN/MAX` | 40 / 75 | RSI band for healthy uptrend |
| `STOP_LOSS_ATR_MULT` | 2.0 | Stop = entry − (2 × ATR) |
| `TARGET_RR_RATIO` | 2.5 | Target = entry + (2.5 × risk) |
| `PATTERN_WINDOW_DAYS` | 10 | Days in pattern comparison |
| `PATTERN_TOP_N` | 3 | Historical matches to show |

---

## 📊 DASHBOARD PAGES

### 🏠 Overview
- Summary metrics (stocks loaded, uptrend count, backtested)
- Top uptrend stocks table
- Best strategy recommendations at a glance

### 📋 Stock Universe
- Full list of Halal stocks scraped from halalstock.in
- Trend status, RSI, ADX, 20-day return for each
- Filter by trend type and industry

### 📈 Trend Analysis
- Stocks confirmed in uptrend (score ≥ 4/9)
- RSI vs Return scatter chart
- Per-stock deep-dive with candle chart + RSI panel
- Signal checklist (6 criteria with ✅/❌)
- Support & resistance levels

### 🔬 Backtest Results
- Best strategy per stock (ranked by return %)
- Full strategy comparison table
- Trade log with entry/exit/stop/target
- Win/loss pie chart
- Equity curve overlay for all 5 strategies

### 🔍 Pattern Analysis
- Finds historical windows that match the current chart shape
- Shows similarity score (0–100%)
- Shows what the stock did NEXT after each match
- Confidence level (HIGH / MEDIUM / LOW)
- Visual overlay: matched pattern vs future movement

### 🎯 Trade Recommendations
- Best stock + strategy combos, ranked
- Exact entry price, stop loss, target 1 & 2
- Position size and investment amount
- Why this stock was selected (technical checklist)
- Backtest stats, pattern confidence
- Price chart with stop/target lines drawn
- CSV export of all recommendations

---

## 🔄 DAILY WORKFLOW

```
1. Open dashboard (run.bat)
2. Click "Refresh Data"    → scrapes Halal list + downloads prices
3. Click "Backtest All"    → tests all 5 strategies on uptrend stocks
4. Go to 🎯 Recommendations → pick top 2-3 trades
5. Execute manually in Zerodha/broker
6. Repeat next day
```

---

## 🎯 THE 5 STRATEGIES

| # | Strategy | Entry Signal | Stop | Target |
|---|----------|-------------|------|--------|
| 1 | **Trend Following** | EMA9 × EMA21 + ADX > 22 | 2 × ATR | 2.5 × risk |
| 2 | **Mean Reversion** | Price ≤ Lower BB + RSI < 35 | 2 × ATR | 2.5 × risk |
| 3 | **Momentum Breakout** | New 20D high + Vol > 1.4× + RSI 48-72 | 2 × ATR | 2.5 × risk |
| 4 | **Swing Trading** | Bounce off support + bullish candle + volume | 2 × ATR | 2.5 × risk |
| 5 | **MACD RSI Combo** | MACD cross + RSI 42-63 + above SMA50 | 2 × ATR | 2.5 × risk |

All stops and targets are **dynamic** — calculated from the current ATR at the time of entry.

---

## 📐 HOW PATTERN RECOGNITION WORKS

1. Takes the last N days of price data (normalised to 0–1 shape)
2. Slides a same-length window across all historical data
3. Computes cosine similarity at each position
4. Keeps matches above the minimum similarity threshold
5. Looks forward N days from each match and records the outcome
6. Reports: similarity %, entry price, exit price, % gain/loss, confidence

> **Example output:**  
> "Found 3 similar patterns. Avg outcome: +7.4% in 10 days. Historical win rate: 67%. Confidence: HIGH"

---

## 💰 UNDERSTANDING YOUR RETURNS

### Three numbers you'll see:

| Term | Formula | Example |
|------|---------|---------|
| **Trade Return %** | Profit ÷ Money invested in trade | ₹980 ÷ ₹25,000 = **3.92%** |
| **Capital Return %** | Profit ÷ Total capital | ₹980 ÷ ₹1,00,000 = **0.98%** |
| **Annualised %** | Period return × (365 ÷ days tested) | 4% in 4 weeks → **~52% annual** |

### Position sizing example (₹1,00,000 capital):
```
Per trade:   ₹25,000
Stock price: ₹3,500
Shares:      7   (₹25,000 ÷ ₹3,500)
ATR:         ₹70
Stop loss:   ₹3,500 − (2 × ₹70) = ₹3,360
Risk:        7 × ₹140 = ₹980   (0.98% of capital)
Target:      ₹3,500 + (2.5 × ₹140) = ₹3,850
Reward:      7 × ₹350 = ₹2,450
```

---

## 🔌 ZERODHA INTEGRATION (Phase 2)

When you're ready to go live, only `market_data.py` needs updating:

```python
# Replace yfinance fetch with:
from kiteconnect import KiteConnect
kite = KiteConnect(api_key="YOUR_KEY")

def fetch_stock(ticker, ...):
    data = kite.historical_data(
        instrument_token=token,
        from_date=start,
        to_date=end,
        interval="day"
    )
    df = pd.DataFrame(data)
    df = add_indicators(df)   # ← same function, zero changes
    return df
```

The entire strategy engine, backtester, pattern engine, and Streamlit dashboard
remain **100% unchanged**.

---

## 🛠️ TROUBLESHOOTING

| Problem | Fix |
|---------|-----|
| `streamlit: command not found` | Run `pip install streamlit` |
| `No data for TICKER.NS` | Stock may be delisted; will be skipped |
| "Table body not found" | halalstock.in layout may have changed; cached data still works |
| Very few uptrend stocks | Lower `TREND_ADX_MIN` in config.py (try 18) |
| No pattern matches found | Lower `PATTERN_MIN_SCORE` in config.py (try 50) |
| Backtest shows 0 trades | Widen `BACKTEST_WEEKS` or check stock has enough data |

---

## ⚠️ DISCLAIMER

This system is for **educational and research purposes only**.  
Past performance does not guarantee future results.  
Always do your own research before placing real trades.  
Position sizing, stop losses, and risk management are your responsibility.
