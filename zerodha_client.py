"""
Zerodha (Kite) client wrapper for data-only operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Dict, List, Optional, Tuple
import logging
import pandas as pd
import numpy as np

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
        quotes = self.fetch_quotes(symbols)
        today = date.today().isoformat()
        instrument_token_by_symbol: Dict[str, int] = {}
        try:
            instruments = self.kite.instruments("NSE")
            for row in instruments:
                tradingsymbol = self.normalize_symbol(str(row.get("tradingsymbol", "")))
                token = row.get("instrument_token")
                if tradingsymbol and token:
                    instrument_token_by_symbol[tradingsymbol] = int(token)
        except Exception as exc:
            log.warning("Could not preload instruments for indicator enrichment: %s", exc)

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

                q = quotes.get(symbol)
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
                    token = instrument_token_by_symbol.get(symbol)
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
                            strategy_fit, confidence, updated_at
                        )
                        VALUES
                        (
                            ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?,
                            ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, CURRENT_TIMESTAMP
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
        global_stats = {
            "momentum": {"trades": 0, "wins": 0, "sum_return": 0.0},
            "breakout": {"trades": 0, "wins": 0, "sum_return": 0.0},
            "swing": {"trades": 0, "wins": 0, "sum_return": 0.0},
            "mean_revert": {"trades": 0, "wins": 0, "sum_return": 0.0},
        }

        instrument_token_by_symbol: Dict[str, int] = {}
        instruments = self.kite.instruments("NSE")
        for row in instruments:
            tradingsymbol = self.normalize_symbol(str(row.get("tradingsymbol", "")))
            token = row.get("instrument_token")
            if tradingsymbol and token:
                instrument_token_by_symbol[tradingsymbol] = int(token)

        conn = get_connection()
        cur = conn.cursor()
        total = len(symbols)
        processed = 0

        try:
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
                    failed_symbols += 1
                    failures.append((symbol, "Instrument token not found"))
                    status = "missing_token"
                    processed += 1
                    if progress_cb:
                        progress_cb(processed, total, symbol, status)
                    continue

                try:
                    candles = self.kite.historical_data(
                        instrument_token=token,
                        from_date=from_date,
                        to_date=date.today(),
                        interval="day",
                    )
                    if not candles:
                        raise ValueError("No historical candles")
                    hist_df = pd.DataFrame(candles)
                    if hist_df.empty or len(hist_df) < 80:
                        raise ValueError("Insufficient historical candles")

                    ind_df = add_indicators(hist_df)
                    if ind_df.empty or len(ind_df) < 80:
                        raise ValueError("Indicator enrichment failed")

                    backtest = self._backtest_strategies(ind_df, hold_days=hold_days)
                    for s_name, s_data in backtest.items():
                        global_stats[s_name]["trades"] += int(s_data["trades"])
                        global_stats[s_name]["wins"] += int(s_data["wins"])
                        global_stats[s_name]["sum_return"] += float(s_data["sum_return"])

                    best_strategy, best_info = self._pick_best_strategy(backtest)

                    latest = ind_df.iloc[-1]
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

                    if best_strategy == "none":
                        final_strategy = determine_strategy_fit(enriched)
                    else:
                        final_strategy = best_strategy

                    enriched["win_probability"] = max(0.01, min(0.99, float(final_win)))
                    enriched["expected_return"] = float(final_profit)
                    enriched["confidence"] = float(final_confidence)
                    enriched["strategy_fit"] = final_strategy
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
                            confidence = ?, opportunity_score = ?, updated_at = CURRENT_TIMESTAMP
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
            "updated_symbols": updated_symbols,
            "failed_symbols": failed_symbols,
            "failures": failures,
            "strategy_distribution": strategy_distribution,
        }

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

        if trend_score >= 70 and adx >= 25:
            strategy_fit = "momentum"
        elif bb_width < 0.02 and volume_ratio >= 1.1:
            strategy_fit = "breakout"
        elif trend_score >= 55:
            strategy_fit = "swing"
        elif rsi <= 35 and adx < 20:
            strategy_fit = "mean_revert"
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
        }

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

    def _backtest_strategies(self, ind_df: pd.DataFrame, hold_days: int = 5) -> Dict[str, Dict]:
        stats = {
            "momentum": {"trades": 0, "wins": 0, "sum_return": 0.0},
            "breakout": {"trades": 0, "wins": 0, "sum_return": 0.0},
            "swing": {"trades": 0, "wins": 0, "sum_return": 0.0},
            "mean_revert": {"trades": 0, "wins": 0, "sum_return": 0.0},
        }
        if ind_df.empty or len(ind_df) <= hold_days + 60:
            return {k: {"trades": 0, "wins": 0, "win_rate": 0.5, "avg_return": 0.0, "sum_return": 0.0} for k in stats}

        for i in range(60, len(ind_df) - hold_days):
            row = ind_df.iloc[i]
            entry = self._safe_float(row.get("close"), 0.0)
            if entry <= 0:
                continue
            exit_price = self._safe_float(ind_df.iloc[i + hold_days].get("close"), entry)
            ret_pct = ((exit_price - entry) / entry) * 100.0

            for strat in stats.keys():
                if self._strategy_signal(row, strat):
                    stats[strat]["trades"] += 1
                    stats[strat]["sum_return"] += ret_pct
                    if ret_pct > 0:
                        stats[strat]["wins"] += 1

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
        return out

    @classmethod
    def _strategy_signal(cls, row, strategy: str) -> bool:
        close = cls._safe_float(row.get("close"), 0.0)
        rsi = cls._safe_float(row.get("RSI"), 50.0)
        adx = cls._safe_float(row.get("ADX"), 20.0)
        macd = cls._safe_float(row.get("MACD"), 0.0)
        macd_signal = cls._safe_float(row.get("MACD_Signal"), 0.0)
        sma20 = cls._safe_float(row.get("SMA_20"), close)
        sma50 = cls._safe_float(row.get("SMA_50"), close)
        sma200 = cls._safe_float(row.get("SMA_200"), close)
        bb_width_raw = cls._safe_float(row.get("BB_Width"), 0.0)
        bb_width = bb_width_raw / 100.0 if bb_width_raw > 1 else bb_width_raw
        volume_ratio = cls._safe_float(row.get("Volume_Ratio"), 1.0)

        if strategy == "momentum":
            return close > sma20 and sma20 > sma50 and rsi >= 55 and adx >= 22 and macd > macd_signal
        if strategy == "breakout":
            return close > sma20 and bb_width <= 0.035 and volume_ratio >= 1.1 and adx >= 18
        if strategy == "swing":
            return close > sma50 and sma50 >= sma200 and 40 <= rsi <= 65 and adx >= 16
        if strategy == "mean_revert":
            return rsi <= 35 and adx <= 22
        return False

    @staticmethod
    def _pick_best_strategy(backtest: Dict[str, Dict]) -> Tuple[str, Dict]:
        best_name = "none"
        best_score = -1e9
        best_info = {"trades": 0, "wins": 0, "win_rate": 0.5, "avg_return": 0.0, "sum_return": 0.0}
        for name, info in backtest.items():
            trades = int(info.get("trades", 0))
            win_rate = float(info.get("win_rate", 0.5))
            avg_return = float(info.get("avg_return", 0.0))
            confidence_bonus = min(0.15, trades / 200.0)
            score = (win_rate * 100.0) + (avg_return * 5.0) + (confidence_bonus * 100.0)
            if trades < 5:
                score -= 12.0
            if score > best_score:
                best_score = score
                best_name = name
                best_info = info
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
