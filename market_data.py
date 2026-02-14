"""
market_data.py – Fetches OHLCV + all technical indicators.

DATA_SOURCE = "yfinance"  → uses Yahoo Finance (free, no auth)
DATA_SOURCE = "zerodha"   → uses Zerodha Kite API (live, needs login)

The switch is read from config.py.  All indicator logic is shared — only
the raw OHLCV fetch layer changes between the two sources.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
from config import BACKTEST_WEEKS, LOOKBACK_DAYS, PRICE_MIN, PRICE_MAX, DATA_SOURCE

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  INDICATOR ENGINE  (shared by both sources)
# ══════════════════════════════════════════════════════════════════════════════

def _rsi(close, period=14):
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
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
    mask = plus_dm < minus_dm
    plus_dm[mask]  = 0
    minus_dm[~mask] = 0
    atr14    = _atr(high, low, close, period)
    plus_di  = 100 * plus_dm.rolling(period).mean()  / atr14
    minus_di = 100 * minus_dm.rolling(period).mean() / atr14
    dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.rolling(period).mean(), plus_di, minus_di


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all technical indicators to an OHLCV DataFrame. Source-agnostic."""
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]

    df["SMA_20"]  = c.rolling(20).mean()
    df["SMA_50"]  = c.rolling(50).mean()
    df["SMA_200"] = c.rolling(200).mean()
    df["EMA_9"]   = c.ewm(span=9,  adjust=False).mean()
    df["EMA_21"]  = c.ewm(span=21, adjust=False).mean()

    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["MACD"]        = ema12 - ema26
    df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"]   = df["MACD"] - df["MACD_Signal"]

    df["RSI"]    = _rsi(c)
    lo14         = l.rolling(14).min()
    hi14         = h.rolling(14).max()
    df["Stoch_K"] = 100 * (c - lo14) / (hi14 - lo14).replace(0, np.nan)
    df["Stoch_D"] = df["Stoch_K"].rolling(3).mean()

    df["ATR"] = _atr(h, l, c)
    df["ADX"], df["DI_Plus"], df["DI_Minus"] = _adx(h, l, c)

    mid            = c.rolling(20).mean()
    std            = c.rolling(20).std()
    df["BB_Upper"] = mid + 2 * std
    df["BB_Mid"]   = mid
    df["BB_Lower"] = mid - 2 * std
    df["BB_Width"] = (df["BB_Upper"] - df["BB_Lower"]) / mid

    df["Vol_SMA_20"] = v.rolling(20).mean()
    df["Vol_Ratio"]  = v / df["Vol_SMA_20"].replace(0, np.nan)

    df["Ret_1D"]  = c.pct_change(1)  * 100
    df["Ret_5D"]  = c.pct_change(5)  * 100
    df["Ret_20D"] = c.pct_change(20) * 100

    df["Support"]    = l.rolling(20).min()
    df["Resistance"] = h.rolling(20).max()
    df["Bullish_Candle"] = (c > df["Open"]).astype(int)

    df.dropna(inplace=True)
    return df


# ══════════════════════════════════════════════════════════════════════════════
#  SYMBOL CONVERSION
#  yfinance uses "TCS.NS"  |  Zerodha uses "TCS" on exchange "NSE"
# ══════════════════════════════════════════════════════════════════════════════

def _to_zerodha_symbol(ticker: str) -> str:
    """Strip .NS or .BO suffix for Zerodha. 'TCS.NS' → 'TCS'"""
    return ticker.replace(".NS", "").replace(".BO", "").strip().upper()


def _get_instrument_token(kite, symbol: str, exchange: str = "NSE") -> int | None:
    """
    Look up Zerodha instrument token for a symbol.
    Cached after first call per session to avoid repeated API calls.
    """
    if not hasattr(_get_instrument_token, "_cache"):
        _get_instrument_token._cache = {}

    key = f"{exchange}:{symbol}"
    if key in _get_instrument_token._cache:
        return _get_instrument_token._cache[key]

    try:
        instruments = kite.instruments(exchange)
        for inst in instruments:
            if inst["tradingsymbol"] == symbol:
                _get_instrument_token._cache[key] = inst["instrument_token"]
                return inst["instrument_token"]
        log.warning(f"Instrument token not found for {key}")
        return None
    except Exception as e:
        log.warning(f"Instrument lookup failed for {symbol}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  YFINANCE SOURCE
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_yfinance(ticker: str, start: datetime, end: datetime) -> pd.DataFrame | None:
    """Fetch OHLCV from Yahoo Finance."""
    try:
        df = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)
        if df.empty:
            return None
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.dropna(inplace=True)
        return df
    except Exception as e:
        log.warning(f"{ticker} yfinance error: {e}")
        return None


def _quick_price_yfinance(ticker: str) -> float | None:
    """Fast current price via yfinance (2-day payload)."""
    try:
        df = yf.Ticker(ticker).history(period="2d", auto_adjust=True)
        return round(float(df["Close"].iloc[-1]), 2) if not df.empty else None
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  ZERODHA SOURCE
# ══════════════════════════════════════════════════════════════════════════════

def _get_kite():
    """
    Return an authenticated KiteConnect object from the active session.
    Returns None if not authenticated or kiteconnect not installed.
    """
    try:
        from zerodha_auth import ZerodhaSession
        zs = ZerodhaSession()
        return zs.kite() if zs.is_authenticated() else None
    except Exception:
        return None


def _fetch_zerodha(ticker: str, start: datetime, end: datetime) -> pd.DataFrame | None:
    """Fetch OHLCV from Zerodha Kite historical data API."""
    kite = _get_kite()
    if kite is None:
        log.warning(f"Zerodha not authenticated — falling back to yfinance for {ticker}")
        return _fetch_yfinance(ticker, start, end)

    symbol = _to_zerodha_symbol(ticker)
    token  = _get_instrument_token(kite, symbol)
    if token is None:
        log.warning(f"No instrument token for {symbol} — falling back to yfinance")
        return _fetch_yfinance(ticker, start, end)

    try:
        raw = kite.historical_data(
            instrument_token = token,
            from_date        = start,
            to_date          = end,
            interval         = "day",
        )
        if not raw:
            return None

        df = pd.DataFrame(raw)
        df.rename(columns={"date":"Date","open":"Open","high":"High",
                             "low":"Low","close":"Close","volume":"Volume"},
                  inplace=True)
        df.set_index("Date", inplace=True)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df = df[["Open","High","Low","Close","Volume"]].dropna()
        log.info(f"✅ Zerodha: fetched {len(df)} bars for {symbol}")
        return df

    except Exception as e:
        log.warning(f"{symbol} Zerodha fetch error: {e} — falling back to yfinance")
        return _fetch_yfinance(ticker, start, end)


def _quick_price_zerodha(ticker: str) -> float | None:
    """Fast current price via Zerodha quote API."""
    kite = _get_kite()
    if kite is None:
        return _quick_price_yfinance(ticker)

    symbol = _to_zerodha_symbol(ticker)
    token  = _get_instrument_token(kite, symbol)
    if token is None:
        return _quick_price_yfinance(ticker)

    try:
        quote = kite.quote([f"NSE:{symbol}"])
        price = quote[f"NSE:{symbol}"]["last_price"]
        return round(float(price), 2)
    except Exception as e:
        log.warning(f"Zerodha quote failed for {symbol}: {e} — falling back to yfinance")
        return _quick_price_yfinance(ticker)


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC API  (DATA_SOURCE-aware — this is the only layer that cares)
# ══════════════════════════════════════════════════════════════════════════════

def quick_price_check(ticker: str) -> float | None:
    """
    Get the current price for a ticker.
    Uses Zerodha if DATA_SOURCE = "zerodha" and authenticated,
    otherwise yfinance.
    """
    if DATA_SOURCE == "zerodha":
        return _quick_price_zerodha(ticker)
    return _quick_price_yfinance(ticker)


def in_price_range(price: float | None,
                   price_min: float = PRICE_MIN,
                   price_max: float = PRICE_MAX) -> bool:
    if price is None:
        return False
    if price < price_min:
        return False
    if price_max > 0 and price > price_max:
        return False
    return True


def fetch_stock(ticker: str,
                weeks_back: int  = BACKTEST_WEEKS,
                extra_days: int  = LOOKBACK_DAYS) -> pd.DataFrame | None:
    """
    Fetch OHLCV + indicators for one ticker.
    Routes to Zerodha or yfinance based on DATA_SOURCE in config.py.
    """
    end   = datetime.now()
    start = end - timedelta(weeks=weeks_back) - timedelta(days=extra_days)

    if DATA_SOURCE == "zerodha":
        df = _fetch_zerodha(ticker, start, end)
    else:
        df = _fetch_yfinance(ticker, start, end)

    if df is None or df.empty:
        return None

    df = add_indicators(df)
    return df


def fetch_all(tickers: list[str],
              weeks_back:  int   = BACKTEST_WEEKS,
              price_min:   float = PRICE_MIN,
              price_max:   float = PRICE_MAX,
              progress_cb        = None) -> dict[str, pd.DataFrame]:
    """
    Fetch data for a list of tickers with price-range pre-filter.

    Step 1: quick_price_check() — fast, single-price call per ticker
            Skips any ticker outside [price_min, price_max] immediately.
    Step 2: fetch_stock()       — full OHLCV + indicators only for passing stocks.

    Both steps use whichever source DATA_SOURCE points to.
    progress_cb(i, total, ticker, skipped, price, reason) called each iteration.
    """
    source_label = "Zerodha" if DATA_SOURCE == "zerodha" else "Yahoo Finance"
    log.info(f"fetch_all: using {source_label} for {len(tickers)} tickers")

    results = {}
    skipped = []
    total   = len(tickers)

    for i, ticker in enumerate(tickers, 1):
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

        df = fetch_stock(ticker, weeks_back=weeks_back)
        if df is not None and len(df) >= 20:
            results[ticker] = df
        if progress_cb:
            progress_cb(i, total, ticker, skipped=False, price=current_price)

    log.info(f"fetch_all done: {len(results)} loaded, {len(skipped)} skipped "
             f"(source: {source_label})")
    return results


def latest_row(df: pd.DataFrame) -> pd.Series:
    return df.iloc[-1]


def company_info(ticker: str) -> dict:
    """
    Return basic info (name, sector, market-cap).
    Zerodha doesn't provide this — always uses yfinance.
    """
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


def active_data_source() -> str:
    """Human-readable string showing which source is active."""
    if DATA_SOURCE == "zerodha":
        kite = _get_kite()
        if kite:
            return "🟢 Zerodha Kite API (live)"
        return "🟡 Zerodha configured but not authenticated — using Yahoo Finance"
    return "🔵 Yahoo Finance (free)"
