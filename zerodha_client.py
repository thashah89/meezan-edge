"""
Zerodha (Kite) client wrapper for data-only operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Dict, List, Optional, Tuple
import logging
import pandas as pd

try:
    from kiteconnect import KiteConnect
except ImportError:  # pragma: no cover
    KiteConnect = None

from database_schema import get_connection
from utils_indicators import add_indicators

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
                    cur.execute(
                        """
                        INSERT OR REPLACE INTO stock_metrics
                        (
                            symbol, date, ltp, open, high, low, close, volume,
                            rsi, adx, macd, macd_signal,
                            sma_20, sma_50, sma_200, ema_9, ema_21,
                            atr, bb_upper, bb_middle, bb_lower, bb_width, trend_score,
                            momentum_score, volatility_score, liquidity_score,
                            volume_ratio, win_probability, expected_return,
                            strategy_fit, confidence, updated_at
                        )
                        VALUES
                        (
                            ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?,
                            ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?,
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
