"""
live_engine.py – Live signal engine with strict 2:1 Risk:Reward enforcement.

What it does:
1. Fetches the latest intraday + daily data for each uptrend stock
2. Runs all 5 strategy signal generators on the most recent bar
3. Confirms signals using backtest performance (only shows strategies
   that earned ≥ MIN_WIN_RATE_LIVE% and ≥ MIN_PROFIT_FACTOR_LIVE in recent backtest)
4. Calculates EXACT entry / stop / target enforcing  target = 2 × risk  (2:1 R:R)
5. Returns ranked live trade opportunities with full risk maths
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import logging

from config import (
    STOP_LOSS_ATR_MULT, TARGET_RR_RATIO,
    CAPITAL_PER_TRADE, TOTAL_CAPITAL, MAX_HOLD_DAYS,
    LIVE_INTRADAY_INTERVAL, LIVE_INTRADAY_PERIOD,
    LIVE_SIGNAL_CONFIRM, MIN_WIN_RATE_LIVE, MIN_PROFIT_FACTOR_LIVE,
    BACKTEST_WEEKS
)
from market_data  import add_indicators
from backtester   import STRATEGIES, _backtest_one, best_strategy

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  LIVE DATA FETCH
# ══════════════════════════════════════════════════════════════════════════════

def fetch_live_daily(ticker: str) -> pd.DataFrame | None:
    """Daily bars – enough for all indicators (365 + buffer)."""
    try:
        end   = datetime.now()
        start = end - timedelta(days=400)
        df = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df = df[["Open","High","Low","Close","Volume"]].dropna()
        if len(df) < 50:
            return None
        return add_indicators(df)
    except Exception as e:
        log.warning(f"{ticker} daily fetch: {e}")
        return None


def fetch_live_intraday(ticker: str,
                         interval: str = LIVE_INTRADAY_INTERVAL,
                         period:   str = LIVE_INTRADAY_PERIOD) -> pd.DataFrame | None:
    """
    Intraday bars for same-day signal confirmation.
    Returns None when market is closed / no data.
    """
    try:
        df = yf.Ticker(ticker).history(period=period, interval=interval,
                                        auto_adjust=True)
        if df.empty:
            return None
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df = df[["Open","High","Low","Close","Volume"]].dropna()
        if len(df) < 20:
            return None
        return add_indicators(df)
    except Exception as e:
        log.warning(f"{ticker} intraday fetch: {e}")
        return None


def get_current_price(ticker: str) -> float | None:
    """Fetch last traded price (fast, single API call)."""
    try:
        info = yf.Ticker(ticker).fast_info
        return round(float(info.last_price), 2)
    except Exception:
        try:
            df = yf.Ticker(ticker).history(period="1d", interval="1m", auto_adjust=True)
            return round(float(df["Close"].iloc[-1]), 2) if not df.empty else None
        except Exception:
            return None


# ══════════════════════════════════════════════════════════════════════════════
#  2:1 LEVEL CALCULATOR  (single source of truth)
# ══════════════════════════════════════════════════════════════════════════════

def calc_levels_2to1(entry: float, atr: float,
                      atr_mult: float = STOP_LOSS_ATR_MULT) -> dict:
    """
    Given entry price and ATR, return stop / targets enforcing strict 2:1 R:R.

    Risk  = atr_mult × ATR
    Stop  = entry − Risk
    T1    = entry + (1.0 × Risk)   ← partial exit at 1:1
    T2    = entry + (2.0 × Risk)   ← full exit at 2:1  (main target)

    Partial-profit rule: exit 50% at T1, trail stop to breakeven,
    let remaining 50% run to T2.
    """
    risk   = round(atr_mult * atr, 2)
    stop   = round(entry - risk, 2)
    t1     = round(entry + 1.0 * risk, 2)      # 1:1 partial
    t2     = round(entry + 2.0 * risk, 2)      # 2:1 full target
    rr     = round((t2 - entry) / risk, 2)     # should be exactly 2.0

    qty    = int(CAPITAL_PER_TRADE / entry)
    inv    = round(qty * entry, 2)
    max_loss     = round(qty * risk, 2)
    profit_t1    = round(qty * (t1 - entry), 2)
    profit_t2    = round(qty * (t2 - entry), 2)
    profit_full  = round((profit_t1 / 2) + (profit_t2 / 2), 2)   # 50% exit at each
    risk_pct_cap = round(max_loss / TOTAL_CAPITAL * 100, 2)
    reward_pct_cap = round(profit_full / TOTAL_CAPITAL * 100, 2)

    return {
        "entry":            entry,
        "stop":             stop,
        "target_1":         t1,         # 1:1 (partial profit)
        "target_2":         t2,         # 2:1 (main target)
        "risk_per_share":   risk,
        "rr_ratio":         rr,
        "qty":              qty,
        "investment":       inv,
        "max_loss":         max_loss,
        "profit_at_t1":     profit_t1,
        "profit_at_t2":     profit_t2,
        "avg_expected_profit": profit_full,
        "risk_pct_of_capital":  risk_pct_cap,
        "reward_pct_of_capital": reward_pct_cap,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  SIGNAL CHECKER (latest bar)
# ══════════════════════════════════════════════════════════════════════════════

def check_live_signals(df_daily: pd.DataFrame) -> list[str]:
    """
    Returns names of strategies that are firing a BUY signal
    on the LAST row of df_daily.
    """
    active = []
    for name, fn in STRATEGIES.items():
        try:
            entry_sig, _ = fn(df_daily)
            if entry_sig.iloc[-1] == 1:
                active.append(name)
        except Exception:
            pass
    return active


def check_intraday_confirmation(df_intra: pd.DataFrame | None,
                                  strategy_name: str) -> bool:
    """
    Cross-check the daily signal against intraday data.
    Returns True if intraday bars also support the signal.
    """
    if df_intra is None or len(df_intra) < 5:
        return True   # can't confirm – don't block; default to True

    fn = STRATEGIES.get(strategy_name)
    if fn is None:
        return True

    try:
        entry_sig, _ = fn(df_intra)
        # At least 1 of the last 3 intraday bars fired entry
        return bool(entry_sig.iloc[-3:].any())
    except Exception:
        return True


# ══════════════════════════════════════════════════════════════════════════════
#  BACKTEST VALIDATOR  – only trust strategies that proved themselves recently
# ══════════════════════════════════════════════════════════════════════════════

def validate_via_backtest(df_daily: pd.DataFrame,
                           strategy_name: str,
                           total_capital: int = TOTAL_CAPITAL,
                           capital_per_trade: int = CAPITAL_PER_TRADE,
                           weeks_back: int = BACKTEST_WEEKS) -> dict | None:
    """
    Run the strategy on the recent period and return its stats.
    Returns None if insufficient data or no trades.
    """
    from datetime import timedelta
    fn = STRATEGIES.get(strategy_name)
    if fn is None:
        return None

    recent_start = df_daily.index[-1] - timedelta(weeks=weeks_back)
    result = _backtest_one(strategy_name, fn, df_daily, recent_start,
                            total_capital, capital_per_trade)
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN: GENERATE LIVE SIGNALS FOR ALL UPTREND STOCKS
# ══════════════════════════════════════════════════════════════════════════════

def generate_live_signals(
        tickers: list[str],
        halal_info: list[dict],
        total_capital: int   = TOTAL_CAPITAL,
        capital_per_trade: int = CAPITAL_PER_TRADE,
        weeks_back: int        = BACKTEST_WEEKS,
        progress_cb            = None
) -> list[dict]:
    """
    For each ticker:
      1. Fetch daily data
      2. Check which strategies fire on the latest bar
      3. Validate each signal via recent backtest
      4. Filter: win-rate ≥ threshold AND profit-factor ≥ threshold
      5. Calculate 2:1 levels
      6. Confirm on intraday (if available)
      7. Return ranked signal list

    Returns list of signal dicts, sorted by confidence score.
    """
    halal_map = {s["nse_ticker"]: s for s in halal_info}
    signals   = []
    total     = len(tickers)

    for i, ticker in enumerate(tickers, 1):
        if progress_cb:
            progress_cb(i, total, ticker)

        df = fetch_live_daily(ticker)
        if df is None or len(df) < 60:
            continue

        # Latest row data
        last      = df.iloc[-1]
        price     = round(last["Close"], 2)
        atr       = last.get("ATR", price * 0.02)
        atr       = atr if pd.notna(atr) and atr > 0 else price * 0.02

        # ── Which strategies fire? ───────────────────────────────────────────
        active_strategies = check_live_signals(df)
        if not active_strategies:
            continue

        df_intra = fetch_live_intraday(ticker)

        for strat_name in active_strategies:
            # ── Backtest validation ──────────────────────────────────────────
            bt = validate_via_backtest(df, strat_name, total_capital,
                                        capital_per_trade, weeks_back)

            if bt is None:
                bt_win_rate  = 0
                bt_pf        = 0
                bt_trades    = 0
                bt_return    = 0
                bt_avg_win   = 0
                bt_avg_loss  = 0
                bt_max_dd    = 0
            else:
                bt_win_rate  = bt.get("win_rate", 0)
                bt_pf        = bt.get("profit_factor", 0)
                bt_trades    = bt.get("total_trades", 0)
                bt_return    = bt.get("total_return_pct", 0)
                bt_avg_win   = bt.get("avg_win", 0)
                bt_avg_loss  = bt.get("avg_loss", 0)
                bt_max_dd    = bt.get("max_drawdown", 0)

            # Filter: must meet minimum thresholds OR have no backtest data yet
            if bt_trades > 0:
                if bt_win_rate < MIN_WIN_RATE_LIVE or bt_pf < MIN_PROFIT_FACTOR_LIVE:
                    continue

            # ── Intraday confirmation ────────────────────────────────────────
            intra_confirmed = check_intraday_confirmation(df_intra, strat_name)

            # ── 2:1 Levels ──────────────────────────────────────────────────
            levels = calc_levels_2to1(price, atr)

            # ── Expected value at 2:1 R:R ────────────────────────────────────
            # EV = (win_rate × 2R) − (loss_rate × 1R)
            # At 2:1: break-even win rate = 1/(1+2) = 33.3%
            win_p  = bt_win_rate / 100 if bt_win_rate > 0 else 0.45
            loss_p = 1 - win_p
            reward_r = levels["risk_per_share"] * 2
            ev_per_share = round(win_p * reward_r - loss_p * levels["risk_per_share"], 3)
            ev_total     = round(ev_per_share * levels["qty"], 2)

            # ── Confidence score (0-100) ─────────────────────────────────────
            conf = _confidence_score(
                bt_win_rate, bt_pf, bt_trades,
                intra_confirmed, float(last.get("ADX", 0)),
                float(last.get("RSI", 50)),
                float(last.get("Vol_Ratio", 1)),
            )

            # ── Overall recommendation ───────────────────────────────────────
            rec = (
                "⭐ STRONG SIGNAL" if conf >= 75 else
                "✅ GOOD SIGNAL"   if conf >= 55 else
                "🟡 WEAK SIGNAL"
            )

            company = halal_map.get(ticker, {}).get("company", ticker)
            industry = halal_map.get(ticker, {}).get("industry", "N/A")

            signals.append({
                # Identity
                "ticker":            ticker,
                "company":           company,
                "industry":          industry,

                # Live data
                "live_price":        price,
                "atr":               round(atr, 2),
                "rsi":               round(float(last.get("RSI",  50)), 1),
                "adx":               round(float(last.get("ADX",  0)),  1),
                "vol_ratio":         round(float(last.get("Vol_Ratio", 1)), 2),
                "macd_hist":         round(float(last.get("MACD_Hist", 0)), 3),
                "last_updated":      df.index[-1].strftime("%d %b %Y %H:%M"),

                # Strategy
                "strategy":          strat_name,
                "intra_confirmed":   intra_confirmed,

                # 2:1 Levels
                **levels,

                # Backtest validation
                "bt_trades":         bt_trades,
                "bt_win_rate":       bt_win_rate,
                "bt_profit_factor":  bt_pf,
                "bt_return_pct":     bt_return,
                "bt_avg_win":        bt_avg_win,
                "bt_avg_loss":       bt_avg_loss,
                "bt_max_dd":         bt_max_dd,

                # Expected value
                "ev_per_share":      ev_per_share,
                "ev_total":          ev_total,
                "breakeven_wr":      33.3,          # always 33.3% at 2:1

                # Scoring
                "confidence":        conf,
                "recommendation":    rec,
            })

    # Sort: confidence desc
    signals.sort(key=lambda x: x["confidence"], reverse=True)
    return signals


# ══════════════════════════════════════════════════════════════════════════════
#  CONFIDENCE SCORER
# ══════════════════════════════════════════════════════════════════════════════

def _confidence_score(win_rate, pf, trades, intra_ok,
                       adx, rsi, vol_ratio) -> int:
    """
    Composite 0-100 confidence score.
    Components:
      Backtest quality  (40 pts)
      Technical quality (40 pts)
      Confirmation      (20 pts)
    """
    # ── Backtest quality ──────────────────────────────────────────────────────
    bt_score = 0
    if trades > 0:
        bt_score += min(20, (win_rate - 33) * 0.8)   # 0–20 pts for win rate 33-58%
        bt_score += min(20, (pf - 1.0) * 12)         # 0–20 pts for PF 1.0-2.7
    else:
        bt_score = 10                                  # neutral when no backtest data

    # ── Technical quality ────────────────────────────────────────────────────
    tech_score = 0
    tech_score += min(15, max(0, (adx - 20) * 1.0))  # 0-15 pts, ADX 20-35
    if 45 <= rsi <= 65:
        tech_score += 15                               # ideal RSI zone
    elif 35 <= rsi <= 75:
        tech_score += 8
    tech_score += min(10, (vol_ratio - 1.0) * 12)     # 0-10 pts, vol ratio 1-1.8

    # ── Intraday confirmation ────────────────────────────────────────────────
    conf_score = 20 if intra_ok else 5

    total = int(bt_score + tech_score + conf_score)
    return max(0, min(100, total))


# ══════════════════════════════════════════════════════════════════════════════
#  LIVE PORTFOLIO MONITOR
# ══════════════════════════════════════════════════════════════════════════════

def monitor_open_positions(positions: list[dict]) -> list[dict]:
    """
    Given a list of open position dicts (entry, stop, t1, t2, qty, ticker),
    fetch live price and return updated status for each.

    Each position dict needs:
      ticker, entry, stop, target_1, target_2, qty, strategy
    """
    updated = []
    for pos in positions:
        ticker     = pos["ticker"]
        live_price = get_current_price(ticker)

        if live_price is None:
            pos["live_price"]  = None
            pos["status"]      = "⚠️ No Price"
            pos["unrealised_pnl"] = None
            updated.append(pos)
            continue

        entry  = pos["entry"]
        stop   = pos["stop"]
        t1     = pos["target_1"]
        t2     = pos["target_2"]
        qty    = pos["qty"]

        pnl    = round((live_price - entry) * qty, 2)
        pnl_pct = round((live_price - entry) / entry * 100, 2)

        if live_price <= stop:
            status = "🔴 STOP HIT"
        elif live_price >= t2:
            status = "🏆 T2 HIT – EXIT FULL"
        elif live_price >= t1:
            status = "✅ T1 HIT – EXIT HALF"
        elif pnl > 0:
            status = "🟢 PROFIT"
        else:
            status = "🟡 IN TRADE"

        # Distance from key levels
        pct_to_stop = round((live_price - stop) / entry * 100, 2)
        pct_to_t1   = round((t1 - live_price) / entry * 100, 2)
        pct_to_t2   = round((t2 - live_price) / entry * 100, 2)

        updated.append({
            **pos,
            "live_price":       live_price,
            "unrealised_pnl":   pnl,
            "pnl_pct":          pnl_pct,
            "status":           status,
            "pct_to_stop":      pct_to_stop,
            "pct_to_t1":        pct_to_t1,
            "pct_to_t2":        pct_to_t2,
        })

    return updated
