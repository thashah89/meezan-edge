"""
Zerodha (Kite) client wrapper for data-only operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
import logging
import pandas as pd
import numpy as np
import requests

try:
    from kiteconnect import KiteConnect
except ImportError:  # pragma: no cover
    KiteConnect = None

from database_schema import get_connection
from utils_indicators import add_indicators
from ml_trainer import MLPredictor
from market_intel_engine import calculate_opportunity_score, determine_strategy_fit

log = logging.getLogger(__name__)


class ZerodhaConfigError(Exception):
    """Raised when Zerodha configuration is missing or invalid."""


@dataclass
class RefreshResult:
    """Result summary for metrics refresh."""

    inserted_or_updated: int
    failed: int
    failures: List[Tuple[str, str]]


class ZerodhaClient:
    """Small data client for Kite APIs. Real order APIs are intentionally not exposed."""
    PRIMARY_STRATEGY = "vwap_pullback"

    def __init__(self, api_key: str, api_secret: str, access_token: Optional[str] = None):
        self.api_key = (api_key or "").strip()
        self.api_secret = (api_secret or "").strip()
        self.access_token = (access_token or "").strip()

        if not self.api_key or self.api_key.startswith("your_"):
            raise ZerodhaConfigError("Missing valid Zerodha api_key in .streamlit/secrets.toml")
        if not self.api_secret or self.api_secret.startswith("your_"):
            raise ZerodhaConfigError("Missing valid Zerodha api_secret in .streamlit/secrets.toml")

        if KiteConnect is None:
            raise ZerodhaConfigError("kiteconnect is not installed. Run: pip install kiteconnect")

        self.kite = KiteConnect(api_key=self.api_key)
        if self.access_token:
            self.kite.set_access_token(self.access_token)
        self.predictor = MLPredictor()
        self._reco_cache: Dict[str, Dict[str, Any]] = {}

    @property
    def is_authenticated(self) -> bool:
        return bool(self.access_token)

    def get_login_url(self) -> str:
        return self.kite.login_url()

    def create_session(self, request_token: str) -> str:
        """Exchange request token for access token."""
        if not request_token:
            raise ValueError("request_token is required")

        session = self.kite.generate_session(request_token, api_secret=self.api_secret)
        token = session.get("access_token", "")
        if not token:
            raise RuntimeError("Kite session did not return access_token")

        self.access_token = token
        self.kite.set_access_token(token)
        return token

    def test_connection(self) -> Dict:
        """Validate access token by fetching profile."""
        if not self.is_authenticated:
            raise ZerodhaConfigError("Zerodha access token is missing. Authenticate first.")
        return self.kite.profile()

    def fetch_quotes(self, symbols: List[str], batch_size: int = 100) -> Dict[str, Dict]:
        """Fetch quotes for NSE symbols in batches to avoid oversized request URIs."""
        if not self.is_authenticated:
            raise ZerodhaConfigError("Zerodha access token is missing. Authenticate first.")
        if not symbols:
            return {}

        out: Dict[str, Dict] = {}
        normalized = [self.normalize_symbol(s) for s in symbols]
        unique_symbols = [s for s in dict.fromkeys(normalized) if s]

        for i in range(0, len(unique_symbols), batch_size):
            batch = unique_symbols[i : i + batch_size]
            instruments = [f"NSE:{s}" for s in batch]
            raw = self.kite.quote(instruments)
            for instrument, payload in raw.items():
                symbol = instrument.split(":", 1)[-1]
                out[symbol] = payload

        return out

    def refresh_latest_metrics(
        self,
        symbols: List[str],
        progress_cb: Optional[Callable[[int, int, str, str], None]] = None,
    ) -> RefreshResult:
        """
        Pull latest quote snapshot and upsert into stock_metrics.
        """
        today = date.today().isoformat()
        instrument_token_by_symbol: Dict[str, int] = {}
        alias_to_tradingsymbol: Dict[str, str] = {}
        resolved_by_input: Dict[str, str] = {}
        try:
            instruments = self.kite.instruments("NSE")
            instrument_token_by_symbol, alias_to_tradingsymbol = self._build_instrument_resolution_maps(instruments)
            for raw_symbol in symbols:
                base_symbol = self.normalize_symbol(raw_symbol)
                resolved = self._resolve_to_tradingsymbol(
                    base_symbol,
                    instrument_token_by_symbol,
                    alias_to_tradingsymbol,
                )
                if resolved:
                    resolved_by_input[base_symbol] = resolved
        except Exception as exc:
            log.warning("Could not preload instruments for indicator enrichment: %s", exc)
        resolved_universe = list({v for v in resolved_by_input.values() if v})
        quotes = self.fetch_quotes(resolved_universe) if resolved_universe else {}

        conn = get_connection()
        cur = conn.cursor()
        updated = 0
        failed = 0
        failures: List[Tuple[str, str]] = []

        total = len(symbols)
        processed = 0

        try:
            for raw_symbol in symbols:
                symbol = self.normalize_symbol(raw_symbol)
                status = "updated"
                if not symbol:
                    failed += 1
                    failures.append((str(raw_symbol), "Invalid symbol"))
                    status = "invalid"
                    processed += 1
                    if progress_cb:
                        progress_cb(processed, total, str(raw_symbol), status)
                    continue

                resolved_symbol = resolved_by_input.get(symbol, "")
                if not resolved_symbol:
                    failed += 1
                    failures.append((symbol, "Instrument token not found"))
                    status = "failed"
                    processed += 1
                    if progress_cb:
                        progress_cb(processed, total, symbol, status)
                    continue

                q = quotes.get(resolved_symbol)
                if not q:
                    failed += 1
                    failures.append((symbol, "No quote received"))
                    status = "failed"
                    processed += 1
                    if progress_cb:
                        progress_cb(processed, total, symbol, status)
                    continue

                try:
                    row = self._quote_to_metrics_row(symbol, q)
                    token = instrument_token_by_symbol.get(resolved_symbol)
                    if token:
                        row = self._enrich_row_with_history(token, row)
                    row = self._apply_ml_predictions(row)
                    row["strategy_fit"] = determine_strategy_fit(row)
                    row["opportunity_score"] = calculate_opportunity_score(row)
                    cur.execute(
                        """
                        INSERT OR REPLACE INTO stock_metrics
                        (
                            symbol, date, ltp, open, high, low, close, volume,
                            rsi, adx, macd, macd_signal,
                            sma_20, sma_50, sma_200, ema_9, ema_21,
                            atr, bb_upper, bb_middle, bb_lower, bb_width, trend_score,
                            momentum_score, volatility_score, liquidity_score, opportunity_score,
                            volume_ratio, win_probability, expected_return,
                            strategy_fit, confidence,
                            reco_score, reco_hit_rate, reco_sample_size, reco_label, reco_source,
                            updated_at
                        )
                        VALUES
                        (
                            ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?,
                            ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?,
                            ?, ?, ?, ?,
                            ?, ?, ?, ?, ?,
                            CURRENT_TIMESTAMP
                        )
                        """,
                        (
                            symbol,
                            today,
                            row["ltp"],
                            row["open"],
                            row["high"],
                            row["low"],
                            row["close"],
                            row["volume"],
                            row["rsi"],
                            row["adx"],
                            row["macd"],
                            row["macd_signal"],
                            row["sma_20"],
                            row["sma_50"],
                            row["sma_200"],
                            row["ema_9"],
                            row["ema_21"],
                            row["atr"],
                            row["bb_upper"],
                            row["bb_middle"],
                            row["bb_lower"],
                            row["bb_width"],
                            row["trend_score"],
                            row["momentum_score"],
                            row["volatility_score"],
                            row["liquidity_score"],
                            row["opportunity_score"],
                            row["volume_ratio"],
                            row["win_probability"],
                            row["expected_return"],
                            row["strategy_fit"],
                            row["confidence"],
                            row.get("reco_score", 0.0),
                            row.get("reco_hit_rate", 0.5),
                            row.get("reco_sample_size", 0),
                            row.get("reco_label", "neutral"),
                            row.get("reco_source", "none"),
                        ),
                    )
                    updated += 1
                except Exception as exc:
                    failed += 1
                    failures.append((symbol, str(exc)))
                    status = "failed"

                processed += 1
                if progress_cb:
                    progress_cb(processed, total, symbol, status)

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        return RefreshResult(inserted_or_updated=updated, failed=failed, failures=failures)

    def scan_first4h_reversal_strategy(
        self,
        symbols: List[str],
        trade_date: Optional[date] = None,
        progress_cb: Optional[Callable[[int, int, str, str], None]] = None,
    ) -> Dict:
        """
        4H first-candle range + 5m sweep/reversal strategy scanner.
        Entry is on reversal bar close, with fixed 2:1 target.
        """
        if not self.is_authenticated:
            raise ZerodhaConfigError("Zerodha access token is missing. Authenticate first.")
        if not symbols:
            return {"signals": [], "failed": 0, "failures": []}

        trade_date = trade_date or date.today()
        day_start = datetime.combine(trade_date, time(9, 15))
        day_end = datetime.combine(trade_date, time(15, 30))

        instruments = self.kite.instruments("NSE")
        instrument_token_by_symbol, alias_to_tradingsymbol = self._build_instrument_resolution_maps(instruments)

        failures: List[Tuple[str, str]] = []
        signals: List[Dict] = []
        total = len(symbols)
        done = 0

        for raw_symbol in symbols:
            symbol = self.normalize_symbol(raw_symbol)
            status = "ok"
            try:
                token = instrument_token_by_symbol.get(symbol)
                if not token:
                    resolved_symbol = self._resolve_to_tradingsymbol(
                        symbol,
                        instrument_token_by_symbol,
                        alias_to_tradingsymbol,
                    )
                    token = instrument_token_by_symbol.get(resolved_symbol) if resolved_symbol else None
                if not token:
                    raise ValueError("Instrument token not found")

                candles = self.kite.historical_data(
                    instrument_token=token,
                    from_date=day_start,
                    to_date=day_end,
                    interval="5minute",
                )
                if not candles:
                    raise ValueError("No 5-minute candles for selected day")

                intraday_df = pd.DataFrame(candles)
                signal = self._build_first4h_reversal_signal(
                    intraday_df=intraday_df,
                    symbol=symbol,
                    trade_date=trade_date,
                )
                if signal:
                    signals.append(signal)
                    status = "signal"
                else:
                    status = "no_signal"
            except Exception as exc:
                failures.append((symbol or str(raw_symbol), str(exc)))
                status = "failed"

            done += 1
            if progress_cb:
                progress_cb(done, total, symbol or str(raw_symbol), status)

        return {
            "signals": signals,
            "failed": len(failures),
            "failures": failures,
        }

    @classmethod
    def _build_first4h_reversal_signal(
        cls,
        intraday_df: pd.DataFrame,
        symbol: str,
        trade_date: date,
    ) -> Optional[Dict]:
        if intraday_df.empty:
            return None

        df = intraday_df.copy()
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df[df["date"].notna()]
            df = df.sort_values(by="date").reset_index(drop=True)
        if df.empty or len(df) < 50:
            return None

        # First 4 hours from 09:15 on a 5-minute chart => 48 bars.
        first_4h = df.head(48)
        first_4h_high = cls._safe_float(first_4h["high"].max(), 0.0)
        first_4h_low = cls._safe_float(first_4h["low"].min(), 0.0)
        if first_4h_high <= 0 or first_4h_low <= 0 or first_4h_high <= first_4h_low:
            return None

        post = df.iloc[48:].copy()
        if post.empty:
            return None

        for _, bar in post.iterrows():
            o = cls._safe_float(bar.get("open"), 0.0)
            h = cls._safe_float(bar.get("high"), 0.0)
            l = cls._safe_float(bar.get("low"), 0.0)
            c = cls._safe_float(bar.get("close"), 0.0)
            t = bar.get("date")
            trigger_time = str(t) if t is not None else ""

            # Sweep above first-4H high then bearish reversal back below high -> SELL.
            if h > first_4h_high and c < first_4h_high and c < o:
                entry = c
                stop_loss = max(h, first_4h_high)
                risk = stop_loss - entry
                if risk <= 0:
                    continue
                target = entry - (2.0 * risk)
                return {
                    "symbol": symbol,
                    "strategy": "first4h_reversal",
                    "side": "SELL",
                    "setup": "High sweep -> bearish reversal",
                    "entry": round(entry, 2),
                    "stop_loss": round(stop_loss, 2),
                    "target": round(target, 2),
                    "rr_ratio": 2.0,
                    "risk_per_share": round(risk, 2),
                    "first_4h_high": round(first_4h_high, 2),
                    "first_4h_low": round(first_4h_low, 2),
                    "trigger_time": trigger_time,
                    "trade_date": trade_date.isoformat(),
                }

            # Sweep below first-4H low then bullish reversal back above low -> BUY.
            if l < first_4h_low and c > first_4h_low and c > o:
                entry = c
                stop_loss = min(l, first_4h_low)
                risk = entry - stop_loss
                if risk <= 0:
                    continue
                target = entry + (2.0 * risk)
                return {
                    "symbol": symbol,
                    "strategy": "first4h_reversal",
                    "side": "BUY",
                    "setup": "Low sweep -> bullish reversal",
                    "entry": round(entry, 2),
                    "stop_loss": round(stop_loss, 2),
                    "target": round(target, 2),
                    "rr_ratio": 2.0,
                    "risk_per_share": round(risk, 2),
                    "first_4h_high": round(first_4h_high, 2),
                    "first_4h_low": round(first_4h_low, 2),
                    "trigger_time": trigger_time,
                    "trade_date": trade_date.isoformat(),
                }

        return None

    def refresh_ltp_snapshot(
        self,
        symbols: List[str],
        progress_cb: Optional[Callable[[int, int, str, str], None]] = None,
    ) -> RefreshResult:
        """
        Fast startup refresh that only updates OHLCV/LTP snapshot for today's row.
        Keeps existing indicator/model columns intact via ON CONFLICT UPDATE.
        """
        if not self.is_authenticated:
            raise ZerodhaConfigError("Zerodha access token is missing. Authenticate first.")
        if not symbols:
            return RefreshResult(inserted_or_updated=0, failed=0, failures=[])

        today = date.today().isoformat()
        instrument_token_by_symbol: Dict[str, int] = {}
        alias_to_tradingsymbol: Dict[str, str] = {}
        resolved_by_input: Dict[str, str] = {}
        failures: List[Tuple[str, str]] = []

        try:
            instruments = self.kite.instruments("NSE")
            instrument_token_by_symbol, alias_to_tradingsymbol = self._build_instrument_resolution_maps(instruments)
            for raw_symbol in symbols:
                base_symbol = self.normalize_symbol(raw_symbol)
                resolved = self._resolve_to_tradingsymbol(
                    base_symbol,
                    instrument_token_by_symbol,
                    alias_to_tradingsymbol,
                )
                if resolved:
                    resolved_by_input[base_symbol] = resolved
        except Exception as exc:
            raise RuntimeError(f"Could not load NSE instruments: {exc}") from exc

        resolved_universe = list({v for v in resolved_by_input.values() if v})
        quotes = self.fetch_quotes(resolved_universe) if resolved_universe else {}

        conn = get_connection()
        cur = conn.cursor()
        updated = 0
        failed = 0
        total = len(symbols)
        processed = 0

        try:
            for raw_symbol in symbols:
                symbol = self.normalize_symbol(raw_symbol)
                status = "updated"
                if not symbol:
                    failed += 1
                    failures.append((str(raw_symbol), "Invalid symbol"))
                    status = "invalid"
                    processed += 1
                    if progress_cb:
                        progress_cb(processed, total, str(raw_symbol), status)
                    continue

                resolved_symbol = resolved_by_input.get(symbol, "")
                if not resolved_symbol:
                    failed += 1
                    failures.append((symbol, "Instrument token not found"))
                    status = "failed"
                    processed += 1
                    if progress_cb:
                        progress_cb(processed, total, symbol, status)
                    continue

                q = quotes.get(resolved_symbol)
                if not q:
                    failed += 1
                    failures.append((symbol, "No quote received"))
                    status = "failed"
                    processed += 1
                    if progress_cb:
                        progress_cb(processed, total, symbol, status)
                    continue

                try:
                    row = self._quote_to_metrics_row(symbol, q)
                    cur.execute(
                        """
                        INSERT INTO stock_metrics
                        (symbol, date, ltp, open, high, low, close, volume, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(symbol, date) DO UPDATE SET
                            ltp = excluded.ltp,
                            open = excluded.open,
                            high = excluded.high,
                            low = excluded.low,
                            close = excluded.close,
                            volume = excluded.volume,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (
                            symbol,
                            today,
                            row["ltp"],
                            row["open"],
                            row["high"],
                            row["low"],
                            row["close"],
                            row["volume"],
                        ),
                    )
                    updated += 1
                except Exception as exc:
                    failed += 1
                    failures.append((symbol, str(exc)))
                    status = "failed"

                processed += 1
                if progress_cb:
                    progress_cb(processed, total, symbol, status)

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        return RefreshResult(inserted_or_updated=updated, failed=failed, failures=failures)

    def refresh_sector_buckets(self, symbols: List[str]) -> Tuple[int, int]:
        """
        Refresh sector buckets for loaded symbols using Zerodha instruments.
        Returns (updated_count, missing_count).
        """
        if not self.is_authenticated:
            raise ZerodhaConfigError("Zerodha access token is missing. Authenticate first.")
        if not symbols:
            return (0, 0)

        instruments = self.kite.instruments("NSE")
        name_by_symbol: Dict[str, str] = {}
        for row in instruments:
            tradingsymbol = str(row.get("tradingsymbol", "")).strip().upper()
            name = str(row.get("name", "")).strip()
            if tradingsymbol:
                name_by_symbol[tradingsymbol] = name

        conn = get_connection()
        cur = conn.cursor()
        updated = 0
        missing = 0

        try:
            for symbol in symbols:
                sym = self.normalize_symbol(symbol)
                if not sym:
                    missing += 1
                    continue
                name = name_by_symbol.get(sym, "")

                if not name:
                    cur.execute("SELECT company FROM stocks_master WHERE symbol = ?", (sym,))
                    row = cur.fetchone()
                    name = (row["company"] if row and row["company"] else "") if row else ""

                if not name:
                    missing += 1
                    bucket = "Other"
                else:
                    bucket = self.classify_sector_bucket(name=name, symbol=sym)
                cur.execute(
                    """
                    UPDATE stocks_master
                    SET sector = ?, company = COALESCE(NULLIF(company, ''), ?)
                    WHERE symbol = ?
                    """,
                    (bucket, name, sym),
                )
                if cur.rowcount > 0:
                    updated += 1

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        return (updated, missing)

    def run_backtest_ai_calibration(
        self,
        symbols: List[str],
        lookback_days: int = 260,
        hold_days: int = 5,
        progress_cb: Optional[Callable[[int, int, str, str], None]] = None,
    ) -> Dict:
        """
        Run historical strategy backtest per symbol and blend with ML predictions
        to recalibrate strategy_fit/confidence/win_probability/expected_return.
        """
        if not self.is_authenticated:
            raise ZerodhaConfigError("Zerodha access token is missing. Authenticate first.")
        if not symbols:
            return {
                "updated_symbols": 0,
                "failed_symbols": 0,
                "failures": [],
                "strategy_distribution": {},
            }

        today = date.today().isoformat()
        from_date = date.today() - timedelta(days=max(120, lookback_days))
        failures: List[Tuple[str, str]] = []
        updated_symbols = 0
        failed_symbols = 0
        strategy_distribution: Dict[str, int] = {}
        strategy_rules = self._strategy_rules()
        use_external_reco = len(symbols) <= 60
        global_stats = {
            name: {"trades": 0, "wins": 0, "sum_return": 0.0}
            for name in strategy_rules.keys()
        }
        run_id = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        timeframe_coverage: Dict[str, int] = {}

        instrument_token_by_symbol: Dict[str, int] = {}
        alias_to_tradingsymbol: Dict[str, str] = {}
        instruments = self.kite.instruments("NSE")
        instrument_token_by_symbol, alias_to_tradingsymbol = self._build_instrument_resolution_maps(instruments)

        conn = get_connection()
        cur = conn.cursor()
        total = len(symbols)
        processed = 0

        try:
            # Keep report snapshot fresh for each run and avoid stale rows in UI.
            cur.execute("DELETE FROM strategy_performance")

            for raw_symbol in symbols:
                symbol = self.normalize_symbol(raw_symbol)
                status = "updated"
                if not symbol:
                    failed_symbols += 1
                    failures.append((str(raw_symbol), "Invalid symbol"))
                    status = "invalid"
                    processed += 1
                    if progress_cb:
                        progress_cb(processed, total, str(raw_symbol), status)
                    continue

                token = instrument_token_by_symbol.get(symbol)
                if not token:
                    resolved_symbol = self._resolve_to_tradingsymbol(
                        symbol,
                        instrument_token_by_symbol,
                        alias_to_tradingsymbol,
                    )
                    token = instrument_token_by_symbol.get(resolved_symbol) if resolved_symbol else None
                if not token:
                    failed_symbols += 1
                    failures.append((symbol, "Instrument token not found"))
                    status = "missing_token"
                    processed += 1
                    if progress_cb:
                        progress_cb(processed, total, symbol, status)
                    continue

                try:
                    interval_plan = self._build_interval_plan(
                        total_symbols=len(symbols),
                        lookback_days=lookback_days,
                        hold_days=hold_days,
                    )
                    combined_backtest = {
                        name: {"trades": 0, "wins": 0, "sum_return": 0.0}
                        for name in strategy_rules.keys()
                    }
                    latest = None
                    usable_intervals = 0

                    for interval, lb_days, interval_hold, weight, max_trades_cap in interval_plan:
                        try:
                            interval_from = date.today() - timedelta(days=max(20, lb_days))
                            candles = self.kite.historical_data(
                                instrument_token=token,
                                from_date=interval_from,
                                to_date=date.today(),
                                interval=interval,
                            )
                            if not candles:
                                continue
                            hist_df = pd.DataFrame(candles)
                            if hist_df.empty or len(hist_df) < 80:
                                continue

                            ind_df = add_indicators(hist_df)
                            if ind_df.empty or len(ind_df) < 80:
                                continue

                            backtest_out = self._backtest_strategies(
                                ind_df,
                                hold_days=interval_hold,
                                symbol=symbol,
                                timeframe=interval,
                                max_trades_per_strategy=max_trades_cap,
                            )
                            backtest_tf = backtest_out.get("stats", {})
                            self._persist_backtest_trades(cur, run_id, backtest_out.get("trades", []))
                            for s_name, s_data in backtest_tf.items():
                                combined_backtest[s_name]["trades"] += int(s_data["trades"] * weight)
                                combined_backtest[s_name]["wins"] += int(s_data["wins"] * weight)
                                combined_backtest[s_name]["sum_return"] += float(s_data["sum_return"] * weight)

                            timeframe_coverage[interval] = timeframe_coverage.get(interval, 0) + 1
                            usable_intervals += 1
                            if interval == "day" or latest is None:
                                latest = ind_df.iloc[-1]
                        except Exception:
                            continue

                    if latest is None or usable_intervals == 0:
                        raise ValueError("Insufficient historical candles across selected intervals")

                    for s_name, s_data in combined_backtest.items():
                        global_stats[s_name]["trades"] += int(s_data["trades"])
                        global_stats[s_name]["wins"] += int(s_data["wins"])
                        global_stats[s_name]["sum_return"] += float(s_data["sum_return"])

                    best_strategy, best_info = self._pick_best_strategy(combined_backtest)

                    row_snapshot = self._latest_metric_snapshot(cur, symbol)
                    if not row_snapshot:
                        raise ValueError("No latest metric row found. Run Refresh Metrics first.")

                    enriched = self._merge_indicator_snapshot(row_snapshot, latest)
                    ai_win, ai_profit = self._predict_from_row(enriched)
                    bt_win = float(best_info.get("win_rate", 0.5))
                    bt_profit = float(best_info.get("avg_return", 0.0))
                    trade_count = int(best_info.get("trades", 0))
                    bt_weight = float(min(0.75, max(0.25, trade_count / 40.0)))

                    final_win = (bt_weight * bt_win) + ((1.0 - bt_weight) * ai_win)
                    final_profit = (bt_weight * bt_profit) + ((1.0 - bt_weight) * ai_profit)
                    final_confidence = min(
                        99.0,
                        max(45.0, 42.0 + (trade_count * 0.9) + (final_win * 30.0) + min(10.0, abs(final_profit) * 2.0)),
                    )
                    reco_info = self._get_external_recommendation_signal(
                        symbol,
                        enabled=use_external_reco,
                    )
                    reco_score = float(reco_info.get("score", 0.0))
                    reco_hit = float(reco_info.get("hit_rate", 0.5))
                    reco_samples = int(reco_info.get("sample_size", 0))
                    reco_prob = float(min(0.9, max(0.1, 0.5 + (reco_score * 0.22))))
                    reco_weight = float(min(0.30, max(0.0, 0.08 + (reco_samples / 120.0))))
                    final_win = ((1.0 - reco_weight) * final_win) + (reco_weight * reco_prob)
                    hit_edge = max(-0.25, min(0.25, reco_hit - 0.5))
                    final_profit = final_profit * (1.0 + (reco_score * hit_edge))
                    final_confidence = min(99.0, max(40.0, final_confidence + (reco_weight * 12.0)))

                    if best_strategy == "none":
                        final_strategy = "none"
                        final_confidence = max(40.0, final_confidence - 12.0)
                    else:
                        final_strategy = best_strategy
                        if reco_samples >= 8 and reco_hit >= 0.55 and reco_score <= -0.35:
                            final_strategy = "none"
                            final_confidence = max(40.0, final_confidence - 8.0)

                    enriched["win_probability"] = max(0.01, min(0.99, float(final_win)))
                    enriched["expected_return"] = float(final_profit)
                    enriched["confidence"] = float(final_confidence)
                    enriched["strategy_fit"] = final_strategy
                    enriched["reco_score"] = reco_score
                    enriched["reco_hit_rate"] = reco_hit
                    enriched["reco_sample_size"] = reco_samples
                    enriched["reco_label"] = str(reco_info.get("label", "neutral"))
                    enriched["reco_source"] = str(reco_info.get("source", "yahoo_finance"))
                    enriched["opportunity_score"] = int(calculate_opportunity_score(enriched))

                    metric_date = row_snapshot.get("date") or today
                    cur.execute(
                        """
                        UPDATE stock_metrics
                        SET
                            rsi = ?, adx = ?, macd = ?, macd_signal = ?,
                            sma_20 = ?, sma_50 = ?, sma_200 = ?, ema_9 = ?, ema_21 = ?,
                            atr = ?, bb_upper = ?, bb_middle = ?, bb_lower = ?, bb_width = ?,
                            trend_score = ?, momentum_score = ?, volatility_score = ?, liquidity_score = ?,
                            volume_ratio = ?, strategy_fit = ?, win_probability = ?, expected_return = ?,
                            confidence = ?, opportunity_score = ?,
                            reco_score = ?, reco_hit_rate = ?, reco_sample_size = ?, reco_label = ?, reco_source = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE symbol = ? AND date = ?
                        """,
                        (
                            enriched["rsi"],
                            enriched["adx"],
                            enriched["macd"],
                            enriched["macd_signal"],
                            enriched["sma_20"],
                            enriched["sma_50"],
                            enriched["sma_200"],
                            enriched["ema_9"],
                            enriched["ema_21"],
                            enriched["atr"],
                            enriched["bb_upper"],
                            enriched["bb_middle"],
                            enriched["bb_lower"],
                            enriched["bb_width"],
                            enriched["trend_score"],
                            enriched["momentum_score"],
                            enriched["volatility_score"],
                            enriched["liquidity_score"],
                            enriched["volume_ratio"],
                            enriched["strategy_fit"],
                            enriched["win_probability"],
                            enriched["expected_return"],
                            enriched["confidence"],
                            enriched["opportunity_score"],
                            enriched["reco_score"],
                            enriched["reco_hit_rate"],
                            enriched["reco_sample_size"],
                            enriched["reco_label"],
                            enriched["reco_source"],
                            symbol,
                            metric_date,
                        ),
                    )
                    if cur.rowcount <= 0:
                        raise ValueError("No row updated")

                    strategy_distribution[final_strategy] = strategy_distribution.get(final_strategy, 0) + 1
                    updated_symbols += 1
                except Exception as exc:
                    failed_symbols += 1
                    failures.append((symbol, str(exc)))
                    status = "failed"

                processed += 1
                if progress_cb:
                    progress_cb(processed, total, symbol, status)

            self._persist_strategy_backtest_rollup(cur, global_stats, from_date.isoformat(), today)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        return {
            "run_id": run_id,
            "updated_symbols": updated_symbols,
            "failed_symbols": failed_symbols,
            "failures": failures,
            "strategy_distribution": strategy_distribution,
            "timeframe_coverage": timeframe_coverage,
            "intervals_used": [p[0] for p in self._build_interval_plan(len(symbols), lookback_days, hold_days)],
            "external_reco_enabled": use_external_reco,
        }

    @staticmethod
    def _build_interval_plan(
        total_symbols: int,
        lookback_days: int,
        hold_days: int,
    ) -> List[Tuple[str, int, int, float, Optional[int]]]:
        """
        Dynamic interval plan to keep backtests responsive on larger universes.
        Tuple: (interval, lookback_days, hold_bars, weight, max_trades_per_strategy)
        """
        if total_symbols >= 220:
            return [
                ("day", max(120, lookback_days), hold_days, 1.0, None),
            ]
        if total_symbols >= 120:
            return [
                ("day", max(120, lookback_days), hold_days, 1.0, None),
                ("60minute", min(90, lookback_days), max(14, hold_days * 5), 0.75, 180),
            ]
        return [
            ("day", max(120, lookback_days), hold_days, 1.0, None),
            ("60minute", min(120, lookback_days), max(16, hold_days * 6), 0.8, 220),
            ("15minute", min(60, lookback_days), max(24, hold_days * 12), 0.6, 120),
        ]

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        """
        Normalize symbols to Zerodha NSE tradingsymbol format.
        Examples:
        - NSE:INFY -> INFY
        - INFY.NS -> INFY
        """
        s = (symbol or "").strip().upper()
        if not s:
            return ""
        if ":" in s:
            s = s.split(":", 1)[1]
        if s.endswith(".NS"):
            s = s[:-3]
        return s

    @staticmethod
    def _quote_to_metrics_row(symbol: str, quote: Dict) -> Dict[str, float | int | str]:
        """
        Map quote snapshot to stock_metrics-compatible row.
        Uses lightweight heuristics when full indicator history is unavailable.
        """
        ohlc = quote.get("ohlc") or {}

        ltp = float(quote.get("last_price") or 0.0)
        open_price = float(ohlc.get("open") or ltp)
        high = float(ohlc.get("high") or ltp)
        low = float(ohlc.get("low") or ltp)
        prev_close = float(ohlc.get("close") or ltp)
        volume = int(quote.get("volume") or 0)

        if prev_close > 0:
            day_change_pct = ((ltp - prev_close) / prev_close) * 100.0
        else:
            day_change_pct = 0.0

        intraday_range_pct = ((high - low) / ltp * 100.0) if ltp > 0 else 0.0
        trend_score = max(0, min(100, int(50 + (day_change_pct * 10))))
        momentum_score = max(0, min(100, int(50 + (day_change_pct * 8))))
        volatility_score = max(0, min(100, int(intraday_range_pct * 12)))
        liquidity_score = 90 if volume > 1_000_000 else 75 if volume > 100_000 else 60

        # Neutral defaults for indicators that require longer history.
        rsi = max(1.0, min(99.0, 50.0 + (day_change_pct * 3.0)))
        adx = max(5.0, min(50.0, 18.0 + abs(day_change_pct * 5.0)))
        macd = day_change_pct / 2.0
        macd_signal = macd * 0.7
        atr = max(0.01, high - low)
        bb_middle = prev_close if prev_close > 0 else ltp
        bb_upper = bb_middle + (2 * atr)
        bb_lower = max(0.01, bb_middle - (2 * atr))
        bb_width = ((bb_upper - bb_lower) / bb_middle) * 100 if bb_middle else 0.0
        sma_20 = prev_close
        sma_50 = prev_close
        sma_200 = prev_close
        ema_9 = prev_close
        ema_21 = prev_close
        volume_ratio = 1.2 if volume > 0 else 1.0
        win_probability = max(0.45, min(0.75, 0.55 + (day_change_pct / 30.0)))
        expected_return = round(day_change_pct, 3)
        confidence = max(40.0, min(85.0, 55.0 + abs(day_change_pct * 4.0)))

        if (ltp >= bb_middle and adx >= 15) or (abs(day_change_pct) <= 1.8 and trend_score >= 50):
            strategy_fit = ZerodhaClient.PRIMARY_STRATEGY
        else:
            strategy_fit = "none"

        return {
            "symbol": symbol,
            "ltp": ltp,
            "open": open_price,
            "high": high,
            "low": low,
            "close": prev_close,
            "volume": volume,
            "rsi": rsi,
            "adx": adx,
            "macd": macd,
            "macd_signal": macd_signal,
            "sma_20": sma_20,
            "sma_50": sma_50,
            "sma_200": sma_200,
            "ema_9": ema_9,
            "ema_21": ema_21,
            "atr": atr,
            "bb_upper": bb_upper,
            "bb_middle": bb_middle,
            "bb_lower": bb_lower,
            "bb_width": bb_width,
            "trend_score": trend_score,
            "momentum_score": momentum_score,
            "volatility_score": volatility_score,
            "liquidity_score": liquidity_score,
            "volume_ratio": volume_ratio,
            "win_probability": win_probability,
            "expected_return": expected_return,
            "strategy_fit": strategy_fit,
            "confidence": confidence,
            "reco_score": 0.0,
            "reco_hit_rate": 0.5,
            "reco_sample_size": 0,
            "reco_label": "neutral",
            "reco_source": "none",
        }

    def _get_external_recommendation_signal(self, symbol: str, enabled: bool = True) -> Dict[str, Any]:
        """
        Pull analyst recommendation consensus and historical recommendation hit-rate
        from Yahoo Finance and convert to normalized signal.
        """
        key = self.normalize_symbol(symbol)
        if not key:
            return {"score": 0.0, "hit_rate": 0.5, "sample_size": 0, "label": "neutral", "source": "none"}
        if not enabled:
            return {"score": 0.0, "hit_rate": 0.5, "sample_size": 0, "label": "neutral", "source": "disabled_for_large_run"}
        cached = self._reco_cache.get(key)
        if cached:
            return cached

        ticker = f"{key}.NS"
        out = {
            "score": 0.0,
            "hit_rate": 0.5,
            "sample_size": 0,
            "label": "neutral",
            "source": "yahoo_finance",
        }
        try:
            summary_url = (
                f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
                "?modules=recommendationTrend,financialData,upgradeDowngradeHistory"
            )
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(summary_url, timeout=1.8, headers=headers)
            data = resp.json()
            result = (((data or {}).get("quoteSummary") or {}).get("result") or [{}])[0]
            trend = (((result.get("recommendationTrend") or {}).get("trend") or [{}])[0])
            fin = result.get("financialData") or {}
            updown = ((result.get("upgradeDowngradeHistory") or {}).get("history") or [])

            strong_buy = float(trend.get("strongBuy") or 0)
            buy = float(trend.get("buy") or 0)
            hold = float(trend.get("hold") or 0)
            sell = float(trend.get("sell") or 0)
            strong_sell = float(trend.get("strongSell") or 0)
            total_votes = strong_buy + buy + hold + sell + strong_sell
            trend_score = ((strong_buy + buy) - (sell + strong_sell)) / total_votes if total_votes > 0 else 0.0

            current_price = float(((fin.get("currentPrice") or {}).get("raw")) or 0.0)
            target_mean = float(((fin.get("targetMeanPrice") or {}).get("raw")) or 0.0)
            target_gap = ((target_mean - current_price) / current_price) if current_price > 0 and target_mean > 0 else 0.0
            target_component = max(-1.0, min(1.0, target_gap / 0.20))

            hist_url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2y"
            hresp = requests.get(hist_url, timeout=1.8, headers=headers)
            hdata = hresp.json()
            hres = (((hdata or {}).get("chart") or {}).get("result") or [{}])[0]
            ts = hres.get("timestamp") or []
            closes = ((((hres.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or [])
            price_points = [(int(t), float(c)) for t, c in zip(ts, closes) if c is not None]
            price_points.sort(key=lambda x: x[0])

            successes = 0
            considered = 0
            if price_points and updown:
                epochs = [p[0] for p in price_points]
                for item in updown[:80]:
                    epoch = int(item.get("epochGradeDate") or 0)
                    action = str(item.get("action") or "").lower().strip()
                    if epoch <= 0:
                        continue
                    direction = 0
                    if action in {"up", "init", "main"}:
                        direction = 1
                    elif action in {"down"}:
                        direction = -1
                    if direction == 0:
                        continue
                    idx = np.searchsorted(epochs, epoch)
                    if idx >= len(price_points) - 20:
                        continue
                    entry = price_points[idx][1]
                    future = price_points[min(len(price_points) - 1, idx + 20)][1]
                    if entry <= 0:
                        continue
                    considered += 1
                    if (direction > 0 and future > entry) or (direction < 0 and future < entry):
                        successes += 1
            hit_rate = (successes / considered) if considered > 0 else 0.5

            score = (0.7 * trend_score) + (0.3 * target_component)
            score = max(-1.0, min(1.0, float(score)))
            if score > 0.2:
                label = "bullish"
            elif score < -0.2:
                label = "bearish"
            else:
                label = "neutral"
            out = {
                "score": score,
                "hit_rate": float(hit_rate),
                "sample_size": int(considered),
                "label": label,
                "source": "yahoo_finance",
            }
        except Exception:
            pass

        self._reco_cache[key] = out
        return out

    def _enrich_row_with_history(self, instrument_token: int, row: Dict) -> Dict:
        """
        Enrich indicator fields using historical day candles.
        Falls back to quote-derived defaults if unavailable.
        """
        try:
            to_date = date.today()
            from_date = to_date - timedelta(days=380)
            candles = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval="day",
            )
            if not candles:
                return row

            df = pd.DataFrame(candles)
            if df.empty:
                return row

            required = {"open", "high", "low", "close", "volume"}
            if not required.issubset(set(df.columns)):
                return row

            ind_df = add_indicators(df)
            if ind_df.empty:
                return row

            last = ind_df.iloc[-1]

            def sfloat(key: str, fallback: float) -> float:
                val = last.get(key, fallback)
                return fallback if pd.isna(val) else float(val)

            row["rsi"] = sfloat("RSI", row["rsi"])
            row["adx"] = sfloat("ADX", row["adx"])
            row["macd"] = sfloat("MACD", row["macd"])
            row["macd_signal"] = sfloat("MACD_Signal", row["macd_signal"])
            row["sma_20"] = sfloat("SMA_20", row["sma_20"])
            row["sma_50"] = sfloat("SMA_50", row["sma_50"])
            row["sma_200"] = sfloat("SMA_200", row["sma_200"])
            row["ema_9"] = sfloat("EMA_9", row["ema_9"])
            row["ema_21"] = sfloat("EMA_21", row["ema_21"])
            row["atr"] = sfloat("ATR", row["atr"])
            row["bb_upper"] = sfloat("BB_Upper", row["bb_upper"])
            row["bb_middle"] = row["sma_20"]
            row["bb_lower"] = sfloat("BB_Lower", row["bb_lower"])
            row["bb_width"] = sfloat("BB_Width", row["bb_width"])
            row["volume_ratio"] = sfloat("Volume_Ratio", row["volume_ratio"])
            return row
        except Exception as exc:
            log.debug("Indicator enrichment failed for token %s: %s", instrument_token, exc)
            return row

    def _apply_ml_predictions(self, row: Dict) -> Dict:
        """
        Apply trained-model inference to overwrite default win/profit predictions.
        """
        try:
            rr_ratio = 2.0
            atr = float(row.get("atr", 0.0) or 0.0)
            ltp = float(row.get("ltp", 0.0) or 0.0)
            if atr > 0 and ltp > 0:
                risk_pct = (atr / ltp) * 100.0
                if risk_pct > 0:
                    rr_ratio = max(1.0, min(4.0, (2.0 * risk_pct) / risk_pct))

            feat = {
                "rsi": float(row.get("rsi", 50.0)),
                "adx": float(row.get("adx", 20.0)),
                "trend_score": float(row.get("trend_score", 50.0)),
                "rr_ratio": float(rr_ratio),
                "rsi_oversold": 1 if float(row.get("rsi", 50.0)) < 30 else 0,
                "rsi_overbought": 1 if float(row.get("rsi", 50.0)) > 70 else 0,
                "adx_strong": 1 if float(row.get("adx", 20.0)) > 30 else 0,
                "strong_trend": 1 if float(row.get("trend_score", 50.0)) > 70 else 0,
                "is_intraday": 1,
                "rsi_adx": float(row.get("rsi", 50.0)) * float(row.get("adx", 20.0)) / 100.0,
            }
            row["win_probability"] = float(self.predictor.predict_win_prob(feat))
            row["expected_return"] = float(self.predictor.predict_profit(feat))
        except Exception as exc:
            log.debug("ML inference fallback used: %s", exc)
        return row

    @staticmethod
    def classify_sector_bucket(name: str, symbol: str = "") -> str:
        """
        Map stock to broad sector buckets (intentionally coarse-grained).
        """
        text = f"{name} {symbol}".upper()

        keyword_map = {
            "Financials": [
                "BANK", "FINANCE", "CAPITAL", "INSURANCE", "NBFC", "HDFC", "ICICI", "SBI"
            ],
            "Technology": [
                "TECH", "INFOTECH", "SOFTWARE", "SYSTEM", "DIGITAL", "IT"
            ],
            "Energy": [
                "OIL", "GAS", "PETRO", "ENERGY", "POWER", "COAL", "ONGC", "RENEW"
            ],
            "Healthcare": [
                "PHARMA", "LAB", "HEALTH", "MEDIC", "HOSP", "BIO", "LIFE SCI"
            ],
            "Consumer": [
                "FMCG", "CONSUMER", "RETAIL", "FOOD", "BEVERAGE", "TEXTILE", "APPAREL", "MART"
            ],
            "Industrials": [
                "CEMENT", "STEEL", "METAL", "MINING", "CHEM", "PAINT", "INFRA",
                "ENGINEER", "INDUSTR", "MFG", "CONSTRUCT", "LOGISTIC", "PORT"
            ],
            "Telecom/Media": [
                "TELECOM", "COMMUNICATION", "MEDIA", "BROADCAST"
            ],
            "Auto/Mobility": [
                "AUTO", "MOTOR", "TYRE", "BATTERY", "MOBILITY", "TRACTOR"
            ],
        }

        for sector, keywords in keyword_map.items():
            if any(k in text for k in keywords):
                return sector

        return "Other"

    def _latest_metric_snapshot(self, cur, symbol: str) -> Optional[Dict]:
        cur.execute(
            """
            SELECT * FROM stock_metrics
            WHERE symbol = ?
            ORDER BY date DESC
            LIMIT 1
            """,
            (symbol,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    @staticmethod
    def _safe_float(value, fallback: float = 0.0) -> float:
        if value is None:
            return float(fallback)
        try:
            if pd.isna(value):
                return float(fallback)
        except Exception:
            pass
        try:
            return float(value)
        except Exception:
            return float(fallback)

    @classmethod
    def _merge_indicator_snapshot(cls, base_row: Dict, latest) -> Dict:
        out = dict(base_row)
        close = cls._safe_float(latest.get("close"), cls._safe_float(base_row.get("close"), 0.0))
        high = cls._safe_float(latest.get("high"), cls._safe_float(base_row.get("high"), close))
        low = cls._safe_float(latest.get("low"), cls._safe_float(base_row.get("low"), close))
        volume = int(cls._safe_float(latest.get("volume"), cls._safe_float(base_row.get("volume"), 0.0)))
        sma20 = cls._safe_float(latest.get("SMA_20"), cls._safe_float(base_row.get("sma_20"), close))
        sma50 = cls._safe_float(latest.get("SMA_50"), cls._safe_float(base_row.get("sma_50"), close))
        sma200 = cls._safe_float(latest.get("SMA_200"), cls._safe_float(base_row.get("sma_200"), close))
        ema9 = cls._safe_float(latest.get("EMA_9"), cls._safe_float(base_row.get("ema_9"), close))
        ema21 = cls._safe_float(latest.get("EMA_21"), cls._safe_float(base_row.get("ema_21"), close))
        atr = max(0.01, cls._safe_float(latest.get("ATR"), cls._safe_float(base_row.get("atr"), abs(high - low))))
        bb_upper = cls._safe_float(latest.get("BB_Upper"), cls._safe_float(base_row.get("bb_upper"), close + (2 * atr)))
        bb_lower = cls._safe_float(latest.get("BB_Lower"), cls._safe_float(base_row.get("bb_lower"), max(0.01, close - (2 * atr))))
        bb_width = cls._safe_float(latest.get("BB_Width"), cls._safe_float(base_row.get("bb_width"), 0.0))
        volume_ratio = cls._safe_float(latest.get("Volume_Ratio"), cls._safe_float(base_row.get("volume_ratio"), 1.0))
        rsi = cls._safe_float(latest.get("RSI"), cls._safe_float(base_row.get("rsi"), 50.0))
        adx = cls._safe_float(latest.get("ADX"), cls._safe_float(base_row.get("adx"), 20.0))
        macd = cls._safe_float(latest.get("MACD"), cls._safe_float(base_row.get("macd"), 0.0))
        macd_signal = cls._safe_float(latest.get("MACD_Signal"), cls._safe_float(base_row.get("macd_signal"), 0.0))

        trend_score = 0
        trend_score += 35 if close > sma20 else 0
        trend_score += 35 if close > sma50 else 0
        trend_score += 30 if sma50 > sma200 else 0
        trend_score = int(min(100, max(0, trend_score)))
        momentum_score = int(min(100, max(0, ((rsi / 100.0) * 60.0) + (20.0 if macd > macd_signal else 0.0) + (20.0 if adx > 20 else 0.0))))
        atr_pct = (atr / close * 100.0) if close > 0 else 0.0
        volatility_score = int(min(100, max(0, 100.0 - abs(3.0 - atr_pct) * 20.0)))
        liquidity_score = 90 if volume > 1_000_000 else 75 if volume > 100_000 else 60

        out.update(
            {
                "ltp": close,
                "close": close,
                "high": high,
                "low": low,
                "volume": volume,
                "rsi": rsi,
                "adx": adx,
                "macd": macd,
                "macd_signal": macd_signal,
                "sma_20": sma20,
                "sma_50": sma50,
                "sma_200": sma200,
                "ema_9": ema9,
                "ema_21": ema21,
                "atr": atr,
                "bb_upper": bb_upper,
                "bb_middle": sma20,
                "bb_lower": bb_lower,
                "bb_width": bb_width,
                "trend_score": trend_score,
                "momentum_score": momentum_score,
                "volatility_score": volatility_score,
                "liquidity_score": liquidity_score,
                "volume_ratio": volume_ratio,
            }
        )
        return out

    def _predict_from_row(self, row: Dict) -> Tuple[float, float]:
        rr_ratio = 2.0
        atr = self._safe_float(row.get("atr"), 0.0)
        ltp = self._safe_float(row.get("ltp"), 0.0)
        if atr > 0 and ltp > 0:
            risk_pct = (atr / ltp) * 100.0
            if risk_pct > 0:
                rr_ratio = max(1.0, min(4.0, (2.0 * risk_pct) / risk_pct))

        feat = {
            "rsi": self._safe_float(row.get("rsi"), 50.0),
            "adx": self._safe_float(row.get("adx"), 20.0),
            "trend_score": self._safe_float(row.get("trend_score"), 50.0),
            "rr_ratio": rr_ratio,
            "rsi_oversold": 1 if self._safe_float(row.get("rsi"), 50.0) < 30 else 0,
            "rsi_overbought": 1 if self._safe_float(row.get("rsi"), 50.0) > 70 else 0,
            "adx_strong": 1 if self._safe_float(row.get("adx"), 20.0) > 30 else 0,
            "strong_trend": 1 if self._safe_float(row.get("trend_score"), 50.0) > 70 else 0,
            "is_intraday": 1,
            "rsi_adx": (self._safe_float(row.get("rsi"), 50.0) * self._safe_float(row.get("adx"), 20.0)) / 100.0,
        }
        ai_win = float(self.predictor.predict_win_prob(feat))
        ai_profit = float(self.predictor.predict_profit(feat))
        return ai_win, ai_profit

    def _backtest_strategies(
        self,
        ind_df: pd.DataFrame,
        hold_days: int = 5,
        symbol: str = "",
        timeframe: str = "day",
        max_trades_per_strategy: Optional[int] = None,
    ) -> Dict[str, Any]:
        rules = self._strategy_rules()
        rule_items = list(rules.items())
        stats = {
            name: {"trades": 0, "wins": 0, "sum_return": 0.0}
            for name in rules.keys()
        }
        trades_log: List[Dict[str, Any]] = []
        daily_once_strategies = {"opening_range_breakout"}
        traded_days: Dict[str, set] = {name: set() for name in rules.keys()}
        if ind_df.empty or len(ind_df) <= hold_days + 60:
            return {
                "stats": {k: {"trades": 0, "wins": 0, "win_rate": 0.5, "avg_return": 0.0, "sum_return": 0.0} for k in stats},
                "trades": [],
            }

        for i in range(60, len(ind_df) - hold_days):
            row = ind_df.iloc[i]
            entry = self._safe_float(row.get("close"), 0.0)
            if entry <= 0:
                continue
            row_day = pd.to_datetime(row.get("date"), errors="coerce")
            day_key = str(row_day.date()) if pd.notna(row_day) else f"idx_{i}"

            all_capped = True
            for strat, rule_fn in rule_items:
                if max_trades_per_strategy is not None and stats[strat]["trades"] >= max_trades_per_strategy:
                    continue
                all_capped = False
                if strat in daily_once_strategies and day_key in traded_days.get(strat, set()):
                    continue
                if rule_fn(row):
                    trade_result = self._simulate_trade_return(
                        ind_df=ind_df,
                        entry_idx=i,
                        hold_days=hold_days,
                        strategy=strat,
                    )
                    ret_pct = float(trade_result.get("return_pct", 0.0))
                    stats[strat]["trades"] += 1
                    stats[strat]["sum_return"] += ret_pct
                    if ret_pct > 0:
                        stats[strat]["wins"] += 1
                    trades_log.append(
                        {
                            "symbol": symbol,
                            "strategy_name": strat,
                            "timeframe": timeframe,
                            "entry_date": trade_result.get("entry_date"),
                            "exit_date": trade_result.get("exit_date"),
                            "holding_bars": int(trade_result.get("holding_bars", 0)),
                            "entry_price": float(trade_result.get("entry_price", 0.0)),
                            "exit_price": float(trade_result.get("exit_price", 0.0)),
                            "stop_loss": float(trade_result.get("stop_loss", 0.0)),
                            "target_price": float(trade_result.get("target_price", 0.0)),
                            "return_pct": ret_pct,
                            "outcome": trade_result.get("outcome", "flat"),
                        }
                    )
                    if strat in daily_once_strategies:
                        traded_days[strat].add(day_key)
            if all_capped:
                break

        out = {}
        for strat, agg in stats.items():
            trades = int(agg["trades"])
            wins = int(agg["wins"])
            win_rate = (wins / trades) if trades > 0 else 0.5
            avg_return = (float(agg["sum_return"]) / trades) if trades > 0 else 0.0
            out[strat] = {
                "trades": trades,
                "wins": wins,
                "win_rate": float(win_rate),
                "avg_return": float(avg_return),
                "sum_return": float(agg["sum_return"]),
            }
        return {"stats": out, "trades": trades_log}

    @classmethod
    def _simulate_trade_return(
        cls,
        ind_df: pd.DataFrame,
        entry_idx: int,
        hold_days: int,
        strategy: str,
    ) -> Dict[str, Any]:
        """
        Simulate return using stop/target intraperiod checks instead of only fixed close exit.
        """
        row = ind_df.iloc[entry_idx]
        entry = cls._safe_float(row.get("close"), 0.0)
        if entry <= 0:
            return {
                "return_pct": 0.0,
                "entry_price": 0.0,
                "exit_price": 0.0,
                "stop_loss": 0.0,
                "target_price": 0.0,
                "entry_date": None,
                "exit_date": None,
                "holding_bars": 0,
                "outcome": "flat",
            }

        atr = max(0.01, cls._safe_float(row.get("ATR"), entry * 0.01))
        if strategy in {"breakout", "volatility_squeeze", "range_breakout"}:
            sl_mult, tgt_mult = 1.0, 2.2
        elif strategy in {"mean_revert", "bollinger_revert", "macd_reversal"}:
            sl_mult, tgt_mult = 0.9, 1.5
        else:
            sl_mult, tgt_mult = 1.1, 2.0

        stop = max(0.01, entry - (atr * sl_mult))
        target = entry + (atr * tgt_mult)

        end_idx = min(len(ind_df) - 1, entry_idx + hold_days)
        actual_exit_idx = end_idx
        exit_price = cls._safe_float(ind_df.iloc[end_idx].get("close"), entry)

        for j in range(entry_idx + 1, end_idx + 1):
            rj = ind_df.iloc[j]
            open_px = cls._safe_float(rj.get("open"), cls._safe_float(rj.get("close"), exit_price))
            close_px = cls._safe_float(rj.get("close"), open_px)
            hi = cls._safe_float(rj.get("high"), cls._safe_float(rj.get("close"), exit_price))
            lo = cls._safe_float(rj.get("low"), cls._safe_float(rj.get("close"), exit_price))
            hit_stop = lo <= stop
            hit_target = hi >= target

            # If both stop and target are touched in the same daily candle,
            # use candle direction as a fair tie-breaker instead of always
            # assuming stop-loss first (which is overly pessimistic).
            if hit_stop and hit_target:
                exit_price = target if close_px >= open_px else stop
                actual_exit_idx = j
                break
            if hit_target:
                exit_price = target
                actual_exit_idx = j
                break
            if hit_stop:
                exit_price = stop
                actual_exit_idx = j
                break
            exit_price = cls._safe_float(rj.get("close"), exit_price)
            actual_exit_idx = j

        gross_ret = ((exit_price - entry) / entry) * 100.0
        # Strategy-aware round-trip friction (%) tuned for paper backtest realism.
        trading_cost_by_strategy = {
            "breakout": 0.12,
            "volatility_squeeze": 0.12,
            "range_breakout": 0.12,
            "donchian_breakout": 0.12,
            "volatility_expansion": 0.12,
            "opening_range_breakout": 0.12,
            "narrow_cpr_breakout": 0.12,
            "volume_breakout_consolidation": 0.12,
            "momentum": 0.10,
            "rsi_momentum": 0.10,
            "adx_trend_follow": 0.10,
            "trend_continuation": 0.10,
            "rvol_momentum": 0.10,
            "swing": 0.08,
            "trend_pullback": 0.08,
            "ema_crossover": 0.08,
            "breakout_retest": 0.08,
            "ema9_21_pullback": 0.08,
            "vwap_pullback": 0.08,
            "mean_revert": 0.09,
            "bollinger_revert": 0.09,
            "macd_reversal": 0.09,
            "prev_day_hl_break": 0.09,
            "ai_multi_timeframe_trend": 0.08,
            "ai_mean_reversion_pro": 0.09,
            "ai_breakout_master": 0.11,
            "ai_momentum_surge": 0.10,
            "ai_volatility_breakout": 0.11,
            "ai_triple_screen": 0.09,
            "ai_divergence_hunter": 0.09,
            "ai_channel_breakout": 0.11,
            "ai_fibonacci_retracement": 0.08,
            "ai_smart_grid": 0.08,
        }
        trading_cost = trading_cost_by_strategy.get(strategy, 0.10)
        net_return = gross_ret - trading_cost
        entry_dt = pd.to_datetime(row.get("date"), errors="coerce")
        exit_dt = pd.to_datetime(ind_df.iloc[actual_exit_idx].get("date"), errors="coerce")
        if net_return > 0:
            outcome = "win"
        elif net_return < 0:
            outcome = "loss"
        else:
            outcome = "flat"
        return {
            "return_pct": float(net_return),
            "entry_price": float(entry),
            "exit_price": float(exit_price),
            "stop_loss": float(stop),
            "target_price": float(target),
            "entry_date": entry_dt.date().isoformat() if pd.notna(entry_dt) else None,
            "exit_date": exit_dt.date().isoformat() if pd.notna(exit_dt) else None,
            "holding_bars": int(max(1, actual_exit_idx - entry_idx)),
            "outcome": outcome,
        }

    @classmethod
    def _strategy_signal(cls, row, strategy: str) -> bool:
        rule = cls._strategy_rules().get(strategy)
        if not rule:
            return False
        return bool(rule(row))

    @staticmethod
    def _strategy_rules() -> Dict[str, Callable]:
        """
        Strategy registry for backtesting.
        Add new strategies here; backtest loop picks them up automatically.
        """
        return {
            "ai_multi_timeframe_trend": ZerodhaClient._rule_ai_multi_timeframe_trend,
            "ai_mean_reversion_pro": ZerodhaClient._rule_ai_mean_reversion_pro,
            "ai_breakout_master": ZerodhaClient._rule_ai_breakout_master,
            "ai_momentum_surge": ZerodhaClient._rule_ai_momentum_surge,
            "ai_volatility_breakout": ZerodhaClient._rule_ai_volatility_breakout,
            "ai_triple_screen": ZerodhaClient._rule_ai_triple_screen,
            "ai_divergence_hunter": ZerodhaClient._rule_ai_divergence_hunter,
            "ai_channel_breakout": ZerodhaClient._rule_ai_channel_breakout,
            "ai_fibonacci_retracement": ZerodhaClient._rule_ai_fibonacci_retracement,
            "ai_smart_grid": ZerodhaClient._rule_ai_smart_grid,
            "vwap_pullback": ZerodhaClient._rule_vwap_pullback,
        }

    @classmethod
    def _rule_opening_range_breakout(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        or_high = cls._safe_float(row.get("OR_15_High"), 0.0)
        or_low = cls._safe_float(row.get("OR_15_Low"), 0.0)
        bars_from_open = cls._safe_float(row.get("Bars_From_Open"), 999.0)
        if close <= 0 or or_high <= 0 or or_low <= 0:
            return False
        if bars_from_open <= 3:
            return False
        return close > or_high or close < or_low

    @classmethod
    def _rule_vwap_pullback(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        open_px = cls._safe_float(row.get("open"), close)
        low = cls._safe_float(row.get("low"), close)
        high = cls._safe_float(row.get("high"), close)
        vwap = cls._safe_float(row.get("VWAP"), close)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        if close <= 0 or vwap <= 0:
            return False
        long_setup = close > vwap and low <= vwap and close > open_px and adx >= 15
        short_setup = close < vwap and high >= vwap and close < open_px and adx >= 15
        return long_setup or short_setup

    @classmethod
    def _rule_narrow_cpr_breakout(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        cpr_high = cls._safe_float(row.get("CPR_High"), 0.0)
        cpr_low = cls._safe_float(row.get("CPR_Low"), 0.0)
        narrow = bool(row.get("Narrow_CPR", False))
        if close <= 0 or cpr_high <= 0 or cpr_low <= 0 or not narrow:
            return False
        return close > cpr_high or close < cpr_low

    @classmethod
    def _rule_volume_breakout_consolidation(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        cons_high = cls._safe_float(row.get("Consolidation_High"), 0.0)
        cons_low = cls._safe_float(row.get("Consolidation_Low"), 0.0)
        tight = bool(row.get("Consolidation_Tight", False))
        rvol = cls._safe_float(row.get("RVOL"), cls._safe_float(row.get("Volume_Ratio"), 1.0))
        if close <= 0 or cons_high <= 0 or cons_low <= 0 or not tight:
            return False
        breakout_up = close > cons_high and rvol >= 2.0
        breakout_down = close < cons_low and rvol >= 2.0
        return breakout_up or breakout_down

    @classmethod
    def _rule_ema9_21_pullback(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        open_px = cls._safe_float(row.get("open"), close)
        low = cls._safe_float(row.get("low"), close)
        high = cls._safe_float(row.get("high"), close)
        ema9 = cls._safe_float(row.get("EMA_9"), close)
        ema21 = cls._safe_float(row.get("EMA_21"), close)
        if close <= 0:
            return False
        long_setup = ema9 > ema21 and low <= max(ema9, ema21) and close > open_px
        short_setup = ema9 < ema21 and high >= min(ema9, ema21) and close < open_px
        return long_setup or short_setup

    @classmethod
    def _rule_rvol_momentum(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        rvol = cls._safe_float(row.get("RVOL"), cls._safe_float(row.get("Volume_Ratio"), 1.0))
        gap_pct = cls._safe_float(row.get("Gap_Pct"), 0.0)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        ema9 = cls._safe_float(row.get("EMA_9"), close)
        if close <= 0:
            return False
        strong_up = rvol > 2.0 and (gap_pct > 0.5 or close > ema9) and adx >= 18
        strong_down = rvol > 2.0 and (gap_pct < -0.5 or close < ema9) and adx >= 18
        return strong_up or strong_down

    @classmethod
    def _rule_prev_day_hl_break(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        prev_high = cls._safe_float(row.get("Prev_Day_High"), 0.0)
        prev_low = cls._safe_float(row.get("Prev_Day_Low"), 0.0)
        if close <= 0 or prev_high <= 0 or prev_low <= 0:
            return False
        return close > prev_high or close < prev_low

    @classmethod
    def _rule_ai_multi_timeframe_trend(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        sma20 = cls._safe_float(row.get("SMA_20"), close)
        sma50 = cls._safe_float(row.get("SMA_50"), close)
        sma200 = cls._safe_float(row.get("SMA_200"), close)
        rsi = cls._safe_float(row.get("RSI"), 50.0)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        macd = cls._safe_float(row.get("MACD"), 0.0)
        macd_signal = cls._safe_float(row.get("MACD_Signal"), 0.0)
        volume_ratio = cls._safe_float(row.get("Volume_Ratio"), 1.0)
        return (
            close > sma20 > sma50 > sma200
            and adx > 25
            and 50 < rsi < 70
            and macd > macd_signal
            and volume_ratio > 1.0
        )

    @classmethod
    def _rule_ai_mean_reversion_pro(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        rsi = cls._safe_float(row.get("RSI"), 50.0)
        will_r = cls._safe_float(row.get("Williams_R"), -50.0)
        stoch_k = cls._safe_float(row.get("Stoch_K"), 50.0)
        bb_lower = cls._safe_float(row.get("BB_Lower"), close)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        sma200 = cls._safe_float(row.get("SMA_200"), close)
        return (
            close > 0
            and rsi < 30
            and will_r < -80
            and stoch_k < 20
            and close < bb_lower
            and adx < 25
            and close > sma200
        )

    @classmethod
    def _rule_ai_breakout_master(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        high = cls._safe_float(row.get("high"), close)
        bb_width = cls._safe_float(row.get("BB_Width"), 0.0)
        rsi = cls._safe_float(row.get("RSI"), 50.0)
        volume_ratio = cls._safe_float(row.get("Volume_Ratio"), 1.0)
        # Approximate squeeze threshold for row-level screening.
        squeeze = bb_width <= 8.0
        breakout = close > high * 0.997
        return close > 0 and squeeze and breakout and volume_ratio > 1.5 and rsi > 60

    @classmethod
    def _rule_ai_momentum_surge(cls, row) -> bool:
        rsi = cls._safe_float(row.get("RSI"), 50.0)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        macd_hist = cls._safe_float(row.get("MACD_Hist"), 0.0)
        aroon_up = cls._safe_float(row.get("Aroon_Up"), 50.0)
        close = cls._safe_float(row.get("close"), 0.0)
        ema20 = cls._safe_float(row.get("EMA_20"), close)
        volume_ratio = cls._safe_float(row.get("Volume_Ratio"), 1.0)
        return (
            60 < rsi < 80
            and adx > 30
            and macd_hist > 0
            and aroon_up > 70
            and close > ema20
            and volume_ratio > 1.2
        )

    @classmethod
    def _rule_ai_volatility_breakout(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        atr = cls._safe_float(row.get("ATR"), 0.0)
        rsi = cls._safe_float(row.get("RSI"), 50.0)
        keltner_upper = cls._safe_float(row.get("Keltner_Upper"), close)
        volatility_regime = int(cls._safe_float(row.get("Volatility_Regime"), 2))
        return close > 0 and volatility_regime == 1 and atr > 0 and close > keltner_upper and rsi > 55

    @classmethod
    def _rule_ai_triple_screen(cls, row) -> bool:
        ema50 = cls._safe_float(row.get("EMA_50"), 0.0)
        ema200 = cls._safe_float(row.get("EMA_200"), 0.0)
        stoch_k = cls._safe_float(row.get("Stoch_K"), 50.0)
        rsi = cls._safe_float(row.get("RSI"), 50.0)
        close = cls._safe_float(row.get("close"), 0.0)
        ema5 = cls._safe_float(row.get("EMA_5"), close)
        volume_ratio = cls._safe_float(row.get("Volume_Ratio"), 1.0)
        return ema50 > ema200 and stoch_k < 30 and rsi < 40 and close > ema5 and volume_ratio > 1.1

    @classmethod
    def _rule_ai_divergence_hunter(cls, row) -> bool:
        # Approximated with oversold reversal context in row-level backtests.
        rsi = cls._safe_float(row.get("RSI"), 50.0)
        volume_ratio = cls._safe_float(row.get("Volume_Ratio"), 1.0)
        macd_hist = cls._safe_float(row.get("MACD_Hist"), 0.0)
        return rsi < 35 and macd_hist >= -0.05 and volume_ratio >= 1.0

    @classmethod
    def _rule_ai_channel_breakout(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        high = cls._safe_float(row.get("high"), close)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        volume_ratio = cls._safe_float(row.get("Volume_Ratio"), 1.0)
        return close > 0 and close > high * 0.997 and adx > 20 and volume_ratio > 1.1

    @classmethod
    def _rule_ai_fibonacci_retracement(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        sma200 = cls._safe_float(row.get("SMA_200"), close)
        rsi = cls._safe_float(row.get("RSI"), 50.0)
        volume_ratio = cls._safe_float(row.get("Volume_Ratio"), 1.0)
        return close > sma200 and 40 <= rsi <= 60 and volume_ratio > 0.9

    @classmethod
    def _rule_ai_smart_grid(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        atr = cls._safe_float(row.get("ATR"), 0.0)
        sma50 = cls._safe_float(row.get("SMA_50"), close)
        rsi = cls._safe_float(row.get("RSI"), 50.0)
        volume_ratio = cls._safe_float(row.get("Volume_Ratio"), 1.0)
        if close <= 0 or atr <= 0:
            return False
        grid_size = atr * 1.5
        support_zone = (close % grid_size) < (0.2 * grid_size) if grid_size > 0 else False
        return support_zone and 45 <= rsi <= 65 and volume_ratio > 0.8 and close > sma50

    @classmethod
    def _rule_momentum(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        rsi = cls._safe_float(row.get("RSI"), 50.0)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        macd = cls._safe_float(row.get("MACD"), 0.0)
        macd_signal = cls._safe_float(row.get("MACD_Signal"), 0.0)
        sma20 = cls._safe_float(row.get("SMA_20"), close)
        sma50 = cls._safe_float(row.get("SMA_50"), close)
        return close > sma20 and sma20 > sma50 and rsi >= 55 and adx >= 22 and macd > macd_signal

    @classmethod
    def _rule_breakout(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        sma20 = cls._safe_float(row.get("SMA_20"), close)
        bb_width_raw = cls._safe_float(row.get("BB_Width"), 0.0)
        bb_width = bb_width_raw / 100.0 if bb_width_raw > 1 else bb_width_raw
        volume_ratio = cls._safe_float(row.get("Volume_Ratio"), 1.0)
        return close > sma20 and bb_width <= 0.035 and volume_ratio >= 1.1 and adx >= 18

    @classmethod
    def _rule_swing(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        rsi = cls._safe_float(row.get("RSI"), 50.0)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        sma50 = cls._safe_float(row.get("SMA_50"), close)
        sma200 = cls._safe_float(row.get("SMA_200"), close)
        return close > sma50 and sma50 >= sma200 and 40 <= rsi <= 65 and adx >= 16

    @classmethod
    def _rule_mean_revert(cls, row) -> bool:
        rsi = cls._safe_float(row.get("RSI"), 50.0)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        return rsi <= 35 and adx <= 22

    @classmethod
    def _rule_trend_pullback(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        rsi = cls._safe_float(row.get("RSI"), 50.0)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        sma50 = cls._safe_float(row.get("SMA_50"), close)
        sma200 = cls._safe_float(row.get("SMA_200"), close)
        return close > sma50 and sma50 > sma200 and 42 <= rsi <= 55 and adx >= 18

    @classmethod
    def _rule_ema_crossover(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        ema9 = cls._safe_float(row.get("EMA_9"), close)
        ema21 = cls._safe_float(row.get("EMA_21"), close)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        return ema9 > ema21 and close > ema21 and adx >= 18

    @classmethod
    def _rule_macd_reversal(cls, row) -> bool:
        macd = cls._safe_float(row.get("MACD"), 0.0)
        macd_signal = cls._safe_float(row.get("MACD_Signal"), 0.0)
        rsi = cls._safe_float(row.get("RSI"), 50.0)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        return macd > macd_signal and 35 <= rsi <= 55 and adx <= 25

    @classmethod
    def _rule_volatility_squeeze(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        sma20 = cls._safe_float(row.get("SMA_20"), close)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        bb_width_raw = cls._safe_float(row.get("BB_Width"), 0.0)
        bb_width = bb_width_raw / 100.0 if bb_width_raw > 1 else bb_width_raw
        volume_ratio = cls._safe_float(row.get("Volume_Ratio"), 1.0)
        return bb_width <= 0.02 and close >= sma20 and volume_ratio >= 1.15 and adx >= 15

    @classmethod
    def _rule_range_breakout(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        high = cls._safe_float(row.get("high"), close)
        low = cls._safe_float(row.get("low"), close)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        volume_ratio = cls._safe_float(row.get("Volume_Ratio"), 1.0)
        if close <= 0:
            return False
        range_pct = ((high - low) / close) * 100.0
        return range_pct >= 1.2 and volume_ratio >= 1.2 and adx >= 16

    @classmethod
    def _rule_rsi_momentum(cls, row) -> bool:
        rsi = cls._safe_float(row.get("RSI"), 50.0)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        macd = cls._safe_float(row.get("MACD"), 0.0)
        macd_signal = cls._safe_float(row.get("MACD_Signal"), 0.0)
        return rsi >= 60 and adx >= 20 and macd > macd_signal

    @classmethod
    def _rule_adx_trend_follow(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        sma20 = cls._safe_float(row.get("SMA_20"), close)
        sma50 = cls._safe_float(row.get("SMA_50"), close)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        return close > sma20 and sma20 > sma50 and adx >= 28

    @classmethod
    def _rule_bollinger_revert(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        bb_lower = cls._safe_float(row.get("BB_Lower"), close)
        rsi = cls._safe_float(row.get("RSI"), 50.0)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        return close <= bb_lower * 1.01 and rsi <= 35 and adx <= 22

    @classmethod
    def _rule_donchian_breakout(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        high = cls._safe_float(row.get("high"), close)
        low = cls._safe_float(row.get("low"), close)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        volume_ratio = cls._safe_float(row.get("Volume_Ratio"), 1.0)
        atr = cls._safe_float(row.get("ATR"), 0.0)
        if close <= 0:
            return False
        range_pct = ((high - low) / close) * 100.0 if close > 0 else 0.0
        atr_pct = (atr / close) * 100.0 if close > 0 else 0.0
        return adx >= 20 and volume_ratio >= 1.15 and range_pct >= 1.2 and atr_pct >= 1.0

    @classmethod
    def _rule_breakout_retest(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        sma20 = cls._safe_float(row.get("SMA_20"), close)
        ema21 = cls._safe_float(row.get("EMA_21"), close)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        rsi = cls._safe_float(row.get("RSI"), 50.0)
        volume_ratio = cls._safe_float(row.get("Volume_Ratio"), 1.0)
        pullback_ok = abs(close - sma20) / close <= 0.015 if close > 0 else False
        return close >= ema21 and pullback_ok and adx >= 18 and 45 <= rsi <= 65 and volume_ratio >= 1.0

    @classmethod
    def _rule_trend_continuation(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        ema9 = cls._safe_float(row.get("EMA_9"), close)
        ema21 = cls._safe_float(row.get("EMA_21"), close)
        sma50 = cls._safe_float(row.get("SMA_50"), close)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        rsi = cls._safe_float(row.get("RSI"), 50.0)
        return ema9 >= ema21 >= sma50 and close >= ema9 and adx >= 22 and 52 <= rsi <= 72

    @classmethod
    def _rule_volatility_expansion(cls, row) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        bb_width_raw = cls._safe_float(row.get("BB_Width"), 0.0)
        bb_width = bb_width_raw / 100.0 if bb_width_raw > 1 else bb_width_raw
        atr = cls._safe_float(row.get("ATR"), 0.0)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        volume_ratio = cls._safe_float(row.get("Volume_Ratio"), 1.0)
        atr_pct = (atr / close) * 100.0 if close > 0 else 0.0
        return bb_width >= 0.02 and atr_pct >= 1.1 and adx >= 18 and volume_ratio >= 1.1

    @staticmethod
    def _pick_best_strategy(backtest: Dict[str, Dict]) -> Tuple[str, Dict]:
        best_name = "none"
        best_score = -1e9
        best_info = {"trades": 0, "wins": 0, "win_rate": 0.5, "avg_return": 0.0, "sum_return": 0.0}
        for name, info in backtest.items():
            trades = int(info.get("trades", 0))
            win_rate = float(info.get("win_rate", 0.5))
            avg_return = float(info.get("avg_return", 0.0))
            consistency = min(20.0, trades * 0.2)
            accuracy_component = (win_rate - 0.5) * 120.0
            return_component = avg_return * 8.0
            score = accuracy_component + return_component + consistency
            if trades < 8:
                score -= (8 - trades) * 3.0
            if avg_return < 0:
                score -= 10.0
            if score > best_score:
                best_score = score
                best_name = name
                best_info = info

        min_trades = 8
        min_win_rate = 0.50
        min_avg_return = 0.02
        if (
            int(best_info.get("trades", 0)) < min_trades
            or float(best_info.get("win_rate", 0.0)) < min_win_rate
            or float(best_info.get("avg_return", 0.0)) < min_avg_return
        ):
            return "none", best_info

        return best_name, best_info

    @staticmethod
    def _persist_strategy_backtest_rollup(cur, global_stats: Dict[str, Dict], period_start: str, period_end: str):
        for strategy, agg in global_stats.items():
            trades = int(agg["trades"])
            wins = int(agg["wins"])
            losses = max(0, trades - wins)
            win_rate = (wins / trades) if trades > 0 else 0.0
            avg_return = (float(agg["sum_return"]) / trades) if trades > 0 else 0.0
            total_return = float(agg["sum_return"])
            cur.execute(
                """
                INSERT OR REPLACE INTO strategy_performance
                (
                    strategy_name, period_start, period_end, total_trades,
                    winning_trades, losing_trades, win_rate, avg_return, total_return,
                    max_drawdown, sharpe_ratio, profit_factor, best_market_regime,
                    worst_market_regime, avg_holding_period, is_active, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    strategy,
                    period_start,
                    period_end,
                    trades,
                    wins,
                    losses,
                    win_rate,
                    avg_return,
                    total_return,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    1,
                ),
            )

    @staticmethod
    def _persist_backtest_trades(cur, run_id: str, trades: List[Dict[str, Any]]):
        if not trades:
            return
        rows = []
        for t in trades:
            if not t.get("symbol") or not t.get("strategy_name"):
                continue
            rows.append(
                (
                    run_id,
                    str(t.get("symbol", "")).upper(),
                    str(t.get("strategy_name", "")),
                    str(t.get("timeframe", "day")),
                    t.get("entry_date"),
                    t.get("exit_date"),
                    int(t.get("holding_bars", 0)),
                    float(t.get("entry_price", 0.0)),
                    float(t.get("exit_price", 0.0)),
                    float(t.get("stop_loss", 0.0)),
                    float(t.get("target_price", 0.0)),
                    float(t.get("return_pct", 0.0)),
                    str(t.get("outcome", "flat")),
                )
            )
        if not rows:
            return
        cur.executemany(
            """
            INSERT INTO backtest_trades (
                run_id, symbol, strategy_name, timeframe, entry_date, exit_date,
                holding_bars, entry_price, exit_price, stop_loss, target_price, return_pct, outcome
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    @staticmethod
    def _build_instrument_resolution_maps(instruments: List[Dict]) -> Tuple[Dict[str, int], Dict[str, str]]:
        """
        Build maps to resolve loaded symbols to Zerodha tradingsymbols.
        Handles SME-style suffixes such as '-SM' and '-BE'.
        """
        token_by_tradingsymbol: Dict[str, int] = {}
        base_candidates: Dict[str, Optional[str]] = {}

        for row in instruments:
            tradingsymbol = str(row.get("tradingsymbol", "")).strip().upper()
            token = row.get("instrument_token")
            if not tradingsymbol or not token:
                continue

            token_by_tradingsymbol[tradingsymbol] = int(token)

            base = tradingsymbol.split("-", 1)[0]
            if base not in base_candidates:
                base_candidates[base] = tradingsymbol
            elif base_candidates[base] != tradingsymbol:
                base_candidates[base] = None

        alias_to_tradingsymbol: Dict[str, str] = {}
        for base, mapped in base_candidates.items():
            if mapped and base not in token_by_tradingsymbol:
                alias_to_tradingsymbol[base] = mapped

        return token_by_tradingsymbol, alias_to_tradingsymbol

    @staticmethod
    def _resolve_to_tradingsymbol(
        symbol: str,
        token_by_tradingsymbol: Dict[str, int],
        alias_to_tradingsymbol: Dict[str, str],
    ) -> str:
        if symbol in token_by_tradingsymbol:
            return symbol
        return alias_to_tradingsymbol.get(symbol, "")
