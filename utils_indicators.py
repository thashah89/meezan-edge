"""
utils_indicators.py — Technical Indicators Calculator
"""

import pandas as pd
import numpy as np

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all technical indicators to OHLCV DataFrame."""
    df = df.copy()
    
    # SMAs
    df['SMA_20'] = df['close'].rolling(20).mean()
    df['SMA_50'] = df['close'].rolling(50).mean()
    df['SMA_200'] = df['close'].rolling(200).mean()
    
    # EMAs
    df['EMA_9'] = df['close'].ewm(span=9).mean()
    df['EMA_21'] = df['close'].ewm(span=21).mean()
    
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
    df['BB_Lower'] = sma20 - (2 * std20)
    df['BB_Width'] = ((df['BB_Upper'] - df['BB_Lower']) / sma20) * 100
    
    # ADX
    df['ADX'] = calculate_adx(df)
    
    # Volume ratio
    df['Volume_SMA20'] = df['volume'].rolling(20).mean()
    df['Volume_Ratio'] = df['volume'] / df['Volume_SMA20']
    
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

