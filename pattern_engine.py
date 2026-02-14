"""
pattern_engine.py
Finds historical windows that look similar to the current price pattern
and reports what the stock did AFTER each match.
"""

import numpy as np
import pandas as pd
from config import PATTERN_WINDOW_DAYS, PATTERN_TOP_N, PATTERN_MIN_SCORE, BACKTEST_WEEKS
from datetime import timedelta


def _normalise(series: pd.Series) -> np.ndarray:
    """Normalise a price series to [0, 1] for shape comparison."""
    mn, mx = series.min(), series.max()
    if mx == mn:
        return np.zeros(len(series))
    return ((series - mn) / (mx - mn)).values


def _similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity scaled to 0-100."""
    dot   = np.dot(a, b)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return round(max(0.0, dot / denom) * 100, 1)


def find_similar_patterns(df: pd.DataFrame,
                           window: int = PATTERN_WINDOW_DAYS,
                           top_n: int = PATTERN_TOP_N,
                           min_score: float = PATTERN_MIN_SCORE,
                           backtest_weeks: int = BACKTEST_WEEKS) -> list[dict]:
    """
    Takes the FULL history DataFrame (including warm-up period).
    The "current" pattern = the last `window` rows of the RECENT section.
    Scans the earlier history for similar windows.

    Returns list of dicts:
      date_start, date_end, similarity_score,
      outcome_pct (% move in next `window` days),
      outcome_label, chart_data (list of close prices)
    """
    prices = df["Close"]
    n      = len(prices)

    # Cutoff: data before the backtest period is "historical"
    recent_cutoff = df.index[-1] - timedelta(weeks=backtest_weeks)
    hist_mask     = df.index < recent_cutoff
    hist_df       = df[hist_mask]

    if len(hist_df) < window * 2 + window:   # need room for outcome window
        return []

    # Current pattern = last `window` rows of full df
    current_window = _normalise(prices.iloc[-window:])

    matches = []
    h_prices = hist_df["Close"]
    h_idx    = hist_df.index

    for i in range(len(h_prices) - window * 2):
        candidate = _normalise(h_prices.iloc[i: i + window])
        score     = _similarity(current_window, candidate)

        if score < min_score:
            continue

        # What happened in the NEXT `window` days?
        future_start = i + window
        future_end   = future_start + window
        if future_end > len(h_prices):
            continue

        entry_price   = h_prices.iloc[future_start]
        exit_price    = h_prices.iloc[future_end - 1]
        outcome_pct   = (exit_price - entry_price) / entry_price * 100

        outcome_label = (
            "📈 Strong Gain" if outcome_pct  >  5 else
            "🟢 Moderate Gain" if outcome_pct > 0 else
            "🔴 Loss"
        )

        matches.append({
            "date_start":     h_idx[i].strftime("%d %b %Y"),
            "date_end":       h_idx[i + window - 1].strftime("%d %b %Y"),
            "similarity_pct": score,
            "outcome_pct":    round(outcome_pct, 2),
            "outcome_days":   window,
            "outcome_label":  outcome_label,
            "entry_price":    round(entry_price, 2),
            "exit_price":     round(exit_price, 2),
            # Normalised pattern for chart overlay
            "pattern_norm":   candidate.tolist(),
            "future_norm":    _normalise(h_prices.iloc[future_start:future_end]).tolist(),
        })

    if not matches:
        return []

    # Deduplicate overlapping windows (keep highest score per 5-day band)
    matches.sort(key=lambda x: -x["similarity_pct"])
    kept, used_starts = [], set()
    for m in matches:
        # Approximate start index
        band = m["date_start"][:7]   # year-month bucket
        if band not in used_starts:
            kept.append(m)
            used_starts.add(band)
        if len(kept) == top_n:
            break

    return kept


def pattern_summary(matches: list[dict]) -> dict:
    """Aggregate statistics across all matched patterns."""
    if not matches:
        return {}

    outcomes = [m["outcome_pct"] for m in matches]
    wins     = [o for o in outcomes if o > 0]
    return {
        "avg_outcome_pct":   round(np.mean(outcomes), 2),
        "win_rate_pct":      round(len(wins) / len(outcomes) * 100, 1),
        "best_outcome_pct":  round(max(outcomes), 2),
        "worst_outcome_pct": round(min(outcomes), 2),
        "num_matches":       len(matches),
        "avg_similarity":    round(np.mean([m["similarity_pct"] for m in matches]), 1),
        "confidence":        (
            "HIGH"   if len(wins) / len(outcomes) >= 0.67 else
            "MEDIUM" if len(wins) / len(outcomes) >= 0.50 else
            "LOW"
        ),
    }
