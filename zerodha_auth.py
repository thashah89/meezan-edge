"""
zerodha_auth.py – Zerodha Kite Connect authentication handler.

Works WITHOUT the kiteconnect SDK — uses raw HTTPS with the correct
Kite v3 headers that Zerodha requires.
Installs kiteconnect if present and uses SDK path when available.

Auth flow:
  1. login_url()       → build the Zerodha login URL
  2. User logs in      → Zerodha redirects to your app URL with ?request_token=
  3. handle_redirect() → reads token from URL, exchanges for access_token
  4. kite()            → returns authenticated KiteConnect object (if SDK installed)
"""

import json
import os
import hashlib
import logging
import requests
from datetime import datetime, date, timedelta

import pandas as pd

from config import (
    ZERODHA_API_KEY, ZERODHA_API_SECRET,
    ZERODHA_REDIRECT_URL, ZERODHA_POSTBACK_URL,
    ZERODHA_TOKEN_FILE,
)

log = logging.getLogger(__name__)

# ── Kite v3 base URL and required headers ─────────────────────────────────────
_KITE_API_BASE = "https://api.kite.trade"
_KITE_HEADERS  = {
    "X-Kite-Version":  "3",                        # ← mandatory for all v3 calls
    "Content-Type":    "application/x-www-form-urlencoded",
    "User-Agent":      "Kite Python Raw Client/1.0",
}


def _kite_available() -> bool:
    try:
        import kiteconnect  # noqa
        return True
    except ImportError:
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  TOKEN CACHE
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
    log.info(f"Token saved → {ZERODHA_TOKEN_FILE}")


def _load_token() -> dict | None:
    """Load today's cached token. Returns None if missing or from a previous day."""
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


# ══════════════════════════════════════════════════════════════════════════════
#  RAW HTTPS SESSION GENERATOR  (no SDK needed)
# ══════════════════════════════════════════════════════════════════════════════

def _raw_generate_session(api_key: str,
                           api_secret: str,
                           request_token: str) -> dict:
    """
    Exchange request_token for access_token using raw HTTPS.
    Sends the exact headers Zerodha v3 requires.

    Returns the full Zerodha response dict on success.
    Raises ValueError with Zerodha's error message on failure.
    """
    # Checksum = SHA256(api_key + request_token + api_secret)
    raw         = f"{api_key}{request_token}{api_secret}"
    checksum    = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    url  = f"{_KITE_API_BASE}/session/token"
    data = {
        "api_key":       api_key,
        "request_token": request_token,
        "checksum":      checksum,
    }

    log.info(f"POST {url}  api_key={api_key[:6]}…  token={request_token[:8]}…")

    resp = requests.post(
        url,
        data    = data,
        headers = _KITE_HEADERS,
        timeout = 15,
    )

    log.info(f"Zerodha response: HTTP {resp.status_code}")

    try:
        body = resp.json()
    except Exception:
        raise ValueError(f"Non-JSON response from Zerodha (HTTP {resp.status_code}): {resp.text[:300]}")

    if body.get("status") != "success":
        # Surface Zerodha's exact error message back to the user
        msg        = body.get("message", "Unknown error")
        error_type = body.get("error_type", "")
        raise ValueError(f"Zerodha error [{error_type}]: {msg}")

    return body.get("data", {})


# ══════════════════════════════════════════════════════════════════════════════
#  ZERODHA SESSION
# ══════════════════════════════════════════════════════════════════════════════

class ZerodhaSession:

    def __init__(self):
        self._kite_obj    = None
        self._access_token: str | None = None
        self._credentials_ok = bool(ZERODHA_API_KEY and ZERODHA_API_SECRET)

        # Load today's cached token if available
        cached = _load_token()
        if cached and cached.get("access_token"):
            self._access_token = cached["access_token"]
            if _kite_available():
                self._init_kite(self._access_token)

    def credentials_configured(self) -> bool:
        return self._credentials_ok

    def is_authenticated(self) -> bool:
        return self._access_token is not None

    # ── BUILD LOGIN URL ────────────────────────────────────────────────────────

    def login_url(self) -> str:
        """
        Returns the Kite v3 login URL.
        Format:  https://kite.zerodha.com/connect/login?v=3&api_key={key}
        After login Zerodha redirects to:
          {ZERODHA_REDIRECT_URL}?request_token=XXXX&action=login&status=success
        """
        if not self._credentials_ok:
            raise ValueError("ZERODHA_API_KEY and ZERODHA_API_SECRET not set in Secrets.")

        if _kite_available():
            from kiteconnect import KiteConnect
            return KiteConnect(api_key=ZERODHA_API_KEY).login_url()

        # Manual URL — same as what the SDK builds
        return (
            "https://kite.zerodha.com/connect/login"
            f"?v=3&api_key={ZERODHA_API_KEY}"
        )

    # ── HANDLE REDIRECT ────────────────────────────────────────────────────────

    def handle_redirect(self) -> bool:
        """
        Call on every Streamlit page load.
        Reads ?request_token= from URL, exchanges it, caches access_token.
        Returns True when a new login was just completed.
        """
        import streamlit as st

        params        = st.query_params
        request_token = params.get("request_token", None)
        status        = params.get("status", "")

        if not request_token:
            return False   # no redirect happened

        # Zerodha sends status=success on success
        if status not in ("success", ""):
            st.error(f"Zerodha login failed. Status returned: `{status}`")
            st.query_params.clear()
            return False

        try:
            data         = _raw_generate_session(
                               ZERODHA_API_KEY, ZERODHA_API_SECRET, request_token)
            access_token = data["access_token"]
            public_token = data.get("public_token", "")

            self._access_token = access_token
            _save_token(ZERODHA_API_KEY, access_token, public_token)
            self._init_kite(access_token)

            st.query_params.clear()
            log.info("Zerodha authentication successful.")
            return True

        except Exception as e:
            st.error(f"❌ Token exchange failed: {e}")
            log.error(f"Token exchange error: {e}")
            st.query_params.clear()
            return False

    # ── KITE OBJECT (SDK path) ─────────────────────────────────────────────────

    def _init_kite(self, access_token: str) -> None:
        if _kite_available():
            from kiteconnect import KiteConnect
            kite = KiteConnect(api_key=ZERODHA_API_KEY)
            kite.set_access_token(access_token)
            self._kite_obj = kite

    def kite(self):
        """
        Returns authenticated KiteConnect object (if SDK installed),
        otherwise None.  Raw HTTP callers use _raw_kite_get/post instead.
        """
        return self._kite_obj

    def access_token(self) -> str | None:
        return self._access_token

    def logout(self) -> None:
        if self._kite_obj:
            try:
                self._kite_obj.invalidate_access_token()
            except Exception:
                pass
        _clear_token()
        self._access_token = None
        self._kite_obj     = None


# ══════════════════════════════════════════════════════════════════════════════
#  RAW KITE API CALLS  (used when kiteconnect SDK is not installed)
# ══════════════════════════════════════════════════════════════════════════════

def _raw_get(endpoint: str, access_token: str, params: dict = None) -> dict:
    """Authenticated GET to Kite v3 API."""
    headers = {
        **_KITE_HEADERS,
        "Authorization": f"token {ZERODHA_API_KEY}:{access_token}",
    }
    resp = requests.get(
        f"{_KITE_API_BASE}{endpoint}",
        headers = headers,
        params  = params or {},
        timeout = 15,
    )
    body = resp.json()
    if body.get("status") != "success":
        raise ValueError(f"Kite API error: {body.get('message', body)}")
    return body.get("data", {})


def _raw_post(endpoint: str, access_token: str, data: dict = None) -> dict:
    """Authenticated POST to Kite v3 API."""
    headers = {
        **_KITE_HEADERS,
        "Authorization": f"token {ZERODHA_API_KEY}:{access_token}",
    }
    resp = requests.post(
        f"{_KITE_API_BASE}{endpoint}",
        headers = headers,
        data    = data or {},
        timeout = 15,
    )
    body = resp.json()
    if body.get("status") != "success":
        raise ValueError(f"Kite API error: {body.get('message', body)}")
    return body.get("data", {})


# ══════════════════════════════════════════════════════════════════════════════
#  DATA FETCHERS
# ══════════════════════════════════════════════════════════════════════════════

def fetch_historical_zerodha(kite_or_token,
                              instrument_token: int,
                              ticker_label: str,
                              days: int = 400,
                              interval: str = "day") -> pd.DataFrame | None:
    """
    Fetch OHLCV history from Zerodha.
    Accepts either a KiteConnect object (SDK) or an access_token string (raw).
    """
    from market_data import add_indicators

    end   = datetime.now()
    start = end - timedelta(days=days)

    try:
        if _kite_available() and hasattr(kite_or_token, "historical_data"):
            raw = kite_or_token.historical_data(
                instrument_token = instrument_token,
                from_date = start, to_date = end, interval = interval,
            )
        else:
            # Raw HTTP path
            access_token = kite_or_token if isinstance(kite_or_token, str) else None
            if not access_token:
                return None
            raw = _raw_get(
                f"/instruments/historical/{instrument_token}/{interval}",
                access_token,
                params={
                    "from": start.strftime("%Y-%m-%d"),
                    "to":   end.strftime("%Y-%m-%d"),
                },
            )
            raw = raw.get("candles", [])
            # candles format: [timestamp, open, high, low, close, volume]
            raw = [{"date": r[0], "open": r[1], "high": r[2],
                    "low": r[3], "close": r[4], "volume": r[5]}
                   for r in raw]

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
        log.warning(f"{ticker_label} historical fetch error: {e}")
        return None


def get_live_quote(kite_or_token, symbols: list[str]) -> dict:
    """
    Fetch live quotes.  symbols = ["NSE:TCS", "NSE:INFY", …]
    Returns {symbol: {last_price, ohlc, …}}
    """
    try:
        if _kite_available() and hasattr(kite_or_token, "quote"):
            return kite_or_token.quote(symbols)
        else:
            data = _raw_get("/quote", kite_or_token,
                             params={"i": symbols})
            return data
    except Exception as e:
        log.warning(f"Quote fetch error: {e}")
        return {}


def get_instrument_token(kite_or_token, symbol: str,
                          exchange: str = "NSE") -> int | None:
    try:
        if _kite_available() and hasattr(kite_or_token, "instruments"):
            instruments = kite_or_token.instruments(exchange)
        else:
            instruments = _raw_get(f"/instruments/{exchange}", kite_or_token)

        for inst in instruments:
            if inst.get("tradingsymbol") == symbol:
                return inst["instrument_token"]
        return None
    except Exception as e:
        log.warning(f"Token lookup failed for {symbol}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  ORDER PLACER
# ══════════════════════════════════════════════════════════════════════════════

def place_order(kite_or_token,
                tradingsymbol: str,
                quantity: int,
                transaction_type: str = "BUY",
                order_type: str       = "MARKET",
                price: float | None   = None,
                trigger_price: float | None = None,
                exchange: str         = "NSE",
                product: str          = "MIS",
                tag: str              = "meezan_edge") -> dict:
    try:
        if _kite_available() and hasattr(kite_or_token, "place_order"):
            kite = kite_or_token
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
                tag = tag,
            )
            if price:         params["price"]         = price
            if trigger_price: params["trigger_price"] = trigger_price
            order_id = kite.place_order(**params)

        else:
            # Raw HTTP path
            access_token = kite_or_token if isinstance(kite_or_token, str) else None
            if not access_token:
                return {"success": False, "error": "No access token"}
            data = {
                "variety":          "regular",
                "exchange":          exchange,
                "tradingsymbol":     tradingsymbol,
                "transaction_type":  transaction_type,
                "quantity":          str(quantity),
                "product":           product,
                "order_type":        order_type,
                "tag":               tag,
            }
            if price:         data["price"]         = str(price)
            if trigger_price: data["trigger_price"] = str(trigger_price)

            result   = _raw_post("/orders/regular", access_token, data)
            order_id = result.get("order_id", "")

        log.info(f"Order placed: {transaction_type} {quantity} {tradingsymbol} → {order_id}")
        return {"success": True, "order_id": order_id}

    except Exception as e:
        log.error(f"Order failed for {tradingsymbol}: {e}")
        return {"success": False, "error": str(e)}


def get_orders(kite_or_token) -> list:
    try:
        if _kite_available() and hasattr(kite_or_token, "orders"):
            return kite_or_token.orders() or []
        return _raw_get("/orders", kite_or_token) or []
    except Exception as e:
        log.warning(f"get_orders error: {e}")
        return []


def get_positions(kite_or_token) -> dict:
    try:
        if _kite_available() and hasattr(kite_or_token, "positions"):
            return kite_or_token.positions() or {}
        return _raw_get("/portfolio/positions", kite_or_token) or {}
    except Exception as e:
        log.warning(f"get_positions error: {e}")
        return {}


def get_holdings(kite_or_token) -> list:
    try:
        if _kite_available() and hasattr(kite_or_token, "holdings"):
            return kite_or_token.holdings() or []
        return _raw_get("/portfolio/holdings", kite_or_token) or []
    except Exception as e:
        log.warning(f"get_holdings error: {e}")
        return []


# ══════════════════════════════════════════════════════════════════════════════
#  POSTBACK PARSER
# ══════════════════════════════════════════════════════════════════════════════

def parse_postback(raw_post_data: dict) -> dict:
    status = raw_post_data.get("status", "").upper()
    symbol = raw_post_data.get("tradingsymbol", "")
    txn    = raw_post_data.get("transaction_type", "")
    qty    = raw_post_data.get("filled_quantity", 0)
    avg    = raw_post_data.get("average_price", 0)
    oid    = raw_post_data.get("order_id", "")
    emoji  = {"COMPLETE":"✅","REJECTED":"❌","CANCELLED":"⚠️"}.get(status,"🔄")
    msg    = f"{emoji} Order {oid} | {txn} {qty} {symbol} @ ₹{avg} | {status}"
    log.info(f"Postback: {msg}")
    return {
        "order_id": oid, "status": status, "tradingsymbol": symbol,
        "transaction_type": txn, "filled_quantity": qty,
        "average_price": avg, "message": msg, "raw": raw_post_data,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  STREAMLIT UI HELPER
# ══════════════════════════════════════════════════════════════════════════════

def render_login_ui(zs: "ZerodhaSession") -> bool:
    import streamlit as st

    just_logged_in = zs.handle_redirect()
    if just_logged_in:
        st.success("✅ Zerodha login successful!")
        st.rerun()

    if zs.is_authenticated():
        return True

    if not zs.credentials_configured():
        st.error("API Key/Secret not set. Add them in Streamlit Secrets.")
        return False

    login_url = zs.login_url()
    st.markdown("### 🔐 Login to Zerodha")
    st.markdown(
        f"""<a href="{login_url}" target="_self">
<button style="background:#387ed1;color:white;border:none;
  padding:12px 28px;border-radius:6px;font-size:16px;
  cursor:pointer;font-weight:600">🔐 Login with Zerodha</button></a>""",
        unsafe_allow_html=True,
    )
    st.caption(f"Redirect URL: `{ZERODHA_REDIRECT_URL}`")
    return False
