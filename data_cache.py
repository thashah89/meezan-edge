"""
data_cache.py – Persistent market data cache for Meezan Edge.

Streamlit Cloud filesystem resets on redeploy, so we use TWO layers:
  Layer 1: st.session_state  – lives for the current browser session
  Layer 2: JSON file          – survives server restarts, downloadable/uploadable

The cache stores the computed trend results (not raw OHLCV — too large).
This is enough to power the entire dashboard without re-fetching.

Cache lifecycle:
  • Refresh Data button    → fetches live data, computes trends, saves cache
  • Every page load        → loads from file if session_state is empty
  • Warning at 14 days     → amber banner in sidebar
  • Expire at 60 days      → red banner + forced refresh prompt
  • User can download cache → restore it after a redeploy
  • User can upload cache  → instantly restores without re-fetching
"""

import json
import os
import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

CACHE_FILE        = "meezan_market_cache.json"
WARN_DAYS         = 14    # show amber warning after this many days
EXPIRE_DAYS       = 60    # show red "please refresh" after this many days
_SS_CACHE_KEY     = "meezan_cache"
_SS_CACHE_DATE    = "meezan_cache_date"


# ══════════════════════════════════════════════════════════════════════════════
#  SAVE
# ══════════════════════════════════════════════════════════════════════════════

def save_cache(market_data: dict, trend_list: list, halal_stocks: list) -> None:
    """
    Save the current dataset to session_state + JSON file.

    market_data: {ticker: DataFrame}  — converted to a compact summary dict
    trend_list:  list of trend dicts
    halal_stocks: list of halal stock dicts
    """
    import streamlit as st

    now = datetime.now(timezone.utc).isoformat()

    # Compact summary from DataFrames (store only latest-row indicators)
    compact_market = {}
    for ticker, df in market_data.items():
        try:
            row = df.iloc[-1]
            compact_market[ticker] = {
                "Close":      float(row["Close"]),
                "RSI":        float(row.get("RSI", 0)),
                "ADX":        float(row.get("ADX", 0)),
                "ATR":        float(row.get("ATR", 0)),
                "Vol_Ratio":  float(row.get("Vol_Ratio", 0)),
                "MACD":       float(row.get("MACD", 0)),
                "MACD_Signal":float(row.get("MACD_Signal", 0)),
                "SMA_20":     float(row.get("SMA_20", 0)),
                "SMA_50":     float(row.get("SMA_50", 0)),
                "SMA_200":    float(row.get("SMA_200", 0)),
                "BB_Width":   float(row.get("BB_Width", 0)),
                "rows":       len(df),
            }
        except Exception:
            pass

    payload = {
        "saved_at":    now,
        "version":     "1.0",
        "ticker_count": len(compact_market),
        "market_summary": compact_market,
        "trend_list":  trend_list,
        "halal_stocks": halal_stocks,
    }

    # Layer 1 — session_state
    st.session_state[_SS_CACHE_KEY]  = payload
    st.session_state[_SS_CACHE_DATE] = now

    # Layer 2 — file (may silently fail on Streamlit Cloud after redeploy)
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(payload, f, default=str)
        log.info(f"Cache saved → {CACHE_FILE}  ({len(compact_market)} tickers)")
    except Exception as e:
        log.warning(f"Cache file write failed (ok on cloud): {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  LOAD
# ══════════════════════════════════════════════════════════════════════════════

def load_cache() -> dict | None:
    """
    Load cache from session_state (priority) or file.
    Returns the payload dict or None if nothing is available.
    """
    import streamlit as st

    # Layer 1 — session_state (fastest)
    if st.session_state.get(_SS_CACHE_KEY):
        return st.session_state[_SS_CACHE_KEY]

    # Layer 2 — file
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE) as f:
                payload = json.load(f)
            # Migrate to session_state
            st.session_state[_SS_CACHE_KEY]  = payload
            st.session_state[_SS_CACHE_DATE] = payload.get("saved_at", "")
            log.info(f"Cache loaded from file: {payload.get('ticker_count',0)} tickers")
            return payload
    except Exception as e:
        log.warning(f"Cache file read failed: {e}")

    return None


# ══════════════════════════════════════════════════════════════════════════════
#  AGE CHECK
# ══════════════════════════════════════════════════════════════════════════════

def cache_age_days(payload: dict) -> float | None:
    """Return how many days old the cache is. None if unknown."""
    try:
        saved_str = payload.get("saved_at", "")
        if not saved_str:
            return None
        saved = datetime.fromisoformat(saved_str)
        if saved.tzinfo is None:
            saved = saved.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - saved).total_seconds() / 86_400
    except Exception:
        return None


def cache_status(payload: dict | None) -> dict:
    """
    Returns a status dict for the sidebar banner:
      {level: "ok"|"warn"|"expired"|"none", message, age_days, saved_at}
    """
    if payload is None:
        return {
            "level":   "none",
            "message": "No data loaded. Click **Refresh Data** to fetch stocks.",
            "age_days": None,
            "saved_at": None,
        }

    age = cache_age_days(payload)
    saved_str = payload.get("saved_at", "")
    try:
        saved_dt  = datetime.fromisoformat(saved_str)
        saved_fmt = saved_dt.strftime("%d %b %Y, %H:%M UTC")
    except Exception:
        saved_fmt = saved_str

    tickers = payload.get("ticker_count", len(payload.get("market_summary", {})))

    if age is None:
        return {"level": "ok", "message": f"Data loaded ({tickers} stocks)",
                "age_days": None, "saved_at": saved_fmt}

    age_label = (
        f"{int(age)} day{'s' if int(age) != 1 else ''}" if age >= 1
        else f"{int(age*24)} hour{'s' if int(age*24) != 1 else ''}"
    )

    if age >= EXPIRE_DAYS:
        return {
            "level":   "expired",
            "message": (f"⚠️ Data is **{age_label} old** — over {EXPIRE_DAYS} days. "
                        f"Please refresh for accurate signals."),
            "age_days": age,
            "saved_at": saved_fmt,
        }
    elif age >= WARN_DAYS:
        return {
            "level":   "warn",
            "message": (f"🕐 Data is **{age_label} old** (last refreshed {saved_fmt}). "
                        f"Consider refreshing before trading."),
            "age_days": age,
            "saved_at": saved_fmt,
        }
    else:
        return {
            "level":   "ok",
            "message": (f"✅ Data fresh — {age_label} old · {tickers} stocks · "
                        f"Last refresh: {saved_fmt}"),
            "age_days": age,
            "saved_at": saved_fmt,
        }


# ══════════════════════════════════════════════════════════════════════════════
#  EXPORT / IMPORT  (for Streamlit download/upload widgets)
# ══════════════════════════════════════════════════════════════════════════════

def export_cache_bytes() -> bytes | None:
    """Return the raw JSON bytes of the current cache for st.download_button."""
    payload = load_cache()
    if payload is None:
        return None
    try:
        return json.dumps(payload, default=str, indent=2).encode("utf-8")
    except Exception:
        return None


def import_cache_bytes(raw: bytes) -> bool:
    """
    Load a previously exported cache from uploaded bytes.
    Returns True on success.
    """
    import streamlit as st
    try:
        payload = json.loads(raw.decode("utf-8"))
        if "trend_list" not in payload or "halal_stocks" not in payload:
            return False
        st.session_state[_SS_CACHE_KEY]  = payload
        st.session_state[_SS_CACHE_DATE] = payload.get("saved_at", "")
        # Also write to file for persistence within this server session
        try:
            with open(CACHE_FILE, "w") as f:
                json.dump(payload, f, default=str)
        except Exception:
            pass
        log.info("Cache imported from uploaded file.")
        return True
    except Exception as e:
        log.error(f"Cache import failed: {e}")
        return False
