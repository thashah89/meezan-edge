# Meezan Edge v3.0 — Autonomous Hedge Fund System Architecture

**Transformation:** Manual Dashboard → Autonomous AI Hedge Fund  
**Status:** Complete redesign from v1.5.0  
**Date:** 2026-02-15

---

## 🎯 Core Transformation

### From v1.5 (Manual)
- User browses stocks manually
- User selects trades
- User decides entry/exit
- 9 separate pages
- Backtesting only historical

### To v3.0 (Autonomous)
- System analyzes market daily
- System selects best trades
- System manages capital allocation
- 3 focused intelligence views
- Live paper trading with ML feedback

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     STREAMLIT UI (3 VIEWS)                  │
├─────────────────────────────────────────────────────────────┤
│  View 1              View 2                  View 3         │
│  Market Intel    │   Portfolio Engine    │   AI Lab        │
│  ├─ Universe     │   ├─ Capital Input    │   ├─ Training   │
│  ├─ Sentiment    │   ├─ Auto Allocator   │   ├─ Models     │
│  ├─ Scanner      │   ├─ Trade Selector   │   ├─ Learning   │
│  └─ Filters      │   └─ Paper Executor   │   └─ Optimizer  │
├─────────────────────────────────────────────────────────────┤
│                      CORE ENGINES                           │
│  ┌──────────────┬──────────────┬────────────┬─────────────┐│
│  │ Market Intel │ Capital AI   │ Paper Trade│ ML Engine   ││
│  │ Engine       │ Allocator    │ Simulator  │ Trainer     ││
│  └──────────────┴──────────────┴────────────┴─────────────┘│
├─────────────────────────────────────────────────────────────┤
│                    DATA LAYER (SQLite)                      │
│  ┌──────────┬──────────┬──────────┬──────────┬───────────┐ │
│  │ stocks   │ metrics  │ trades   │ portfolio│ models    │ │
│  │ _master  │          │          │ _daily   │ _logs     │ │
│  └──────────┴──────────┴──────────┴──────────┴───────────┘ │
├─────────────────────────────────────────────────────────────┤
│                 EXTERNAL INTEGRATIONS                       │
│  ┌──────────────────────┬────────────────────────────────┐ │
│  │ Zerodha Kite API     │ halalstock.in                  │ │
│  │ (data only)          │ (stock universe)               │ │
│  └──────────────────────┴────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## 📦 Module Structure

```
meezan_v3/
├── app.py                      ← Main Streamlit entry (3 views)
├── config.py                   ← Settings, constants
├── requirements.txt            ← Dependencies
│
├── database/
│   ├── __init__.py
│   ├── schema.py              ← SQLite schema + migrations
│   ├── models.py              ← ORM/query helpers
│   └── connection.py          ← DB connection manager
│
├── engines/
│   ├── __init__.py
│   ├── market_intel.py        ← Market analysis, sentiment, scoring
│   ├── capital_allocator.py   ← Dynamic capital distribution AI
│   ├── trade_selector.py      ← Autonomous trade selection
│   ├── paper_trader.py        ← Paper execution simulator
│   └── strategy_engine.py     ← Multi-strategy framework
│
├── ml/
│   ├── __init__.py
│   ├── train.py               ← Model training pipeline
│   ├── predict.py             ← Inference engine
│   ├── features.py            ← Feature engineering
│   └── models/                ← Saved model files (.joblib)
│       ├── win_probability.joblib
│       ├── profit_expectation.joblib
│       └── strategy_selector.joblib
│
├── data_sources/
│   ├── __init__.py
│   ├── zerodha_client.py      ← Kite API wrapper (data only)
│   ├── halal_scraper.py       ← Stock universe loader
│   └── market_data.py         ← OHLCV, indicators
│
├── utils/
│   ├── __init__.py
│   ├── indicators.py          ← Technical indicators
│   ├── risk.py                ← Risk calculations
│   └── logger.py              ← Logging system
│
└── .streamlit/
    ├── config.toml            ← UI theme
    └── secrets.toml           ← API keys (gitignored)
```

---

## 🗄️ Database Schema (SQLite → PostgreSQL ready)

### stocks_master
```sql
CREATE TABLE stocks_master (
    symbol TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    sector TEXT,
    exchange TEXT DEFAULT 'NSE',
    load_date DATE NOT NULL,
    valid_till DATE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### stock_metrics
```sql
CREATE TABLE stock_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    date DATE NOT NULL,
    ltp REAL,
    open REAL,
    high REAL,
    low REAL,
    volume INTEGER,
    -- Technical Indicators
    rsi REAL,
    adx REAL,
    macd REAL,
    sma_20 REAL,
    sma_50 REAL,
    sma_200 REAL,
    atr REAL,
    bb_upper REAL,
    bb_lower REAL,
    -- Derived Scores
    trend_score INTEGER,
    momentum_score INTEGER,
    volatility_score INTEGER,
    liquidity_score INTEGER,
    opportunity_score INTEGER,
    -- ML Predictions
    win_probability REAL,
    expected_return REAL,
    strategy_fit TEXT,
    confidence REAL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (symbol) REFERENCES stocks_master(symbol),
    UNIQUE(symbol, date)
);
```

### market_sentiment
```sql
CREATE TABLE market_sentiment (
    date DATE PRIMARY KEY,
    sentiment TEXT,  -- bullish, bearish, sideways, high_vol
    volatility TEXT, -- low, moderate, high
    confidence REAL,
    nifty_trend TEXT,
    market_breadth REAL,
    sector_strength TEXT,
    recommended_style TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### trades_simulated
```sql
CREATE TABLE trades_simulated (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    entry_date DATE NOT NULL,
    entry_price REAL NOT NULL,
    quantity INTEGER NOT NULL,
    stop_loss REAL NOT NULL,
    target REAL NOT NULL,
    exit_date DATE,
    exit_price REAL,
    exit_reason TEXT,
    -- Trade Classification
    mode TEXT, -- intraday, swing
    strategy TEXT,
    -- Results
    profit_loss REAL,
    profit_pct REAL,
    status TEXT, -- open, win, loss, breakeven
    -- Risk Metrics
    risk_amount REAL,
    reward_amount REAL,
    rr_ratio REAL,
    capital_used REAL,
    -- ML Features
    ml_win_prob REAL,
    ml_expected_return REAL,
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP,
    FOREIGN KEY (symbol) REFERENCES stocks_master(symbol)
);
```

### portfolio_daily
```sql
CREATE TABLE portfolio_daily (
    date DATE PRIMARY KEY,
    total_capital REAL NOT NULL,
    deployed_capital REAL,
    available_capital REAL,
    daily_pnl REAL,
    daily_pnl_pct REAL,
    monthly_pnl REAL,
    monthly_pnl_pct REAL,
    ytd_pnl REAL,
    ytd_pnl_pct REAL,
    total_trades INTEGER,
    winning_trades INTEGER,
    losing_trades INTEGER,
    win_rate REAL,
    avg_win REAL,
    avg_loss REAL,
    max_drawdown REAL,
    sharpe_ratio REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### strategy_performance
```sql
CREATE TABLE strategy_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name TEXT NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    total_trades INTEGER,
    winning_trades INTEGER,
    win_rate REAL,
    avg_return REAL,
    max_drawdown REAL,
    sharpe_ratio REAL,
    best_market_regime TEXT,
    worst_market_regime TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### ai_model_logs
```sql
CREATE TABLE ai_model_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    training_date DATE NOT NULL,
    accuracy REAL,
    precision_score REAL,
    recall REAL,
    f1_score REAL,
    dataset_size INTEGER,
    features_used TEXT,
    hyperparameters TEXT,
    model_path TEXT,
    performance_notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 🧠 Core Engine Logic

### 1. Market Intelligence Engine (`engines/market_intel.py`)

**Input:** Stock universe + latest metrics  
**Output:** Ranked opportunities + market sentiment

**Process:**
1. Calculate opportunity scores (0-100) for all stocks
2. Detect market regime (bullish/bearish/sideways/volatile)
3. Match stocks to optimal strategies
4. Rank by expected value = win_prob × expected_return

**Scoring Formula:**
```python
opportunity_score = (
    trend_strength * 0.25 +
    momentum_score * 0.20 +
    volume_confirmation * 0.15 +
    volatility_fit * 0.15 +
    ml_win_probability * 0.25
)
```

---

### 2. Capital Allocation AI (`engines/capital_allocator.py`)

**Input:** Total capital + market sentiment + opportunity list  
**Output:** Allocation plan

**Logic:**
```python
if market_sentiment == "aggressive_bullish":
    deploy_pct = 0.70
    intraday_pct = 0.40
    swing_pct = 0.60
elif market_sentiment == "bearish":
    deploy_pct = 0.30
    intraday_pct = 0.70  # faster exits
    swing_pct = 0.30
else:
    deploy_pct = 0.50
    intraday_pct = 0.50
    swing_pct = 0.50

deployed_capital = total_capital * deploy_pct
intraday_capital = deployed_capital * intraday_pct
swing_capital = deployed_capital * swing_pct

# Position sizing: Kelly Criterion or fixed % risk
position_size = min(
    kelly_fraction * capital,
    0.05 * capital  # max 5% per trade
)
```

---

### 3. Trade Selector (`engines/trade_selector.py`)

**Input:** Opportunity-ranked stocks + capital allocation  
**Output:** Selected trades with entry/SL/target

**Selection Criteria:**
```python
def select_trades(opportunities, capital, max_trades=10):
    selected = []
    for stock in opportunities:
        if len(selected) >= max_trades:
            break
        
        # Must pass all filters
        if (stock.win_probability < 0.55 or
            stock.rr_ratio < 2.0 or
            stock.liquidity_score < 60):
            continue
        
        # Calculate levels
        entry = stock.ltp
        sl = entry - (1.5 * stock.atr)
        risk = entry - sl
        target = entry + (2.0 * risk)
        
        selected.append({
            'symbol': stock.symbol,
            'entry': entry,
            'sl': sl,
            'target': target,
            'quantity': calculate_quantity(capital, risk),
            'expected_return': stock.expected_return,
            'win_prob': stock.win_probability
        })
    
    return selected
```

---

### 4. Paper Trading Engine (`engines/paper_trader.py`)

**Simulates real execution using live prices**

**Features:**
- Entry/exit tracking
- Live P&L updates
- Auto stop-loss/target hits
- Position management
- Daily settlement
- Historical trade log

**NO real orders placed** — pure simulation

---

### 5. ML Training Pipeline (`ml/train.py`)

**Models to train:**

#### A. Win Probability Classifier
- **Input Features:** RSI, ADX, MACD, trend_score, volume_ratio, volatility, market_regime
- **Target:** 1 if trade won, 0 if lost
- **Algorithm:** XGBoost Classifier
- **Retraining:** Weekly

#### B. Profit Expectation Regressor
- **Input Features:** Same + strategy type
- **Target:** Actual profit %
- **Algorithm:** XGBoost Regressor
- **Retraining:** Weekly

#### C. Strategy Selector
- **Input Features:** Market regime, volatility, trend, volume
- **Target:** Best performing strategy for that condition
- **Algorithm:** Random Forest Classifier
- **Retraining:** Monthly

**Training Data Source:**
- All completed trades in `trades_simulated`
- Minimum 100 trades before first training
- Incremental learning after that

---

## 🔄 Daily Autonomous Workflow

### 6:00 AM — Market Prep
1. Refresh stock metrics from Zerodha
2. Calculate indicators
3. Run ML predictions
4. Update opportunity scores
5. Detect market sentiment

### 9:15 AM — Market Open
1. Capital allocator determines deployment
2. Trade selector picks best setups
3. Paper trader simulates entries
4. Live P&L monitoring starts

### 3:30 PM — Market Close
1. Close all intraday positions
2. Update swing positions
3. Calculate daily P&L
4. Log performance metrics
5. Update strategy performance table

### 6:00 PM — Learning Phase
1. Analyze closed trades
2. Update win/loss patterns
3. Adjust strategy weights
4. Retrain models (if threshold met)
5. Generate next-day plan

---

## 📊 View 1 — Market Intelligence Engine (UI)

### Section A: Stock Universe Control
```
┌─────────────────────────────────────────────────┐
│ 🗂️ Stock Universe                              │
│                                                 │
│ [Load Halal Universe] [Refresh Metrics]        │
│                                                 │
│ Status: 347 stocks loaded                      │
│ Last refresh: 2 hours ago                      │
│ Next allowed refresh: in 13 days               │
│                                                 │
│ ┌─────────────────────────────────────────────┐│
│ │Symbol│Company        │Load Date│Valid Till││
│ │TCS   │Tata Consult...│15-Feb   │01-Mar    ││
│ │INFY  │Infosys        │15-Feb   │01-Mar    ││
│ └─────────────────────────────────────────────┘│
└─────────────────────────────────────────────────┘
```

### Section B: Market Sentiment
```
┌─────────────────────────────────────────────────┐
│ 🌡️ Market Regime Today                         │
│                                                 │
│ 🟢 AGGRESSIVE BULLISH                          │
│ Volatility: Moderate | Confidence: 84%         │
│                                                 │
│ Recommended: Momentum + Breakouts              │
│ Capital Deployment: 70%                         │
│ Intraday Focus: 40% | Swing Focus: 60%         │
└─────────────────────────────────────────────────┘
```

### Section C: Opportunity Scanner
```
┌─────────────────────────────────────────────────┐
│ 🔍 Top Opportunities (Ranked)                  │
│                                                 │
│ ┌─────────────────────────────────────────────┐│
│ │Symbol│Score│Strategy   │Confidence│ML Win ││
│ │TATAM │ 94  │Momentum   │ 88%      │ 72%  ││
│ │RELIAN│ 92  │Breakout   │ 86%      │ 68%  ││
│ │INFY  │ 89  │Swing Trend│ 82%      │ 71%  ││
│ └─────────────────────────────────────────────┘│
└─────────────────────────────────────────────────┘
```

---

## 📊 View 2 — Autonomous Portfolio Engine (UI)

### Section A: Capital Input
```
┌─────────────────────────────────────────────────┐
│ 💰 Capital Configuration                       │
│                                                 │
│ Total Capital: ₹ [5,00,000]                    │
│                                                 │
│ System will manage everything autonomously.    │
└─────────────────────────────────────────────────┘
```

### Section B: AI Allocation
```
┌─────────────────────────────────────────────────┐
│ 🤖 AI Capital Allocation Today                 │
│                                                 │
│ Deployed: ₹3,50,000 (70%)                      │
│ Intraday: ₹1,40,000 (40%)                      │
│ Swing:    ₹2,10,000 (60%)                      │
│                                                 │
│ Trades Selected: 7                              │
│ Expected Return: 1.8%                           │
│ Risk Level: Moderate                            │
└─────────────────────────────────────────────────┘
```

### Section C: Live Positions
```
┌─────────────────────────────────────────────────┐
│ 📊 Active Positions                            │
│                                                 │
│ ┌─────────────────────────────────────────────┐│
│ │Symbol│Mode│Entry│SL  │Target│P&L  │Status││
│ │TCS   │Swg │3500│3422│ 3656 │+2.1%│ 🟢   ││
│ │INFY  │Int │1450│1428│ 1494 │+1.4%│ 🟢   ││
│ └─────────────────────────────────────────────┘│
└─────────────────────────────────────────────────┘
```

### Section D: Performance Dashboard
```
┌─────────────────────────────────────────────────┐
│ 📈 Portfolio Performance                       │
│                                                 │
│ Capital:      ₹5,08,420 (+1.68%)               │
│ Daily P&L:    +₹8,420                          │
│ Monthly P&L:  +₹52,180 (+10.4%)                │
│ Win Rate:     68.2%                             │
│ Max Drawdown: 2.3%                              │
│                                                 │
│ [Equity Curve Chart]                            │
│ [Strategy Contribution Pie]                     │
└─────────────────────────────────────────────────┘
```

---

## 📊 View 3 — AI Hedge Fund Lab (UI)

### Section A: Model Training
```
┌─────────────────────────────────────────────────┐
│ 🧠 ML Model Status                             │
│                                                 │
│ Win Probability:     ✅ Trained (432 samples)  │
│   Accuracy: 71.2% | Last: 2 days ago           │
│                                                 │
│ Profit Expectation:  ✅ Trained (432 samples)  │
│   MAE: 0.82% | Last: 2 days ago                │
│                                                 │
│ Strategy Selector:   ✅ Trained (89 regimes)   │
│   Accuracy: 64.8% | Last: 1 week ago           │
│                                                 │
│ [Train All Models Now]                          │
└─────────────────────────────────────────────────┘
```

### Section B: Learning Dashboard
```
┌─────────────────────────────────────────────────┐
│ 📚 Self-Improvement Insights                   │
│                                                 │
│ Best Strategy (Last 30d): Momentum (78% win)   │
│ Worst Strategy: Mean Revert (41% win)          │
│                                                 │
│ Optimal Market: Bullish Moderate Vol           │
│ Avoid Trading: High Vol Sideways               │
│                                                 │
│ Pattern Learned: RSI >65 + ADX >30 = 82% win   │
└─────────────────────────────────────────────────┘
```

### Section C: AI Predictions
```
┌─────────────────────────────────────────────────┐
│ 🔮 Tomorrow's AI Forecast                      │
│                                                 │
│ Best Strategy: Breakout Momentum               │
│ Expected Daily Return: 1.6%                     │
│ Monthly Projection: 18.2%                       │
│ Confidence: 76%                                 │
│ Risk Level: Moderate-High                       │
│ Recommended Deployment: 65%                     │
└─────────────────────────────────────────────────┘
```

---

## 🔐 Zerodha Integration Rules (Strict)

### ✅ ALLOWED (Data Only)
- Historical OHLCV candles
- Live price quotes (LTP)
- Market depth
- Instrument master list

### ❌ PROHIBITED (No Real Trading)
- `place_order()` calls
- `modify_order()` calls
- Real capital deployment
- Actual position holding

**Implementation:**
```python
class ZerodhaClient:
    def __init__(self, api_key, access_token):
        self.kite = KiteConnect(api_key=api_key)
        self.kite.set_access_token(access_token)
        self.PAPER_TRADING_MODE = True  # ← LOCKED
    
    def place_order(self, *args, **kwargs):
        if self.PAPER_TRADING_MODE:
            raise PermissionError(
                "Real order placement is DISABLED. "
                "System operates in paper trading mode only."
            )
        # Real order code never reached
```

---

## 🚀 Migration Path (v1.5 → v3.0)

### Phase 1: Database Setup
1. Create SQLite database
2. Migrate stock list from `halal_stocks_cache.json`
3. Import historical backtest results as initial training data

### Phase 2: Engine Development
1. Build market_intel engine
2. Build capital_allocator
3. Build trade_selector
4. Build paper_trader

### Phase 3: ML Integration
1. Prepare feature engineering
2. Train initial models on backtest data
3. Integrate predictions into trade selection

### Phase 4: UI Transformation
1. Replace 9 pages with 3 views
2. Wire engines to UI
3. Add live dashboards

### Phase 5: Autonomous Operation
1. Daily scheduler
2. Auto-refresh metrics
3. Auto-select trades
4. Auto-update models

---

## 📈 Success Metrics

### System Must Achieve
- Win rate ≥ 60%
- Monthly return ≥ 10%
- Max drawdown ≤ 8%
- Sharpe ratio ≥ 1.5
- Model accuracy ≥ 65%

### Monitoring
- Daily P&L tracking
- Weekly strategy review
- Monthly model retraining
- Quarterly performance audit

---

## ⚙️ Configuration (`config.py`)

```python
# Capital & Risk
DEFAULT_CAPITAL = 500_000
MAX_POSITION_SIZE_PCT = 0.05  # 5% per trade
MIN_RR_RATIO = 2.0
MAX_DAILY_LOSS_PCT = 0.03  # 3% daily stop

# Market Intelligence
OPPORTUNITY_SCORE_THRESHOLD = 70
ML_WIN_PROB_THRESHOLD = 0.55
MIN_LIQUIDITY_SCORE = 60

# ML Training
MIN_TRADES_FOR_TRAINING = 100
RETRAIN_FREQUENCY_DAYS = 7
MODEL_ACCURACY_THRESHOLD = 0.60

# Data Refresh
STOCK_UNIVERSE_VALID_DAYS = 15
METRICS_REFRESH_HOURS = 4

# Paper Trading
SLIPPAGE_PCT = 0.001  # 0.1%
BROKERAGE_PER_TRADE = 20
```

---

## 📦 Dependencies (`requirements.txt`)

```
streamlit>=1.30.0
pandas>=2.0.0
numpy>=1.24.0
scikit-learn>=1.3.0
xgboost>=2.0.0
joblib>=1.3.0
plotly>=5.17.0
requests>=2.31.0
beautifulsoup4>=4.12.0
kiteconnect>=4.2.0
SQLAlchemy>=2.0.0  # ORM if needed
python-dotenv>=1.0.0
schedule>=1.2.0  # for daily automation
```

---

## 🧪 Testing Strategy

### Unit Tests
- Each engine independently testable
- Mock Zerodha API responses
- Verify scoring logic
- Test position sizing

### Integration Tests
- End-to-end trade flow
- Database integrity
- ML pipeline
- UI state management

### Backtesting Validation
- Run v3 engine on historical data
- Compare with v1.5 backtest results
- Validate >10% monthly target is achievable

---

**End of Architecture Document**

This is the complete blueprint. Next: Full implementation of all modules.
