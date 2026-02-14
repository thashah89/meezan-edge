"""
trend_filter.py – Classifies each stock's trend and filters to uptrend candidates.
"""

import pandas as pd
import numpy as np
from market_data import latest_row
from config import TREND_ADX_MIN, TREND_RSI_MIN, TREND_RSI_MAX, VOLUME_RATIO_MIN


TREND_LABELS = {
    5: "🟢 STRONG UP",
    4: "🟢 UP",
    3: "🟡 NEUTRAL",
    2: "🔴 DOWN",
    1: "🔴 STRONG DOWN",
}


def classify_trend(df: pd.DataFrame) -> dict:
    """
    Score each stock across 6 criteria → trend label + numeric score.

    Returns a dict with all metrics + trend label.
    """
    r = latest_row(df)

    # ── individual signals ────────────────────────────────────────────────────
    price_above_sma200 = int(r["Close"] > r["SMA_200"])  if pd.notna(r.get("SMA_200")) else 0
    price_above_sma50  = int(r["Close"] > r["SMA_50"])   if pd.notna(r.get("SMA_50"))  else 0
    price_above_sma20  = int(r["Close"] > r["SMA_20"])   if pd.notna(r.get("SMA_20"))  else 0
    golden_cross       = int(r["SMA_50"] > r["SMA_200"]) if pd.notna(r.get("SMA_50")) and pd.notna(r.get("SMA_200")) else 0
    macd_bullish       = int(r["MACD"] > r["MACD_Signal"]) if pd.notna(r.get("MACD")) else 0
    rsi_healthy        = int(TREND_RSI_MIN <= r["RSI"] <= TREND_RSI_MAX) if pd.notna(r.get("RSI")) else 0
    adx_trending       = int(r["ADX"] >= TREND_ADX_MIN)  if pd.notna(r.get("ADX")) else 0
    volume_ok          = int(r["Vol_Ratio"] >= VOLUME_RATIO_MIN) if pd.notna(r.get("Vol_Ratio")) else 0
    ret_positive       = int(r.get("Ret_20D", 0) > 0)

    # ── composite score (0-9) ─────────────────────────────────────────────────
    score = sum([price_above_sma200, price_above_sma50, price_above_sma20,
                 golden_cross, macd_bullish, rsi_healthy,
                 adx_trending, volume_ok, ret_positive])

    # ── map score → trend label ───────────────────────────────────────────────
    if   score >= 7: trend_level = 5
    elif score >= 5: trend_level = 4
    elif score >= 3: trend_level = 3
    elif score >= 2: trend_level = 2
    else:            trend_level = 1

    # ── pct from key MAs ─────────────────────────────────────────────────────
    def pct_from(ma_val):
        if pd.notna(ma_val) and ma_val != 0:
            return round((r["Close"] - ma_val) / ma_val * 100, 2)
        return None

    return {
        "trend_label":       TREND_LABELS[trend_level],
        "trend_score":       score,
        "trend_level":       trend_level,      # 1-5
        "is_uptrend":        trend_level >= 4,

        # Price data
        "current_price":     round(r["Close"], 2),
        "change_20d_pct":    round(r.get("Ret_20D", 0), 2),
        "change_5d_pct":     round(r.get("Ret_5D",  0), 2),

        # Indicators
        "rsi":               round(r["RSI"], 1)           if pd.notna(r.get("RSI")) else None,
        "adx":               round(r["ADX"], 1)           if pd.notna(r.get("ADX")) else None,
        "macd":              round(r["MACD"], 3)           if pd.notna(r.get("MACD")) else None,
        "vol_ratio":         round(r["Vol_Ratio"], 2)      if pd.notna(r.get("Vol_Ratio")) else None,
        "atr":               round(r["ATR"], 2)            if pd.notna(r.get("ATR")) else None,
        "bb_width":          round(r.get("BB_Width", 0)*100, 2),

        # Distance from MAs
        "pct_from_sma20":    pct_from(r.get("SMA_20")),
        "pct_from_sma50":    pct_from(r.get("SMA_50")),
        "pct_from_sma200":   pct_from(r.get("SMA_200")),

        # Signal flags
        "price_above_sma200": bool(price_above_sma200),
        "price_above_sma50":  bool(price_above_sma50),
        "golden_cross":        bool(golden_cross),
        "macd_bullish":        bool(macd_bullish),
        "rsi_healthy":         bool(rsi_healthy),
        "adx_trending":        bool(adx_trending),

        # Support / Resistance
        "support":     round(r.get("Support", 0), 2),
        "resistance":  round(r.get("Resistance", 0), 2),
    }


def filter_uptrend_stocks(stock_data: dict) -> list[dict]:
    """
    Given {ticker: DataFrame}, return a list of dicts (one per uptrend stock)
    sorted by trend_score desc.
    """
    results = []
    for ticker, df in stock_data.items():
        try:
            info = classify_trend(df)
            info["ticker"] = ticker
            results.append(info)
        except Exception as e:
            pass

    # Sort: uptrend first, then by score
    results.sort(key=lambda x: x["trend_score"], reverse=True)
    return results


def build_summary_table(trend_list: list[dict]) -> pd.DataFrame:
    """Convert trend list → DataFrame for display."""
    rows = []
    for t in trend_list:
        rows.append({
            "Ticker":         t["ticker"],
            "Trend":          t["trend_label"],
            "Score":          t["trend_score"],
            "Price (₹)":      t["current_price"],
            "RSI":            t["rsi"],
            "ADX":            t["adx"],
            "Vol Ratio":      t["vol_ratio"],
            "20D Return %":   t["change_20d_pct"],
            "vs SMA200 %":    t["pct_from_sma200"],
            "MACD Bullish":   "✓" if t["macd_bullish"] else "✗",
            "Golden Cross":   "✓" if t["golden_cross"] else "✗",
        })
    return pd.DataFrame(rows)
