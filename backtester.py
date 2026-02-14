"""
backtester.py – 5 strategies × recent-data backtesting engine.
★ Enforces STRICT 2:1 Risk:Reward on every trade.

Exit logic per trade:
  T1 (1:1) → exit 50% of position, move stop to breakeven
  T2 (2:1) → exit remaining 50%
  Stop     → exit 100% at stop price
  Signal   → exit 100% at market
  Time     → exit 100% after MAX_HOLD_DAYS
"""

import pandas as pd
import numpy as np
from datetime import timedelta
from config import (TOTAL_CAPITAL, CAPITAL_PER_TRADE,
                    BACKTEST_WEEKS, MAX_HOLD_DAYS, STOP_LOSS_ATR_MULT)


# ══════════════════════════════════════════════════════════════════════════════
#  SIGNAL GENERATORS
# ══════════════════════════════════════════════════════════════════════════════

def _sig_trend_following(df):
    e        = df["EMA_9"] > df["EMA_21"]
    cross_up = e & ~e.shift(1).fillna(False)
    entry    = cross_up & (df["ADX"] > 22) & (df["Close"] > df["SMA_50"])
    exit_    = df["EMA_9"] < df["EMA_21"]
    return entry.astype(int), exit_.astype(int)

def _sig_mean_reversion(df):
    entry = (df["Close"] <= df["BB_Lower"]) & (df["RSI"] < 35)
    exit_ = (df["Close"] >= df["BB_Mid"]) | (df["RSI"] > 65)
    return entry.astype(int), exit_.astype(int)

def _sig_momentum_breakout(df):
    high20 = df["High"].rolling(20).max().shift(1)
    entry  = (df["Close"] > high20) & (df["Vol_Ratio"] > 1.4) & df["RSI"].between(48, 72)
    exit_  = df["Close"] < df["EMA_21"]
    return entry.astype(int), exit_.astype(int)

def _sig_swing_trading(df):
    near_sup = (df["Low"] <= df["Support"] * 1.015) & (df["Close"] > df["Support"])
    entry    = near_sup & (df["Bullish_Candle"] == 1) & (df["Vol_Ratio"] > 1.1)
    exit_    = df["High"] >= df["Resistance"] * 0.98
    return entry.astype(int), exit_.astype(int)

def _sig_macd_rsi(df):
    macd_cross = (df["MACD"] > df["MACD_Signal"]) & \
                 (df["MACD"].shift(1) <= df["MACD_Signal"].shift(1))
    entry = macd_cross & df["RSI"].between(42, 63) & (df["Close"] > df["SMA_50"])
    exit_ = (df["MACD"] < df["MACD_Signal"]) | (df["RSI"] > 78)
    return entry.astype(int), exit_.astype(int)

STRATEGIES = {
    "Trend Following":    _sig_trend_following,
    "Mean Reversion":     _sig_mean_reversion,
    "Momentum Breakout":  _sig_momentum_breakout,
    "Swing Trading":      _sig_swing_trading,
    "MACD RSI Combo":     _sig_macd_rsi,
}


# ══════════════════════════════════════════════════════════════════════════════
#  CORE ENGINE  (strict 2:1 with partial exit)
# ══════════════════════════════════════════════════════════════════════════════

def _trade_row(strategy, entry_px, exit_px, stop, t1, t2,
               qty, profit, total_capital, entry_date, exit_date,
               hold_days, exit_type):
    invested = max(qty * entry_px, 1)
    return {
        "strategy":      strategy,
        "entry_date":    entry_date.date() if hasattr(entry_date,"date") else entry_date,
        "exit_date":     exit_date.date()  if hasattr(exit_date, "date") else exit_date,
        "entry_price":   round(entry_px, 2),
        "exit_price":    round(exit_px,  2),
        "stop_loss":     round(stop,     2),
        "target_1":      round(t1,       2),
        "target_2":      round(t2,       2),
        "rr_ratio":      "2:1",
        "qty":           qty,
        "invested":      round(qty * entry_px, 2),
        "profit":        round(profit, 2),
        "profit_pct":    round(profit / invested * 100, 2),
        "profit_on_cap": round(profit / total_capital * 100, 2),
        "hold_days":     hold_days,
        "exit_type":     exit_type,
        "result":        "WIN" if profit >= 0 else "LOSS",
    }


def _backtest_one(strategy_name, sig_fn, df, recent_start_date,
                   total_capital, capital_per_trade):
    try:
        entry_sig, exit_sig = sig_fn(df)
    except Exception:
        return None

    recent_mask = df.index >= recent_start_date
    capital     = float(total_capital)
    position    = None
    trades      = []
    equity      = []

    for i, (date, row) in enumerate(df.iterrows()):
        price = float(row["Close"])
        atr   = float(row.get("ATR", price * 0.02))
        atr   = atr if pd.notna(atr) and atr > 0 else price * 0.02

        # Equity snapshot
        pos_value = position["qty_remaining"] * price if position else 0
        equity.append({"date": date, "equity": capital + pos_value})

        if not recent_mask[i]:
            continue

        # ── EXIT LOGIC ────────────────────────────────────────────────────
        if position:
            ep        = position["entry_px"]
            stop      = position["stop"]
            t1        = position["t1"]
            t2        = position["t2"]
            qty_full  = position["qty_full"]
            qty_rem   = position["qty_remaining"]
            hold_days = (date - position["entry_date"]).days

            # T1 partial exit (only once)
            if not position["t1_hit"] and price >= t1:
                half     = max(1, qty_full // 2)
                profit_h = (t1 - ep) * half
                capital += half * t1
                trades.append(_trade_row(strategy_name, ep, t1, stop, t1, t2,
                                         half, profit_h, total_capital,
                                         position["entry_date"], date,
                                         hold_days, "T1 Hit (50%)"))
                position["qty_remaining"] = qty_rem - half
                position["t1_hit"]        = True
                position["stop"]          = ep     # move stop to breakeven
                if position["qty_remaining"] <= 0:
                    position = None
                continue

            if position is None:
                pass
            elif price <= position["stop"]:
                lbl    = "Breakeven Stop" if position["t1_hit"] else "Stop Loss"
                profit = (position["stop"] - ep) * qty_rem
                capital += qty_rem * position["stop"]
                trades.append(_trade_row(strategy_name, ep, position["stop"],
                                         stop, t1, t2, qty_rem, profit,
                                         total_capital, position["entry_date"],
                                         date, hold_days, lbl))
                position = None

            elif price >= t2:
                profit = (t2 - ep) * qty_rem
                capital += qty_rem * t2
                trades.append(_trade_row(strategy_name, ep, t2, stop, t1, t2,
                                         qty_rem, profit, total_capital,
                                         position["entry_date"], date,
                                         hold_days, "T2 Hit (2:1)"))
                position = None

            elif exit_sig.iloc[i] or hold_days >= MAX_HOLD_DAYS:
                lbl    = "Signal Exit" if exit_sig.iloc[i] else "Time Exit"
                profit = (price - ep) * qty_rem
                capital += qty_rem * price
                trades.append(_trade_row(strategy_name, ep, price, stop, t1, t2,
                                         qty_rem, profit, total_capital,
                                         position["entry_date"], date,
                                         hold_days, lbl))
                position = None

        # ── ENTRY LOGIC ───────────────────────────────────────────────────
        if position is None and entry_sig.iloc[i]:
            risk = STOP_LOSS_ATR_MULT * atr
            if risk <= 0:
                continue
            stop = round(price - risk, 2)
            t1   = round(price + 1.0 * risk, 2)
            t2   = round(price + 2.0 * risk, 2)   # ★ strict 2:1
            qty  = int(capital_per_trade / price)
            if qty > 0 and qty * price <= capital:
                capital -= qty * price
                position = {
                    "entry_date":    date,
                    "entry_px":      price,
                    "stop":          stop,
                    "t1":            t1,
                    "t2":            t2,
                    "qty_full":      qty,
                    "qty_remaining": qty,
                    "t1_hit":        False,
                }

    # Force-close at period end
    if position:
        last_px = float(df["Close"].iloc[-1])
        profit  = (last_px - position["entry_px"]) * position["qty_remaining"]
        capital += position["qty_remaining"] * last_px
        trades.append(_trade_row(
            strategy_name, position["entry_px"], last_px,
            position["stop"], position["t1"], position["t2"],
            position["qty_remaining"], profit, total_capital,
            position["entry_date"], df.index[-1],
            (df.index[-1] - position["entry_date"]).days, "Period End"))

    if not trades:
        return None

    trades_df     = pd.DataFrame(trades)
    wins          = trades_df[trades_df["result"] == "WIN"]
    losses        = trades_df[trades_df["result"] == "LOSS"]
    total_profit  = trades_df["profit"].sum()
    win_rate      = len(wins) / len(trades_df) * 100
    avg_win       = wins["profit"].mean()   if len(wins)   > 0 else 0
    avg_loss      = losses["profit"].mean() if len(losses) > 0 else 0
    gross_win     = wins["profit"].sum()
    gross_loss    = abs(losses["profit"].sum())
    pf            = gross_win / gross_loss if gross_loss > 0 else (99 if gross_win > 0 else 0)

    eq_s          = pd.Series([e["equity"] for e in equity])
    max_dd        = ((eq_s - eq_s.expanding().max()) / eq_s.expanding().max()).min() * 100

    days          = BACKTEST_WEEKS * 7
    ann           = (total_profit / total_capital * 100) * (365/days) if days else 0
    breakeven_wr  = round(100 / (1 + 2.0), 1)   # 33.3%
    ev            = (win_rate/100 * abs(avg_win)) - ((1-win_rate/100) * abs(avg_loss))

    return {
        "strategy":           strategy_name,
        "rr_ratio":           "2:1 (Strict)",
        "total_trades":       len(trades_df),
        "wins":               len(wins),
        "losses":             len(losses),
        "win_rate":           round(win_rate, 1),
        "breakeven_win_rate": breakeven_wr,
        "above_breakeven":    win_rate > breakeven_wr,
        "total_profit":       round(total_profit, 2),
        "total_return_pct":   round(total_profit / total_capital * 100, 2),
        "annualised_return":  round(ann, 1),
        "avg_win":            round(avg_win,  2),
        "avg_loss":           round(avg_loss, 2),
        "profit_factor":      round(pf, 2),
        "expected_value":     round(ev, 2),
        "max_drawdown":       round(max_dd, 2),
        "best_trade_pct":     round(trades_df["profit_pct"].max(), 2),
        "worst_trade_pct":    round(trades_df["profit_pct"].min(), 2),
        "avg_hold_days":      round(trades_df["hold_days"].mean(), 1),
        "target_1_hit_pct":   round((trades_df["exit_type"]=="T1 Hit (50%)").mean()*100,1),
        "target_2_hit_pct":   round((trades_df["exit_type"]=="T2 Hit (2:1)").mean()*100,1),
        "stop_hit_pct":       round((trades_df["exit_type"]=="Stop Loss").mean()*100,1),
        "trades_df":          trades_df,
        "equity_curve":       pd.DataFrame(equity),
        "recommendation":     _recommend(win_rate, pf, total_profit),
    }


def _recommend(win_rate, pf, profit):
    if   win_rate >= 55 and pf >= 1.8 and profit > 0: return "⭐ STRONG BUY"
    elif win_rate >= 40 and pf >= 1.3 and profit > 0: return "✅ BUY"
    elif profit > 0:                                    return "🟡 WATCH"
    else:                                               return "❌ SKIP"


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def backtest_ticker(df, total_capital=TOTAL_CAPITAL,
                    capital_per_trade=CAPITAL_PER_TRADE,
                    weeks_back=BACKTEST_WEEKS):
    recent_start = df.index[-1] - timedelta(weeks=weeks_back)
    return {
        name: r
        for name, fn in STRATEGIES.items()
        if (r := _backtest_one(name, fn, df, recent_start,
                                total_capital, capital_per_trade))
    }

def best_strategy(results):
    if not results: return None
    order = {"⭐ STRONG BUY":4,"✅ BUY":3,"🟡 WATCH":2,"❌ SKIP":1}
    return max(results.values(),
               key=lambda r:(order.get(r["recommendation"],0), r["total_return_pct"]))

def summary_table(results):
    rows = [{
        "Strategy":         r["strategy"],
        "R:R":              r["rr_ratio"],
        "Trades":           r["total_trades"],
        "Win Rate %":       r["win_rate"],
        "Break-even WR":    f"{r['breakeven_win_rate']}%",
        "Profitable?":      "✅" if r["above_breakeven"] else "❌",
        "Profit (₹)":       r["total_profit"],
        "Return %":         r["total_return_pct"],
        "Annualised %":     r["annualised_return"],
        "Profit Factor":    r["profit_factor"],
        "Exp Value (₹)":    r["expected_value"],
        "Max DD %":         r["max_drawdown"],
        "T1 Hit %":         r["target_1_hit_pct"],
        "T2 Hit %":         r["target_2_hit_pct"],
        "Recommendation":   r["recommendation"],
    } for r in results.values()]
    return pd.DataFrame(rows).sort_values("Return %", ascending=False).reset_index(drop=True)

def expected_value_table(win_rates=(35,40,45,50,55,60,65),
                          rr=2.0, risk_per_trade=500):
    """EV sensitivity table at different win rates with strict 2:1 R:R."""
    rows = []
    for wr in win_rates:
        wp = wr/100
        ev = wp*(rr*risk_per_trade) - (1-wp)*risk_per_trade
        rows.append({
            "Win Rate %":    wr,
            "R:R":           f"{rr}:1",
            "Break-even WR": "33.3%",
            "EV per Trade (₹)": round(ev,2),
            "EV 10 Trades (₹)": round(ev*10,2),
            "EV 20 Trades (₹)": round(ev*20,2),
            "Profitable?":   "✅ Yes" if ev>0 else "❌ No",
        })
    return pd.DataFrame(rows)
