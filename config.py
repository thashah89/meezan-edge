"""
config.py — System Configuration

PROFIT MAXIMIZATION MODE:
- Target: 15-25% monthly returns
- Risk: Controlled with daily limits
- Deployment: Aggressive when confidence high
"""
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
#  CAPITAL & RISK MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

# Capital
DEFAULT_CAPITAL = 500_000

# Position Sizing (AGGRESSIVE for max profit)
MAX_POSITION_SIZE_PCT = 0.08  # 8% per trade (increased from 5%)
MAX_RISK_PER_TRADE_PCT = 0.025  # 2.5% risk (increased from 2%)
MAX_DAILY_LOSS_PCT = 0.04  # 4% daily stop (increased from 3%)

# Deployment (DYNAMIC based on confidence)
MAX_DEPLOYMENT_PCT = 0.85  # Up to 85% when very confident
MIN_DEPLOYMENT_PCT = 0.25  # Minimum 25% even in bad markets

# ══════════════════════════════════════════════════════════════════════════════
#  TRADE SELECTION (QUALITY FILTERS)
# ══════════════════════════════════════════════════════════════════════════════

# ML Thresholds
ML_WIN_PROB_THRESHOLD = 0.58  # 58% minimum (increased from 55%)
ML_CONFIDENCE_THRESHOLD = 0.65  # 65% confidence minimum

# Opportunity Scoring
OPPORTUNITY_SCORE_THRESHOLD = 75  # Increased from 70
MIN_LIQUIDITY_SCORE = 65  # Increased from 60

# Risk-Reward
MIN_RR_RATIO = 2.0  # Minimum 2:1
AGGRESSIVE_RR_RATIO = 3.0  # Target 3:1 when possible

# Stop Loss
ATR_MULTIPLIER = 1.5  # 1.5 × ATR for stop loss

# ══════════════════════════════════════════════════════════════════════════════
#  ML TRAINING
# ══════════════════════════════════════════════════════════════════════════════

MIN_TRADES_FOR_TRAINING = 100
RETRAIN_FREQUENCY_DAYS = 5  # Retrain every 5 days (faster learning)
MODEL_ACCURACY_TARGET = 0.72  # Target 72% accuracy

# ══════════════════════════════════════════════════════════════════════════════
#  DATA MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

# Stock Universe
STOCK_UNIVERSE_VALID_DAYS = 15
METRICS_REFRESH_HOURS = 3  # Refresh every 3 hours

# ══════════════════════════════════════════════════════════════════════════════
#  PAPER TRADING SIMULATION
# ══════════════════════════════════════════════════════════════════════════════

SLIPPAGE_PCT = 0.0008  # 0.08% slippage
BROKERAGE_PER_TRADE = 20  # ₹20 flat

# ══════════════════════════════════════════════════════════════════════════════
#  DATABASE
# ══════════════════════════════════════════════════════════════════════════════

DB_PATH = str((Path(__file__).resolve().parent / "meezan_v3.db"))

# ══════════════════════════════════════════════════════════════════════════════
#  PROFIT MAXIMIZATION STRATEGIES
# ══════════════════════════════════════════════════════════════════════════════

# Compounding
ENABLE_COMPOUNDING = True  # Reinvest profits
COMPOUND_FREQUENCY = "weekly"  # Recalculate capital weekly

# Trailing Stops (for profit protection)
ENABLE_TRAILING_STOPS = True
TRAILING_STOP_ACTIVATION = 1.5  # Activate after 1.5% profit
TRAILING_STOP_DISTANCE = 0.8  # Trail by 0.8%

# Position Scaling (add to winners)
ENABLE_POSITION_SCALING = True
SCALING_PROFIT_THRESHOLD = 2.0  # Scale after 2% profit
SCALING_SIZE_PCT = 0.5  # Add 50% more

# Dynamic R:R (increase targets when confidence high)
ENABLE_DYNAMIC_RR = True
HIGH_CONFIDENCE_RR = 3.5  # 3.5:1 when win prob > 75%
MEDIUM_CONFIDENCE_RR = 2.5  # 2.5:1 when win prob 65-75%

# ══════════════════════════════════════════════════════════════════════════════
#  PERFORMANCE TARGETS
# ══════════════════════════════════════════════════════════════════════════════

TARGET_MONTHLY_RETURN = 0.15  # 15% minimum
TARGET_WIN_RATE = 0.65  # 65% win rate
MAX_DRAWDOWN = 0.10  # 10% max drawdown
TARGET_SHARPE = 2.0  # Sharpe ratio 2.0


