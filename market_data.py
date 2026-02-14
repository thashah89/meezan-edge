"""
market_data.py – Fetches OHLCV + all technical indicators via yfinance.
Structured so the data-source can later be swapped to Zerodha with minimal changes.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
from config import BACKTEST_WEEKS, LOOKBACK_DAYS, PRICE_MIN, PRICE_MAX

log = logging.getLogger(__name__)


# ── INDICATOR HELPERS ─────────────────────────────────────────────────────────

def _rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _atr(high, low, close, period=14):
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _adx(high, low, close, period=14):
    plus_dm  = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    # where both are positive, keep only the larger one
    mask = plus_dm < minus_dm
    plus_dm[mask] = 0
    minus_dm[~mask] = 0

    atr14     = _atr(high, low, close, period)
    plus_di   = 100 * plus_dm.rolling(period).mean()  / atr14
    minus_di  = 100 * minus_dm.rolling(period).mean() / atr14
    dx        = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.rolling(period).mean(), plus_di, minus_di


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all technical indicators to an OHLCV DataFrame."""
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]

    # Moving averages
    df["SMA_20"]  = c.rolling(20).mean()
    df["SMA_50"]  = c.rolling(50).mean()
    df["SMA_200"] = c.rolling(200).mean()
    df["EMA_9"]   = c.ewm(span=9,  adjust=False).mean()
    df["EMA_21"]  = c.ewm(span=21, adjust=False).mean()

    # MACD
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["MACD"]        = ema12 - ema26
    df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"]   = df["MACD"] - df["MACD_Signal"]

    # RSI & Stochastic
    df["RSI"] = _rsi(c)
    lo14 = l.rolling(14).min()
    hi14 = h.rolling(14).max()
    df["Stoch_K"] = 100 * (c - lo14) / (hi14 - lo14).replace(0, np.nan)
    df["Stoch_D"] = df["Stoch_K"].rolling(3).mean()

    # ATR & ADX
    df["ATR"] = _atr(h, l, c)
    df["ADX"], df["DI_Plus"], df["DI_Minus"] = _adx(h, l, c)

    # Bollinger Bands
    mid            = c.rolling(20).mean()
    std            = c.rolling(20).std()
    df["BB_Upper"] = mid + 2 * std
    df["BB_Mid"]   = mid
    df["BB_Lower"] = mid - 2 * std
    df["BB_Width"] = (df["BB_Upper"] - df["BB_Lower"]) / mid

    # Volume
    df["Vol_SMA_20"]  = v.rolling(20).mean()
    df["Vol_Ratio"]   = v / df["Vol_SMA_20"].replace(0, np.nan)

    # Returns
    df["Ret_1D"]   = c.pct_change(1)  * 100
    df["Ret_5D"]   = c.pct_change(5)  * 100
    df["Ret_20D"]  = c.pct_change(20) * 100

    # Support / Resistance (rolling)
    df["Support"]    = l.rolling(20).min()
    df["Resistance"] = h.rolling(20).max()

    # Candle type
    df["Bullish_Candle"] = (c > df["Open"]).astype(int)

    df.dropna(inplace=True)
    return df


# ── FAST PRICE CHECK (no history download) ───────────────────────────────────

def quick_price_check(ticker: str) -> float | None:
    """
    Fetches only the last 2 days of daily data (tiny payload) to get the
    current price.  Used by fetch_all() to discard out-of-range stocks
    BEFORE downloading full history — keeps Refresh Data fast.

    Returns the latest close price, or None on error.
    """
    try:
        df = yf.Ticker(ticker).history(period="2d", auto_adjust=True)
        if df.empty:
            return None
        return round(float(df["Close"].iloc[-1]), 2)
    except Exception:
        return None


def in_price_range(price: float | None,
                   price_min: float = PRICE_MIN,
                   price_max: float = PRICE_MAX) -> bool:
    """
    Returns True when price passes the configured range filter.
    price_max == 0 means no upper limit.
    """
    if price is None:
        return False
    if price < price_min:
        return False
    if price_max > 0 and price > price_max:
        return False
    return True


# ── FETCH SINGLE STOCK ────────────────────────────────────────────────────────

def fetch_stock(ticker: str, weeks_back: int = BACKTEST_WEEKS,
                extra_days: int = LOOKBACK_DAYS) -> pd.DataFrame | None:
    """
    Fetch OHLCV + indicators for one ticker.
    Downloads extra history so indicators have enough warm-up data.
    """
    end   = datetime.now()
    start = end - timedelta(weeks=weeks_back) - timedelta(days=extra_days)

    try:
        t  = yf.Ticker(ticker)
        df = t.history(start=start, end=end, auto_adjust=True)

        if df.empty:
            return None

        # Normalise timezone
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.dropna(inplace=True)
        df = add_indicators(df)
        return df

    except Exception as e:
        log.warning(f"{ticker}: fetch error – {e}")
        return None


# ── FETCH MANY STOCKS ─────────────────────────────────────────────────────────

def fetch_all(tickers: list[str],
              weeks_back: int  = BACKTEST_WEEKS,
              price_min: float = PRICE_MIN,
              price_max: float = PRICE_MAX,
              progress_cb      = None) -> dict[str, pd.DataFrame]:
    """
    Fetch data for a list of tickers.

    Price-range pre-filter (FAST):
      For each ticker we first fetch only the last 2 days (lightweight).
      If the current price falls outside [price_min, price_max] the ticker
      is skipped immediately — no full history download required.
      price_max = 0 disables the upper limit.

    progress_cb(i, total, ticker, skipped=False) is called after each ticker.
    Returns {ticker: DataFrame}.
    """
    results  = {}
    skipped  = []
    total    = len(tickers)

    for i, ticker in enumerate(tickers, 1):
        # ── 1. Quick price check (fast — 2-day payload) ───────────────────
        current_price = quick_price_check(ticker)
        passed        = in_price_range(current_price, price_min, price_max)

        if not passed:
            price_str = f"₹{current_price:.0f}" if current_price else "N/A"
            range_str = (f"₹{price_min:.0f}–₹{price_max:.0f}"
                         if price_max > 0 else f"≥₹{price_min:.0f}")
            log.info(f"  ⏭  {ticker} skipped (price {price_str} outside {range_str})")
            skipped.append(ticker)
            if progress_cb:
                progress_cb(i, total, ticker, skipped=True,
                            price=current_price, reason="price filter")
            continue

        # ── 2. Full history download (only for in-range stocks) ───────────
        df = fetch_stock(ticker, weeks_back=weeks_back)
        if df is not None and len(df) >= 20:
            results[ticker] = df
        if progress_cb:
            progress_cb(i, total, ticker, skipped=False, price=current_price)

    log.info(f"Fetched {len(results)}/{total} tickers "
             f"({len(skipped)} skipped by price filter).")
    return results


# ── LATEST SNAPSHOT ───────────────────────────────────────────────────────────

def latest_row(df: pd.DataFrame) -> pd.Series:
    return df.iloc[-1]


def company_info(ticker: str) -> dict:
    """Return basic info dict from yfinance (name, sector, market-cap…)."""
    try:
        info = yf.Ticker(ticker).info
        return {
            "name":       info.get("longName", ticker),
            "sector":     info.get("sector", "N/A"),
            "market_cap": info.get("marketCap", 0),
            "pe_ratio":   info.get("trailingPE", None),
            "beta":       info.get("beta", None),
        }
    except Exception:
        return {"name": ticker, "sector": "N/A",
                "market_cap": 0, "pe_ratio": None, "beta": None}
