"""
zerodha_auth.py – Complete Zerodha Kite Connect authentication handler.

Covers:
  1. Login URL builder           → sends user to Zerodha login page
  2. URL token reader            → reads request_token Zerodha posts back to your app URL
  3. Session generator           → exchanges request_token → access_token
  4. Token cache                 → saves token to file so you only login once per day
  5. Kite instance factory       → returns an authenticated KiteConnect object
  6. Data fetchers               → historical + live price using Kite API
  7. Order placer                → place / modify / cancel orders via Kite API
  8. Postback handler            → parses order-update POST from Zerodha

Usage in app.py (Streamlit):
    from zerodha_auth import ZerodhaSession
    zs = ZerodhaSession()
    if not zs.is_authenticated():
        st.markdown(f"[Login with Zerodha]({zs.login_url()})")
        zs.handle_redirect()   # reads ?request_token= from the current URL
    else:
        kite = zs.kite()
"""

import json
import os
import logging
from datetime import datetime, date, timedelta

import pandas as pd

from config import (
    ZERODHA_API_KEY, ZERODHA_API_SECRET,
    ZERODHA_REDIRECT_URL, ZERODHA_POSTBACK_URL,
    ZERODHA_TOKEN_FILE,
)
from market_data import add_indicators

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  DEPENDENCY GUARD
# ══════════════════════════════════════════════════════════════════════════════

def _kite_available() -> bool:
    try:
        import kiteconnect  # noqa
        return True
    except ImportError:
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  TOKEN CACHE  (file-based, survives app restarts within the same day)
# ══════════════════════════════════════════════════════════════════════════════

def _save_token(api_key: str, access_token: str, public_token: str = "") -> None:
    payload = {
        "api_key":      api_key,
        "access_token": access_token,
        "public_token": public_token,
        "login_date":   date.today().isoformat(),
    }
    with open(ZERODHA_TOKEN_FILE, "w") as f:
        json.dump(payload, f, indent=2)
    log.info(f"Token saved to {ZERODHA_TOKEN_FILE}")


def _load_token() -> dict | None:
    """
    Load cached token.  Returns None if:
      • file doesn't exist
      • token is from a previous day (Zerodha tokens expire at 6 AM next day)
    """
    if not os.path.exists(ZERODHA_TOKEN_FILE):
        return None
    try:
        with open(ZERODHA_TOKEN_FILE) as f:
            data = json.load(f)
        if data.get("login_date") != date.today().isoformat():
            log.info("Cached token is from a previous day — re-login required.")
            return None
        return data
    except Exception as e:
        log.warning(f"Could not read token cache: {e}")
        return None


def _clear_token() -> None:
    if os.path.exists(ZERODHA_TOKEN_FILE):
        os.remove(ZERODHA_TOKEN_FILE)
        log.info("Token cache cleared.")


# ══════════════════════════════════════════════════════════════════════════════
#  ZERODHA SESSION  (main class)
# ══════════════════════════════════════════════════════════════════════════════

class ZerodhaSession:
    """
    Manages the full Zerodha Kite Connect auth lifecycle inside a Streamlit app.

    Quick-start:
        zs = ZerodhaSession()

        # Step 1 — show login button if not authenticated
        if not zs.is_authenticated():
            url = zs.login_url()
            st.markdown(f'<a href="{url}" target="_self">Login with Zerodha</a>',
                        unsafe_allow_html=True)
            # Step 2 — after redirect, read token from URL automatically
            zs.handle_redirect()
        else:
            kite = zs.kite()   # ready to use
    """

    def __init__(self):
        self._kite_obj = None
        self._access_token: str | None = None
        self._credentials_ok = bool(ZERODHA_API_KEY and ZERODHA_API_SECRET)

        # Try loading a cached token immediately
        cached = _load_token()
        if cached and cached.get("access_token"):
            self._access_token = cached["access_token"]
            if _kite_available():
                self._init_kite(self._access_token)

    # ── CREDENTIAL CHECK ───────────────────────────────────────────────────────

    def credentials_configured(self) -> bool:
        """True when API key + secret are filled in config.py."""
        return self._credentials_ok

    def is_authenticated(self) -> bool:
        """True when a valid access_token exists for today."""
        return self._access_token is not None

    # ── STEP 1: BUILD LOGIN URL ────────────────────────────────────────────────

    def login_url(self) -> str:
        """
        Returns the Zerodha login URL.
        User opens this in browser → logs in → Zerodha redirects back to
        ZERODHA_REDIRECT_URL?request_token=XXXX&status=success
        """
        if not self._credentials_ok:
            raise ValueError(
                "ZERODHA_API_KEY and ZERODHA_API_SECRET must be set in config.py"
            )
        if _kite_available():
            from kiteconnect import KiteConnect
            kite = KiteConnect(api_key=ZERODHA_API_KEY)
            return kite.login_url()
        else:
            # Fallback URL without SDK
            return (
                f"https://kite.zerodha.com/connect/login"
                f"?v=3&api_key={ZERODHA_API_KEY}"
            )

    # ── STEP 2: READ request_token FROM REDIRECT URL ───────────────────────────

    def handle_redirect(self) -> bool:
        """
        Call this on every Streamlit page load.

        Streamlit reads the current browser URL query params via
        st.query_params.  After Zerodha redirects the user back,
        the URL looks like:
            http://127.0.0.1:8501?request_token=XXXX&status=success

        This method:
          • reads the request_token from the URL
          • exchanges it for an access_token
          • saves the token to cache
          • clears the query params from the URL (clean address bar)
          • returns True on success

        Must be called from inside a Streamlit script (needs st.query_params).
        """
        import streamlit as st

        params = st.query_params
        request_token = params.get("request_token", None)
        status        = params.get("status", "")

        if not request_token:
            return False   # no redirect happened yet

        if status != "success":
            st.error(f"Zerodha login failed. Status: {status}")
            st.query_params.clear()
            return False

        # Exchange request_token → access_token
        try:
            access_token, public_token = self._generate_session(request_token)
            self._access_token = access_token
            _save_token(ZERODHA_API_KEY, access_token, public_token)
            self._init_kite(access_token)

            # Clean the URL (remove ?request_token=... from address bar)
            st.query_params.clear()
            log.info("Zerodha authentication successful.")
            return True

        except Exception as e:
            st.error(f"Token exchange failed: {e}")
            st.query_params.clear()
            return False

    def _generate_session(self, request_token: str) -> tuple[str, str]:
        """Exchange request_token for access_token using Kite SDK or raw HTTPS."""
        if _kite_available():
            from kiteconnect import KiteConnect
            import hashlib
            kite = KiteConnect(api_key=ZERODHA_API_KEY)
            data = kite.generate_session(request_token,
                                          api_secret=ZERODHA_API_SECRET)
            return data["access_token"], data.get("public_token", "")
        else:
            # Raw HTTPS fallback (no SDK installed)
            import requests, hashlib
            checksum = hashlib.sha256(
                f"{ZERODHA_API_KEY}{request_token}{ZERODHA_API_SECRET}".encode()
            ).hexdigest()
            r = requests.post(
                "https://api.kite.trade/session/token",
                data={
                    "api_key":       ZERODHA_API_KEY,
                    "request_token": request_token,
                    "checksum":      checksum,
                },
                timeout=15,
            )
            r.raise_for_status()
            d = r.json()["data"]
            return d["access_token"], d.get("public_token", "")

    # ── KITE OBJECT ────────────────────────────────────────────────────────────

    def _init_kite(self, access_token: str) -> None:
        if _kite_available():
            from kiteconnect import KiteConnect
            kite = KiteConnect(api_key=ZERODHA_API_KEY)
            kite.set_access_token(access_token)
            self._kite_obj = kite

    def kite(self):
        """Return the authenticated KiteConnect object (or None)."""
        return self._kite_obj

    def logout(self) -> None:
        """Clear token and reset session."""
        if self._kite_obj:
            try:
                self._kite_obj.invalidate_access_token()
            except Exception:
                pass
        _clear_token()
        self._access_token = None
        self._kite_obj = None


# ══════════════════════════════════════════════════════════════════════════════
#  ZERODHA DATA FETCHERS
# ══════════════════════════════════════════════════════════════════════════════

def fetch_historical_zerodha(kite,
                              instrument_token: int,
                              ticker_label: str,
                              days: int = 400,
                              interval: str = "day") -> pd.DataFrame | None:
    """
    Fetch OHLCV history from Zerodha and return an indicator-enriched DataFrame.

    Args:
        kite              – authenticated KiteConnect object
        instrument_token  – Zerodha instrument token (integer)
        ticker_label      – display name (e.g. "TCS.NS")
        days              – how many calendar days of history
        interval          – "day" / "60minute" / "30minute" / "5minute" / "minute"
    """
    try:
        end   = datetime.now()
        start = end - timedelta(days=days)
        raw   = kite.historical_data(
            instrument_token=instrument_token,
            from_date=start,
            to_date=end,
            interval=interval,
        )
        if not raw:
            return None

        df = pd.DataFrame(raw)
        df.rename(columns={"date":"Date","open":"Open","high":"High",
                             "low":"Low","close":"Close","volume":"Volume"},
                  inplace=True)
        df.set_index("Date", inplace=True)

        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        df = df[["Open","High","Low","Close","Volume"]].dropna()
        return add_indicators(df)

    except Exception as e:
        log.warning(f"{ticker_label} Zerodha fetch error: {e}")
        return None


def get_live_quote_zerodha(kite, instrument_tokens: list) -> dict:
    """
    Fetch live quotes for a list of instrument tokens.
    Returns {token: {last_price, ohlc, volume, ...}}
    """
    try:
        return kite.quote(instrument_tokens)
    except Exception as e:
        log.warning(f"Quote fetch error: {e}")
        return {}


def get_instrument_token(kite, exchange: str, tradingsymbol: str) -> int | None:
    """
    Look up the Zerodha instrument token for a given symbol.
    e.g. get_instrument_token(kite, "NSE", "TCS") → 2374401
    """
    try:
        instruments = kite.instruments(exchange)
        for inst in instruments:
            if inst["tradingsymbol"] == tradingsymbol:
                return inst["instrument_token"]
        return None
    except Exception as e:
        log.warning(f"Instrument lookup failed for {tradingsymbol}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  ORDER PLACER
# ══════════════════════════════════════════════════════════════════════════════

def place_order(kite,
                tradingsymbol: str,
                quantity: int,
                transaction_type: str = "BUY",
                order_type: str       = "MARKET",
                price: float | None   = None,
                trigger_price: float | None = None,
                exchange: str         = "NSE",
                product: str          = "MIS",       # MIS=intraday, CNC=delivery
                tag: str              = "halal_bot") -> dict:
    """
    Place an order via Zerodha Kite.

    Args:
        tradingsymbol  – NSE symbol, e.g. "TCS"
        quantity       – number of shares
        transaction_type – "BUY" or "SELL"
        order_type     – "MARKET" | "LIMIT" | "SL" | "SL-M"
        price          – required for LIMIT orders
        trigger_price  – required for SL / SL-M orders
        product        – "MIS" (intraday) | "CNC" (delivery / positional)
        tag            – custom tag visible in Zerodha console

    Returns:
        {"success": True, "order_id": "...", ...}
        {"success": False, "error": "..."}
    """
    from kiteconnect import KiteConnect

    try:
        params = dict(
            variety          = kite.VARIETY_REGULAR,
            exchange         = exchange,
            tradingsymbol    = tradingsymbol,
            transaction_type = (kite.TRANSACTION_TYPE_BUY
                                if transaction_type == "BUY"
                                else kite.TRANSACTION_TYPE_SELL),
            quantity         = quantity,
            product          = (kite.PRODUCT_MIS if product == "MIS"
                                else kite.PRODUCT_CNC),
            order_type       = {
                "MARKET": kite.ORDER_TYPE_MARKET,
                "LIMIT":  kite.ORDER_TYPE_LIMIT,
                "SL":     kite.ORDER_TYPE_SL,
                "SL-M":   kite.ORDER_TYPE_SLM,
            }.get(order_type, kite.ORDER_TYPE_MARKET),
            tag              = tag,
        )
        if price:          params["price"]         = price
        if trigger_price:  params["trigger_price"] = trigger_price

        order_id = kite.place_order(**params)
        log.info(f"Order placed: {transaction_type} {quantity} {tradingsymbol} "
                 f"({order_type}) → order_id={order_id}")
        return {"success": True, "order_id": order_id}

    except Exception as e:
        log.error(f"Order failed for {tradingsymbol}: {e}")
        return {"success": False, "error": str(e)}


def place_bracket_order_manual(kite,
                                tradingsymbol: str,
                                quantity: int,
                                entry_price: float,
                                stop_loss: float,
                                target: float,
                                exchange: str = "NSE") -> dict:
    """
    Simulates a bracket order using 3 separate orders:
      1. LIMIT BUY at entry_price
      2. SL-M SELL at stop_loss (stop-loss leg)
      3. LIMIT SELL at target (profit-booking leg)

    Zerodha's bracket order (BO) can also be used directly if available.
    """
    results = {}

    # Entry order
    entry = place_order(kite, tradingsymbol, quantity,
                         "BUY", "LIMIT", price=entry_price,
                         exchange=exchange, product="MIS")
    results["entry"] = entry

    if not entry["success"]:
        return {"success": False, "error": "Entry order failed", "details": results}

    # Stop-loss order
    sl = place_order(kite, tradingsymbol, quantity,
                      "SELL", "SL-M", trigger_price=stop_loss,
                      exchange=exchange, product="MIS")
    results["stop_loss"] = sl

    # Target order
    tgt = place_order(kite, tradingsymbol, quantity,
                       "SELL", "LIMIT", price=target,
                       exchange=exchange, product="MIS")
    results["target"] = tgt

    results["success"] = all(r["success"] for r in results.values()
                              if isinstance(r, dict) and "success" in r)
    return results


def get_orders(kite) -> list[dict]:
    """Return all orders placed today."""
    try:
        return kite.orders() or []
    except Exception as e:
        log.warning(f"get_orders error: {e}")
        return []


def get_positions(kite) -> dict:
    """Return current open positions."""
    try:
        return kite.positions() or {}
    except Exception as e:
        log.warning(f"get_positions error: {e}")
        return {}


def get_holdings(kite) -> list[dict]:
    """Return delivery holdings."""
    try:
        return kite.holdings() or []
    except Exception as e:
        log.warning(f"get_holdings error: {e}")
        return []


# ══════════════════════════════════════════════════════════════════════════════
#  POSTBACK HANDLER  (Zerodha → your server → here)
# ══════════════════════════════════════════════════════════════════════════════

def parse_postback(raw_post_data: dict) -> dict:
    """
    Parse an order-update postback sent by Zerodha to your postback URL.

    Zerodha sends a POST request with these fields:
        order_id, exchange_order_id, status, tradingsymbol,
        exchange, transaction_type, quantity, price, filled_quantity,
        average_price, order_timestamp, ...

    Call this from your postback endpoint:
        data = parse_postback(request.form)   # Flask
        data = parse_postback(await request.json())  # FastAPI

    Returns a clean dict with the key fields + a human-readable message.
    """
    status = raw_post_data.get("status", "").upper()
    symbol = raw_post_data.get("tradingsymbol", "")
    txn    = raw_post_data.get("transaction_type", "")
    qty    = raw_post_data.get("filled_quantity", 0)
    avg    = raw_post_data.get("average_price", 0)
    oid    = raw_post_data.get("order_id", "")

    emoji  = {"COMPLETE": "✅", "REJECTED": "❌",
               "CANCELLED": "⚠️"}.get(status, "🔄")

    msg = (f"{emoji} Order {oid} | {txn} {qty} {symbol} "
           f"@ ₹{avg} | Status: {status}")

    log.info(f"Postback: {msg}")

    return {
        "order_id":        oid,
        "status":          status,
        "tradingsymbol":   symbol,
        "transaction_type":txn,
        "filled_quantity": qty,
        "average_price":   avg,
        "message":         msg,
        "raw":             raw_post_data,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  STREAMLIT UI HELPER
# ══════════════════════════════════════════════════════════════════════════════

def render_login_ui(zs: "ZerodhaSession") -> bool:
    """
    Renders the Zerodha login panel inside a Streamlit app.
    Returns True if the user is (now) authenticated.

    Call from any Streamlit page:
        from zerodha_auth import ZerodhaSession, render_login_ui
        zs = ZerodhaSession()
        if render_login_ui(zs):
            kite = zs.kite()
            # do live trading stuff
    """
    import streamlit as st

    # Always try to pick up a redirect first
    just_logged_in = zs.handle_redirect()
    if just_logged_in:
        st.success("✅ Zerodha login successful!")
        st.rerun()

    if zs.is_authenticated():
        return True

    if not zs.credentials_configured():
        st.error(
            "Zerodha credentials not configured. "
            "Open `config.py` and fill in `ZERODHA_API_KEY` and `ZERODHA_API_SECRET`."
        )
        return False

    # Show login button
    st.markdown("### 🔐 Zerodha Login Required")
    st.markdown(
        "Click the button below to log in with your Zerodha account. "
        "You will be redirected back here automatically after login."
    )

    login_url = zs.login_url()
    st.markdown(
        f"""
<a href="{login_url}" target="_self">
  <button style="
    background:#387ed1;color:white;border:none;
    padding:12px 28px;border-radius:6px;
    font-size:16px;cursor:pointer;font-weight:600">
    🔐 Login with Zerodha
  </button>
</a>
""",
        unsafe_allow_html=True,
    )

    st.caption(
        f"After login, Zerodha will redirect you back to: `{ZERODHA_REDIRECT_URL}`"
    )
    return False
