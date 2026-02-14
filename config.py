"""
config.py – All user-configurable settings.
Edit this file to change capital, risk, backtest period, etc.
NEVER put real API keys directly here — use .streamlit/secrets.toml locally
or Streamlit Cloud Secrets dashboard when deployed.
"""

# ── CREDENTIALS HELPER ────────────────────────────────────────────────────────
def _get_secret(key: str, fallback: str = "") -> str:
    """
    Read from Streamlit Secrets (works on Streamlit Cloud AND locally via
    .streamlit/secrets.toml).  Falls back to `fallback` if not found.
    """
    try:
        import streamlit as st
        return st.secrets.get(key, fallback)
    except Exception:
        return fallback

# ── CAPITAL SETTINGS ─────────────────────────────────────────────────────────
TOTAL_CAPITAL      = 100_000   # ₹ Total trading capital
CAPITAL_PER_TRADE  = 75_000    # ₹ Fixed amount invested per trade
RISK_PCT_PER_TRADE = 2.0       # % of total capital risked per trade (stop-loss sizing)
MAX_POSITIONS      = 10         # Max simultaneous open trades

# ── BACKTEST SETTINGS ─────────────────────────────────────────────────────────
BACKTEST_WEEKS     = 12         # How many recent weeks to backtest (1-12)
LOOKBACK_DAYS      = 365       # Extra historical days fetched for indicators & patterns
MAX_HOLD_DAYS      = 10        # Auto-exit after N days if target/stop not hit

# ── PRICE RANGE FILTER ───────────────────────────────────────────────────────
# Only stocks whose current price falls inside [PRICE_MIN, PRICE_MAX] will be
# downloaded, analysed, and backtested.  Set PRICE_MAX = 0 to disable the cap.
# Applied BEFORE full history download → dramatically speeds up Refresh Data.
PRICE_MIN          = 600       # ₹ Minimum stock price  (e.g. 100)
PRICE_MAX          = 2_500     # ₹ Maximum stock price  (0 = no upper limit)

# ── TREND FILTER THRESHOLDS ───────────────────────────────────────────────────
TREND_ADX_MIN      = 20        # Minimum ADX for "trending" market
TREND_RSI_MIN      = 40        # RSI floor for uptrend candidates
TREND_RSI_MAX      = 75        # RSI ceiling  (avoid overbought)
VOLUME_RATIO_MIN   = 1.0       # Min volume vs 20-day average

# ── STRATEGY PARAMETERS ──────────────────────────────────────────────────────
STOP_LOSS_ATR_MULT  = 1.5      # Stop = entry − (multiplier × ATR)
TARGET_RR_RATIO     = 2.0      # ★ STRICT 2:1  Target = entry + (2 × risk)
#                               # At 2:1 you only need >33.3% win rate to profit
#                               # At 40% win rate:  EV = 0.4×2R − 0.6×R = +0.2R per trade

# ── LIVE ENGINE SETTINGS ─────────────────────────────────────────────────────
LIVE_INTRADAY_INTERVAL = "5m"  # Intraday candle size for live signals ("1m","5m","15m","1h")
LIVE_INTRADAY_PERIOD   = "5d"  # yfinance period for intraday data
LIVE_SIGNAL_CONFIRM    = 2     # Min strategies that must agree to flag a STRONG signal
MIN_WIN_RATE_LIVE      = 40.0  # % – only show strategies that cleared this in backtest
MIN_PROFIT_FACTOR_LIVE = 1.3   # Must exceed this profit factor in backtest

# ── PATTERN RECOGNITION ──────────────────────────────────────────────────────
PATTERN_WINDOW_DAYS = 10       # Days in the pattern window
PATTERN_TOP_N       = 3        # Number of historical matches to show
PATTERN_MIN_SCORE   = 60       # Minimum similarity score (0-100) to show

# ── ZERODHA API CREDENTIALS ──────────────────────────────────────────────────
# Loaded from Streamlit Secrets — NEVER hardcode real keys in this file.
# Local dev:  add to  .streamlit/secrets.toml
# Production: add via  share.streamlit.io → App Settings → Secrets
ZERODHA_API_KEY      = _get_secret("ZERODHA_API_KEY")
ZERODHA_API_SECRET   = _get_secret("ZERODHA_API_SECRET")
ZERODHA_REDIRECT_URL = _get_secret("ZERODHA_REDIRECT_URL", "http://127.0.0.1:8501")
ZERODHA_POSTBACK_URL = _get_secret("ZERODHA_POSTBACK_URL", "")
ZERODHA_TOKEN_FILE   = "zerodha_token.json"

# ── DATA SOURCE ───────────────────────────────────────────────────────────────
DATA_SOURCE         = "zerodha"  # "yfinance" (free)  |  "zerodha" (live)
SCRAPER_URL         = "https://halalstock.in/halal-shariah-compliant-shares-list/"
CACHE_FILE          = "halal_stocks_cache.json"

# ── DISPLAY ───────────────────────────────────────────────────────────────────
APP_TITLE           = "🕌 Halal Stock Trading System"
ACCENT_COLOR        = "#00C49F"
