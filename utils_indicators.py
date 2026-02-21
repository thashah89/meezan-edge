"""
utils_indicators.py — Technical Indicators Calculator
"""

import pandas as pd
import numpy as np

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all technical indicators to OHLCV DataFrame."""
    df = df.copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.sort_values(by="date").reset_index(drop=True)
    
    # SMAs
    df['SMA_20'] = df['close'].rolling(20).mean()
    df['SMA_50'] = df['close'].rolling(50).mean()
    df['SMA_200'] = df['close'].rolling(200).mean()
    
    # EMAs
    df['EMA_5'] = df['close'].ewm(span=5).mean()
    df['EMA_9'] = df['close'].ewm(span=9).mean()
    df['EMA_10'] = df['close'].ewm(span=10).mean()
    df['EMA_20'] = df['close'].ewm(span=20).mean()
    df['EMA_21'] = df['close'].ewm(span=21).mean()
    df['EMA_50'] = df['close'].ewm(span=50).mean()
    df['EMA_100'] = df['close'].ewm(span=100).mean()
    df['EMA_200'] = df['close'].ewm(span=200).mean()
    
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # MACD
    ema12 = df['close'].ewm(span=12).mean()
    ema26 = df['close'].ewm(span=26).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_Signal'] = df['MACD'].ewm(span=9).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
    
    # ATR
    hl = df['high'] - df['low']
    hc = abs(df['high'] - df['close'].shift())
    lc = abs(df['low'] - df['close'].shift())
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()
    
    # Bollinger Bands
    sma20 = df['SMA_20']
    std20 = df['close'].rolling(20).std()
    df['BB_Upper'] = sma20 + (2 * std20)
    df['BB_Middle'] = sma20
    df['BB_Lower'] = sma20 - (2 * std20)
    df['BB_Width'] = ((df['BB_Upper'] - df['BB_Lower']) / sma20) * 100

    # Keltner channels
    df["Keltner_Middle"] = df["EMA_20"]
    df["Keltner_Upper"] = df["Keltner_Middle"] + (2 * df["ATR"])
    df["Keltner_Lower"] = df["Keltner_Middle"] - (2 * df["ATR"])
    
    # ADX
    df['ADX'] = calculate_adx(df)
    
    # Volume ratio
    df['Volume_SMA20'] = df['volume'].rolling(20).mean()
    df['Volume_Ratio'] = df['volume'] / df['Volume_SMA20']
    df['RVOL'] = df['Volume_Ratio']

    # Stochastic, CCI, Williams %R
    stoch_low = df["low"].rolling(14).min()
    stoch_high = df["high"].rolling(14).max()
    stoch_k_raw = 100 * ((df["close"] - stoch_low) / (stoch_high - stoch_low))
    df["Stoch_K"] = stoch_k_raw.rolling(3).mean()
    df["Stoch_D"] = df["Stoch_K"].rolling(3).mean()

    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    tp_sma = typical_price.rolling(20).mean()
    tp_mad = typical_price.rolling(20).apply(lambda x: np.abs(x - x.mean()).mean())
    df["CCI"] = (typical_price - tp_sma) / (0.015 * tp_mad)

    will_high = df["high"].rolling(14).max()
    will_low = df["low"].rolling(14).min()
    df["Williams_R"] = -100 * ((will_high - df["close"]) / (will_high - will_low))

    # Aroon
    aroon_period = 25
    df["Aroon_Up"] = 100 * df["high"].rolling(aroon_period + 1).apply(lambda x: x.argmax() / aroon_period)
    df["Aroon_Down"] = 100 * df["low"].rolling(aroon_period + 1).apply(lambda x: x.argmin() / aroon_period)

    # Enhanced meta indicators
    df["ATR_pct"] = np.where(df["close"] > 0, (df["ATR"] / df["close"]) * 100.0, np.nan)

    ma_alignment = (
        (df["close"] > df["SMA_20"]).astype(int) * 25
        + (df["SMA_20"] > df["SMA_50"]).astype(int) * 25
        + (df["SMA_50"] > df["SMA_200"]).astype(int) * 25
        + (df["close"] > df["SMA_200"]).astype(int) * 25
    )
    adx_strength = np.minimum(df["ADX"] * 2.5, 100)
    df["Trend_Strength"] = pd.concat([ma_alignment, adx_strength], axis=1).mean(axis=1)

    low_vol_cut = df["ATR_pct"].rolling(100, min_periods=20).quantile(0.33)
    med_vol_cut = df["ATR_pct"].rolling(100, min_periods=20).quantile(0.67)
    df["Volatility_Regime"] = np.select(
        [df["ATR_pct"] < low_vol_cut, df["ATR_pct"] < med_vol_cut],
        [1, 2],
        default=3,
    )

    # Previous bar/day references
    df["Prev_Close"] = df["close"].shift(1)
    df["Gap_Pct"] = np.where(
        df["Prev_Close"] > 0,
        ((df["open"] - df["Prev_Close"]) / df["Prev_Close"]) * 100.0,
        0.0,
    )

    # Consolidation context
    roll_window = 20
    df["Consolidation_High"] = df["high"].rolling(roll_window).max().shift(1)
    df["Consolidation_Low"] = df["low"].rolling(roll_window).min().shift(1)
    cons_range_pct = np.where(
        df["close"] > 0,
        ((df["Consolidation_High"] - df["Consolidation_Low"]) / df["close"]) * 100.0,
        np.nan,
    )
    df["Consolidation_Tight"] = cons_range_pct < 1.5

    # VWAP (session-aware for intraday if time component exists)
    if "date" in df.columns and df["date"].notna().any():
        has_intraday = bool((df["date"].dt.hour != 0).any() or (df["date"].dt.minute != 0).any())
    else:
        has_intraday = False

    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    if has_intraday:
        df["session_date"] = df["date"].dt.date
        tpv = typical_price * df["volume"]
        cum_tpv = tpv.groupby(df["session_date"]).cumsum()
        cum_vol = df["volume"].groupby(df["session_date"]).cumsum().replace(0, np.nan)
        df["VWAP"] = cum_tpv / cum_vol
    else:
        tpv = typical_price * df["volume"]
        cum_tpv = tpv.cumsum()
        cum_vol = df["volume"].cumsum().replace(0, np.nan)
        df["VWAP"] = cum_tpv / cum_vol

    # Previous-day high/low + CPR (+ ORB reference on intraday)
    if has_intraday:
        # Opening range (first 15 minutes = first 3 bars on 5m data)
        first3 = (
            df.groupby("session_date")
            .head(3)
            .groupby("session_date")
            .agg(OR_15_High=("high", "max"), OR_15_Low=("low", "min"))
        )
        df = df.merge(first3, how="left", left_on="session_date", right_index=True)
        df["Bars_From_Open"] = df.groupby("session_date").cumcount() + 1

        day_ohlc = (
            df.groupby("session_date")
            .agg(day_high=("high", "max"), day_low=("low", "min"), day_close=("close", "last"))
            .sort_index()
        )
        prev_day = day_ohlc.shift(1)
        prev_day["Pivot"] = (prev_day["day_high"] + prev_day["day_low"] + prev_day["day_close"]) / 3.0
        prev_day["CPR_BC"] = (prev_day["day_high"] + prev_day["day_low"]) / 2.0
        prev_day["CPR_TC"] = (2 * prev_day["Pivot"]) - prev_day["CPR_BC"]
        prev_day["CPR_High"] = prev_day[["CPR_BC", "CPR_TC"]].max(axis=1)
        prev_day["CPR_Low"] = prev_day[["CPR_BC", "CPR_TC"]].min(axis=1)
        prev_day["CPR_Width_Pct"] = np.where(
            prev_day["day_close"] > 0,
            ((prev_day["CPR_High"] - prev_day["CPR_Low"]) / prev_day["day_close"]) * 100.0,
            np.nan,
        )
        prev_day["Narrow_CPR"] = (
            prev_day["CPR_Width_Pct"]
            <= prev_day["CPR_Width_Pct"].rolling(20, min_periods=5).quantile(0.3)
        )

        map_cols = {
            "day_high": "Prev_Day_High",
            "day_low": "Prev_Day_Low",
            "CPR_High": "CPR_High",
            "CPR_Low": "CPR_Low",
            "Narrow_CPR": "Narrow_CPR",
        }
        for src, dst in map_cols.items():
            df[dst] = df["session_date"].map(prev_day[src])
    else:
        df["Prev_Day_High"] = df["high"].shift(1)
        df["Prev_Day_Low"] = df["low"].shift(1)
        pivot = (df["high"].shift(1) + df["low"].shift(1) + df["close"].shift(1)) / 3.0
        bc = (df["high"].shift(1) + df["low"].shift(1)) / 2.0
        tc = (2 * pivot) - bc
        df["CPR_High"] = pd.concat([bc, tc], axis=1).max(axis=1)
        df["CPR_Low"] = pd.concat([bc, tc], axis=1).min(axis=1)
        cpr_width_pct = np.where(
            df["close"].shift(1) > 0,
            ((df["CPR_High"] - df["CPR_Low"]) / df["close"].shift(1)) * 100.0,
            np.nan,
        )
        df["Narrow_CPR"] = cpr_width_pct <= pd.Series(cpr_width_pct).rolling(20, min_periods=5).quantile(0.3)
        df["OR_15_High"] = np.nan
        df["OR_15_Low"] = np.nan
        df["Bars_From_Open"] = np.nan
    
    return df

def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate ADX."""
    high = df['high']
    low = df['low']
    close = df['close']
    
    plus_dm = high.diff()
    minus_dm = low.diff().mul(-1)
    
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    
    tr = pd.concat([
        high - low,
        abs(high - close.shift()),
        abs(low - close.shift())
    ], axis=1).max(axis=1)
    
    atr = tr.rolling(period).mean()
    
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(period).mean()
    
    return adx
