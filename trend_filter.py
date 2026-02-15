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


# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY SUITABILITY FILTER  (v1.5)
# ══════════════════════════════════════════════════════════════════════════════

STRATEGY_LABELS = {
    "swing":       "🔄 Swing",
    "momentum":    "🚀 Momentum",
    "breakout":    "💥 Breakout",
    "mean_revert": "↩️ Mean Revert",
    "none":        "—",
}

STRATEGY_DESCRIPTIONS = {
    "swing":       "Hold 3–10 days. Enters near support after a pullback in an uptrend. Needs ADX 20+, RSI 40–60, price near SMA20.",
    "momentum":    "Ride strong trends. Strong ADX 30+, RSI 55–70, price above all MAs, high volume surge.",
    "breakout":    "Buy on price breaking resistance with volume. Bollinger squeeze, vol ratio 1.5×+, ADX rising.",
    "mean_revert": "Buy dips in range-bound stocks. RSI < 35, price near lower BB, ADX < 20.",
}


def score_strategies(info: dict) -> dict:
    """
    Given a trend dict from classify_trend(), return strategy suitability scores.

    Each strategy gets a score 0-100. The best strategy is tagged on the stock.
    Returns: {"best": "swing", "scores": {"swing": 85, ...}, "label": "🔄 Swing"}
    """
    rsi      = info.get("rsi") or 50
    adx      = info.get("adx") or 0
    vr       = info.get("vol_ratio") or 0
    bb_width = info.get("bb_width") or 0          # as percentage
    p20      = info.get("pct_from_sma20") or 0    # % above/below SMA20
    p50      = info.get("pct_from_sma50") or 0
    p200     = info.get("pct_from_sma200") or 0
    macd_b   = info.get("macd_bullish", False)
    gc       = info.get("golden_cross", False)
    pa200    = info.get("price_above_sma200", False)
    pa50     = info.get("price_above_sma50", False)
    ret_20   = info.get("change_20d_pct") or 0

    # ── SWING TRADING ─────────────────────────────────────────────────────────
    # Ideal: uptrend (above SMA200+50), pulled back to SMA20 area, RSI 40-60,
    #        ADX 20-35 (trending but not exhausted), modest volume
    swing = 0
    if pa200:            swing += 25
    if pa50:             swing += 20
    if 40 <= rsi <= 62:  swing += 20
    if 20 <= adx <= 40:  swing += 20
    if -5 <= p20 <= 3:   swing += 10   # near SMA20 (slight pullback)
    if macd_b:           swing += 5

    # ── MOMENTUM ──────────────────────────────────────────────────────────────
    # Ideal: strong trend, RSI 55-72, all MAs stacked, high volume, recent run
    momentum = 0
    if pa200:            momentum += 15
    if pa50:             momentum += 15
    if gc:               momentum += 15
    if 55 <= rsi <= 72:  momentum += 20
    if adx >= 30:        momentum += 20
    if vr >= 1.5:        momentum += 10
    if ret_20 >= 5:      momentum += 5

    # ── BREAKOUT ──────────────────────────────────────────────────────────────
    # Ideal: BB squeeze (narrow), volume surging, ADX rising from low base,
    #        price near or just above resistance
    breakout = 0
    if bb_width < 8:     breakout += 25   # squeeze (narrow bands)
    elif bb_width < 15:  breakout += 10
    if vr >= 1.5:        breakout += 30
    elif vr >= 1.2:      breakout += 15
    if 20 <= adx <= 35:  breakout += 20
    if p20 > 0:          breakout += 15   # above SMA20 (already breaking)
    if macd_b:           breakout += 10

    # ── MEAN REVERSION ────────────────────────────────────────────────────────
    # Ideal: oversold RSI, price below lower BB, ADX low (range-bound),
    #        not in strong downtrend (still above SMA200 ideally)
    mean_rev = 0
    if rsi <= 35:        mean_rev += 35
    elif rsi <= 45:      mean_rev += 15
    if adx < 20:         mean_rev += 30   # range-bound
    elif adx < 25:       mean_rev += 10
    if p20 < -5:         mean_rev += 20   # below SMA20
    if pa200:            mean_rev += 15   # still above LT trend — safer dip buy

    scores = {
        "swing":       min(swing,    100),
        "momentum":    min(momentum, 100),
        "breakout":    min(breakout, 100),
        "mean_revert": min(mean_rev, 100),
    }

    # Best strategy = highest score, but only if > 40 (otherwise "none")
    best_key   = max(scores, key=scores.get)
    best_score = scores[best_key]

    if best_score < 40:
        best_key = "none"

    return {
        "best":    best_key,
        "label":   STRATEGY_LABELS[best_key],
        "scores":  scores,
    }


def filter_uptrend_stocks(stock_data: dict) -> list[dict]:
    """
    Given {ticker: DataFrame}, return a list of dicts (one per stock)
    sorted by trend_score desc.  Each dict now includes strategy suitability.
    """
    results = []
    for ticker, df in stock_data.items():
        try:
            info = classify_trend(df)
            info["ticker"] = ticker
            strat = score_strategies(info)
            info["best_strategy"]      = strat["best"]
            info["strategy_label"]     = strat["label"]
            info["strategy_scores"]    = strat["scores"]
            results.append(info)
        except Exception:
            pass

    results.sort(key=lambda x: x["trend_score"], reverse=True)
    return results


def build_summary_table(trend_list: list[dict]) -> pd.DataFrame:
    """Convert trend list → DataFrame for display. Includes strategy column."""
    rows = []
    for t in trend_list:
        rows.append({
            "Ticker":         t["ticker"],
            "Best For":       t.get("strategy_label", "—"),
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


def get_strategy_stocks(trend_list: list[dict], strategy: str) -> list[dict]:
    """
    Filter trend_list to stocks best suited for a given strategy.
    strategy: "swing" | "momentum" | "breakout" | "mean_revert" | "all"
    Returns sorted by that strategy's score descending.
    """
    if strategy == "all":
        return trend_list
    filtered = [t for t in trend_list if t.get("best_strategy") == strategy]
    return sorted(filtered,
                  key=lambda x: x.get("strategy_scores", {}).get(strategy, 0),
                  reverse=True)
