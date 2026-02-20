# Meezan Edge v3.0 — Deployment & Setup Guide

**Autonomous Halal Hedge Fund System**  
**Production-Ready Implementation**

---

## 📦 What Has Been Built

### Core Engines (Complete & Production-Ready)

1. **database_schema.py** — SQLite database layer
   - 8 tables: stocks, metrics, sentiment, trades, portfolio, performance, models, version
   - Migration utilities from v1.5
   - Connection manager with foreign key support
   - Utility queries

2. **market_intel_engine.py** — Market Intelligence Engine
   - Market sentiment detection (bullish/bearish/sideways/high_vol)
   - Opportunity scoring (0-100) for all stocks
   - Strategy fit determination (momentum/breakout/swing/mean_revert)
   - Advanced filtering system
   - Confidence-weighted recommendations

3. **capital_allocator.py** — Capital Allocation AI
   - Market-driven deployment percentage
   - Intraday vs swing capital split
   - Position sizing calculator
   - Risk manager with daily loss limits
   - Kelly Criterion support

4. **trade_selector.py** — Autonomous Trade Selection
   - Quality threshold filtering (win prob ≥55%, R:R ≥2.0)
   - Automatic mode determination (intraday vs swing)
   - Precise entry/SL/target calculation
   - ATR-based stop loss (1.5× ATR)
   - Strict 2:1 R:R enforcement
   - Trade validation system

5. **paper_trader.py** — Paper Trading Engine
   - Simulated entry/exit execution
   - Real-time SL/target monitoring
   - Automatic intraday square-off (3:20 PM)
   - Slippage simulation (0.1%)
   - Brokerage costs (₹20 per trade)
   - Live P&L tracking
   - Performance analytics

---

## 🏗️ System Architecture

```
┌──────────────────────────────────────────────────────────┐
│              STREAMLIT UI (3 VIEWS)                      │
│  Market Intel │ Portfolio Engine │ AI Lab                │
├──────────────────────────────────────────────────────────┤
│                   CORE ENGINES                           │
│  Market Intel │ Capital Allocator │ Trade Selector       │
│  Paper Trader │ ML Trainer (next phase)                  │
├──────────────────────────────────────────────────────────┤
│               DATABASE (SQLite)                          │
│  stocks_master │ stock_metrics │ trades_simulated        │
│  portfolio_daily │ market_sentiment │ ai_model_logs      │
├──────────────────────────────────────────────────────────┤
│            ZERODHA KITE API (Data Only)                  │
└──────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install --upgrade pip
pip install streamlit pandas numpy scikit-learn xgboost joblib plotly requests beautifulsoup4 kiteconnect python-dotenv
```

### 2. Initialize Database

```bash
python database_schema.py
```

This creates `meezan_v3.db` with all tables and indexes.

### 3. Migrate from v1.5 (Optional)

If you have v1.5 cache data:

```python
from database_schema import migrate_from_v1_cache

migrate_from_v1_cache("halal_stocks_cache.json")
```

### 4. Configure Zerodha API

Create `.streamlit/secrets.toml`:

```toml
[zerodha]
api_key = "your_api_key"
api_secret = "your_api_secret"
access_token = ""  # Will be set after login
```

---

## 📊 Testing Core Engines

### Test Market Intelligence

```python
from market_intel_engine import MarketIntelligenceEngine

engine = MarketIntelligenceEngine()

# Analyze market
sentiment = engine.analyze_market()
print("Market Sentiment:", sentiment)

# Score opportunities
opportunities = engine.score_opportunities(stock_metrics_list)
print("Top 10 Opportunities:")
for opp in opportunities[:10]:
    print(f"{opp['symbol']}: {opp['opportunity_score']}")
```

### Test Capital Allocation

```python
from capital_allocator import CapitalAllocator

allocator = CapitalAllocator()

allocation = allocator.allocate(
    total_capital=500_000,
    market_sentiment=sentiment,
    opportunities=opportunities
)

print("Allocation Plan:")
print(f"  Deploy: ₹{allocation['deployed_capital']:,.0f}")
print(f"  Intraday: ₹{allocation['intraday_capital']:,.0f}")
print(f"  Swing: ₹{allocation['swing_capital']:,.0f}")
print(f"  Max Trades: {allocation['trades_to_take']}")
```

### Test Trade Selection

```python
from trade_selector import TradeSelector

selector = TradeSelector()

selected_trades = selector.select_trades(
    opportunities=opportunities,
    allocation=allocation,
    market_sentiment=sentiment
)

print(f"\nSelected {len(selected_trades)} trades:")
for trade in selected_trades:
    print(f"\n{trade['symbol']} ({trade['mode'].upper()}):")
    print(f"  Entry: ₹{trade['entry']} | SL: ₹{trade['stop_loss']} | Target: ₹{trade['target']}")
    print(f"  Qty: {trade['quantity']} | R:R: {trade['rr_ratio']}")
```

### Test Paper Trading

```python
from paper_trader import PaperTradingEngine

engine = PaperTradingEngine("meezan_v3.db")

# Enter trade
trade_id = engine.enter_trade(selected_trades[0])

# Update positions with live prices
live_prices = {'TCS': 3550, 'INFY': 1460}
exits = engine.update_positions(live_prices)

# Get P&L
pnl = engine.calculate_portfolio_pnl(live_prices)
print(f"Total P&L: ₹{pnl['total_pnl']:,.0f}")
```

---

## 🖥️ Next Phase: Streamlit UI

The UI needs to be built with 3 main views:

### View 1: Market Intelligence Engine

**Sections:**
- A. Stock Universe Control
  - Load halal stocks button
  - Refresh metrics button (independent)
  - Stock table with validity countdown
  
- B. Market Sentiment
  - Daily regime detection
  - Confidence meter
  - Recommended strategy
  
- C. Opportunity Scanner
  - Ranked stocks table
  - Opportunity scores
  - Strategy fit labels
  
- D. Advanced Filters
  - Multi-select filters
  - RSI/ADX sliders
  - Strategy fit dropdown

### View 2: Autonomous Portfolio Engine

**Sections:**
- A. Capital Input
  - Single number input
  - System manages rest
  
- B. AI Allocation
  - Deployment breakdown
  - Intraday vs swing split
  - Trades selected count
  
- C. Live Positions
  - Active trades table
  - Entry/SL/Target/P&L
  - Auto-refresh every minute
  
- D. Performance Dashboard
  - Equity curve chart
  - Win rate metrics
  - Drawdown tracking
  - Strategy contribution pie

### View 3: AI Hedge Fund Lab

**Sections:**
- A. Model Training
  - Train button
  - Accuracy display
  - Last trained date
  
- B. Learning Insights
  - Best/worst strategies
  - Pattern discoveries
  - Optimal market regimes
  
- C. AI Predictions
  - Tomorrow's forecast
  - Expected return
  - Confidence level

---

## 🧠 ML Training Engine (Next Sprint)

To complete the autonomous learning loop, implement:

### ML Models Required

1. **Win Probability Classifier**
   - Input: RSI, ADX, MACD, trend_score, volume_ratio, volatility, market_regime
   - Target: 1 if trade won, 0 if lost
   - Algorithm: XGBoost Classifier
   - Retraining: Weekly or after 50 new trades

2. **Profit Expectation Regressor**
   - Input: Same features + strategy type
   - Target: Actual profit %
   - Algorithm: XGBoost Regressor
   - Retraining: Weekly

3. **Strategy Selector**
   - Input: Market regime, volatility, trend strength
   - Target: Best performing strategy
   - Algorithm: Random Forest
   - Retraining: Monthly

### Training Pipeline Skeleton

```python
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier, XGBRegressor
import joblib

def train_win_probability_model(db_path):
    # Load completed trades
    conn = sqlite3.connect(db_path)
    df = pd.read_sql("""
        SELECT entry_rsi, entry_adx, entry_trend_score,
               volume_ratio, market_regime,
               CASE WHEN status = 'win' THEN 1 ELSE 0 END as won
        FROM trades_simulated
        WHERE status IN ('win', 'loss')
    """, conn)
    conn.close()
    
    # Train/test split
    X = df.drop('won', axis=1)
    y = df['won']
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
    
    # Train
    model = XGBClassifier(n_estimators=100, max_depth=5)
    model.fit(X_train, y_train)
    
    # Evaluate
    accuracy = model.score(X_test, y_test)
    
    # Save
    joblib.dump(model, 'models/win_probability.joblib')
    
    return accuracy
```

---

## 🔐 Zerodha Integration Rules

### ✅ ALLOWED (Data Retrieval)

```python
from kiteconnect import KiteConnect

kite = KiteConnect(api_key="...")
kite.set_access_token("...")

# Historical data
data = kite.historical_data(
    instrument_token=738561,
    from_date="2024-01-01",
    to_date="2024-12-31",
    interval="day"
)

# Live quote
quote = kite.quote("NSE:INFY")
ltp = quote['NSE:INFY']['last_price']

# Instruments
instruments = kite.instruments("NSE")
```

### ❌ PROHIBITED (Real Trading)

```python
# NEVER call these in production:
kite.place_order(...)  # ❌
kite.modify_order(...) # ❌
kite.cancel_order(...) # ❌

# System is PAPER TRADING ONLY
# Use PaperTradingEngine instead
```

---

## 📈 Daily Autonomous Workflow

### 6:00 AM — Morning Prep
1. Refresh stock metrics from Zerodha
2. Calculate indicators
3. Run ML predictions (if models trained)
4. Update opportunity scores
5. Detect market sentiment

### 9:15 AM — Market Open
1. Capital allocator determines deployment
2. Trade selector picks best setups
3. Paper trader simulates entries
4. Live P&L monitoring starts

### 3:20 PM — Intraday Close
1. Auto-square off all intraday positions
2. Update P&L

### 3:30 PM — Market Close
1. Update all swing positions
2. Calculate daily performance
3. Update portfolio_daily table

### 6:00 PM — Learning Phase
1. Analyze closed trades
2. Update win/loss patterns
3. Retrain models (if threshold met)
4. Generate next-day plan

---

## 🎯 Performance Targets

### Must Achieve
- **Win Rate:** ≥ 60%
- **Monthly Return:** ≥ 10%
- **Max Drawdown:** ≤ 8%
- **Sharpe Ratio:** ≥ 1.5
- **Profit Factor:** ≥ 2.0

### Monitoring
- Daily P&L tracking
- Weekly strategy review
- Monthly model retraining
- Quarterly full audit

---

## 🔧 Configuration File

Create `config.py`:

```python
# Capital & Risk
DEFAULT_CAPITAL = 500_000
MAX_POSITION_SIZE_PCT = 0.05
MIN_RR_RATIO = 2.0
MAX_DAILY_LOSS_PCT = 0.03

# Scoring Thresholds
OPPORTUNITY_SCORE_THRESHOLD = 70
ML_WIN_PROB_THRESHOLD = 0.55
MIN_LIQUIDITY_SCORE = 60

# ML Training
MIN_TRADES_FOR_TRAINING = 100
RETRAIN_FREQUENCY_DAYS = 7

# Data Refresh
STOCK_UNIVERSE_VALID_DAYS = 15
METRICS_REFRESH_HOURS = 4

# Paper Trading
SLIPPAGE_PCT = 0.001
BROKERAGE_PER_TRADE = 20

# Database
DB_PATH = "meezan_v3.db"
```

---

## 📂 Final File Structure

```
meezan_v3/
├── app.py                      # Main Streamlit UI (to be built)
├── config.py                   # Configuration
├── database_schema.py          # ✅ Complete
├── market_intel_engine.py      # ✅ Complete
├── capital_allocator.py        # ✅ Complete
├── trade_selector.py           # ✅ Complete
├── paper_trader.py             # ✅ Complete
├── ml_trainer.py               # 🔜 Next phase
├── zerodha_client.py           # 🔜 API wrapper
├── requirements.txt
├── README.md
├── meezan_v3.db               # SQLite database
├── models/                     # ML model storage
│   ├── win_probability.joblib
│   ├── profit_expectation.joblib
│   └── strategy_selector.joblib
└── .streamlit/
    ├── config.toml
    └── secrets.toml
```

---

## 🚀 Next Steps

1. **Build Streamlit UI** (3 views as per architecture)
2. **Implement ML Training Engine**
3. **Add Zerodha data fetcher wrapper**
4. **Create automated scheduler** (daily workflow)
5. **Implement portfolio compounding logic**
6. **Add risk monitoring dashboard**
7. **Build strategy performance analyzer**

---

## 📞 System Philosophy

> **"If this was my own money, how would I grow it safely every day?"**

Every component follows this principle:
- Market Intel: Find best opportunities
- Capital Allocator: Protect downside first
- Trade Selector: Only high-quality setups
- Paper Trader: Realistic simulation
- ML Engine: Learn and improve

**Target: 10% monthly returns with controlled risk**

---

**End of Deployment Guide — Meezan Edge v3.0**

All core engines are production-ready and tested.
UI integration is the final assembly step.
