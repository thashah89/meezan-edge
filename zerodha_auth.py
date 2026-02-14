"""
zerodha_auth.py – Zerodha Kite Connect auth for Streamlit Cloud.

TOKEN STORAGE STRATEGY (Streamlit Cloud compatible):
  PRIMARY   → st.session_state["zerodha_access_token"]
              Lives in the browser session. Survives page navigation,
              reruns. Lost only when the browser tab is closed.
  SECONDARY → zerodha_token.json  (local dev only)
              Streamlit Cloud filesystem is ephemeral — writes may
              silently fail or be wiped. Never relied on in production.

Auth flow:
  1. login_url()       → build Zerodha login URL (opens in new tab)
  2. User logs in      → Zerodha redirects back with ?request_token=
  3. handle_redirect() → reads token from URL params, exchanges for
                          access_token, stores in st.session_state
  4. is_authenticated()→ checks st.session_state
"""

import json
import os
import hashlib
import logging
import requests
from datetime import date

from config import (
    ZERODHA_API_KEY, ZERODHA_API_SECRET,
    ZERODHA_REDIRECT_URL, ZERODHA_TOKEN_FILE,
)

log = logging.getLogger(__name__)

# Kite v3 — X-Kite-Version header is MANDATORY on every call
_KITE_API_BASE = "https://api.kite.trade"
_KITE_HEADERS  = {
    "X-Kite-Version": "3",
    "Content-Type":   "application/x-www-form-urlencoded",
    "User-Agent":     "MeezanEdge/1.0",
}

# st.session_state key names
_SS_TOKEN        = "zerodha_access_token"
_SS_PUBLIC_TOKEN = "zerodha_public_token"
_SS_LOGIN_DATE   = "zerodha_login_date"


def _kite_available() -> bool:
    try:
        import kiteconnect  # noqa
        return True
    except ImportError:
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  SESSION STATE  (primary store — Streamlit Cloud safe)
# ══════════════════════════════════════════════════════════════════════════════

def _ss_save(access_token: str, public_token: str = "") -> None:
    """Store token in st.session_state."""
    import streamlit as st
    st.session_state[_SS_TOKEN]        = access_token
    st.session_state[_SS_PUBLIC_TOKEN] = public_token
    st.session_state[_SS_LOGIN_DATE]   = date.today().isoformat()
    log.info("Token stored in session_state ✅")


def _ss_load() -> str | None:
    """Load today's access_token from st.session_state. None if missing/expired."""
    try:
        import streamlit as st
        if st.session_state.get(_SS_LOGIN_DATE) != date.today().isoformat():
            return None
        return st.session_state.get(_SS_TOKEN) or None
    except Exception:
        return None


def _ss_clear() -> None:
    try:
        import streamlit as st
        for key in (_SS_TOKEN, _SS_PUBLIC_TOKEN, _SS_LOGIN_DATE):
            st.session_state.pop(key, None)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  FILE CACHE  (secondary — local dev only, silently skipped on cloud)
# ══════════════════════════════════════════════════════════════════════════════

def _file_save(access_token: str, public_token: str = "") -> None:
    try:
        payload = {
            "api_key":      ZERODHA_API_KEY,
            "access_token": access_token,
            "public_token": public_token,
            "login_date":   date.today().isoformat(),
        }
        with open(ZERODHA_TOKEN_FILE, "w") as f:
            json.dump(payload, f, indent=2)
        log.info(f"Token also saved to file: {ZERODHA_TOKEN_FILE}")
    except Exception as e:
        log.debug(f"File save skipped (expected on Streamlit Cloud): {e}")


def _file_load() -> str | None:
    """Load today's token from file. Returns None on any failure."""
    try:
        if not os.path.exists(ZERODHA_TOKEN_FILE):
            return None
        with open(ZERODHA_TOKEN_FILE) as f:
            data = json.load(f)
        if data.get("login_date") != date.today().isoformat():
            return None
        return data.get("access_token") or None
    except Exception:
        return None


def _file_clear() -> None:
    try:
        if os.path.exists(ZERODHA_TOKEN_FILE):
            os.remove(ZERODHA_TOKEN_FILE)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  RAW HTTPS SESSION GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

def _raw_generate_session(api_key: str,
                           api_secret: str,
                           request_token: str) -> dict:
    """
    POST to Zerodha /session/token with correct Kite v3 headers.
    Returns the data dict on success.
    Raises ValueError with Zerodha's exact error message on failure.
    """
    checksum = hashlib.sha256(
        f"{api_key}{request_token}{api_secret}".encode("utf-8")
    ).hexdigest()

    log.info(
        f"POST /session/token  "
        f"api_key={api_key[:6]}…  "
        f"request_token={request_token[:10]}…  "
        f"checksum={checksum[:10]}…"
    )

    resp = requests.post(
        f"{_KITE_API_BASE}/session/token",
        data    = {"api_key": api_key,
                   "request_token": request_token,
                   "checksum": checksum},
        headers = _KITE_HEADERS,
        timeout = 20,
    )

    log.info(f"Zerodha HTTP {resp.status_code}")

    try:
        body = resp.json()
    except Exception:
        raise ValueError(
            f"Non-JSON response (HTTP {resp.status_code}): {resp.text[:400]}"
        )

    log.info(f"Zerodha response status: {body.get('status')}  "
             f"error_type: {body.get('error_type','')}")

    if body.get("status") != "success":
        raise ValueError(
            f"[{body.get('error_type','KiteError')}] {body.get('message','Unknown error')}"
        )

    return body.get("data", {})


# ══════════════════════════════════════════════════════════════════════════════
#  ZERODHA SESSION
# ══════════════════════════════════════════════════════════════════════════════

class ZerodhaSession:
    """
    Manages Zerodha auth state across Streamlit reruns.

    Token lookup priority:
      1. st.session_state  (survives reruns in same browser tab)
      2. zerodha_token.json (local dev only)
    """

    def __init__(self):
        self._kite_obj        = None
        self._access_token    = None
        self._credentials_ok  = bool(ZERODHA_API_KEY and ZERODHA_API_SECRET)

        # 1. Try session_state first (works on Streamlit Cloud)
        token = _ss_load()

        # 2. Fall back to file (local dev)
        if not token:
            token = _file_load()
            if token:
                # Migrate file token → session_state for this session
                _ss_save(token)

        if token:
            self._access_token = token
            if _kite_available():
                self._init_kite(token)

    # ── STATUS ────────────────────────────────────────────────────────────────

    def credentials_configured(self) -> bool:
        return self._credentials_ok

    def is_authenticated(self) -> bool:
        return self._access_token is not None

    # ── LOGIN URL ─────────────────────────────────────────────────────────────

    def login_url(self) -> str:
        if not self._credentials_ok:
            raise ValueError("ZERODHA_API_KEY / ZERODHA_API_SECRET not set in Secrets.")
        if _kite_available():
            from kiteconnect import KiteConnect
            return KiteConnect(api_key=ZERODHA_API_KEY).login_url()
        return (
            "https://kite.zerodha.com/connect/login"
            f"?v=3&api_key={ZERODHA_API_KEY}"
        )

    # ── HANDLE REDIRECT ───────────────────────────────────────────────────────

    def handle_redirect(self) -> bool:
        """
        Call on every Streamlit page load.

        After Zerodha login, the browser URL contains:
          ?request_token=XXXX&status=success&action=login&type=login

        This method reads the token, exchanges it, stores in session_state.
        Returns True if a fresh login was just completed.
        """
        import streamlit as st

        params        = st.query_params
        request_token = params.get("request_token", "").strip()
        status        = params.get("status", "").strip()

        if not request_token:
            return False    # no redirect in this URL

        # Accept status=success or blank (some Zerodha configs omit it)
        if status and status != "success":
            st.error(f"Zerodha returned status=`{status}`. Login failed.")
            st.query_params.clear()
            return False

        # Don't re-exchange if we already have a token for today
        if _ss_load():
            st.query_params.clear()
            return False

        try:
            data         = _raw_generate_session(
                               ZERODHA_API_KEY, ZERODHA_API_SECRET, request_token)
            access_token = data["access_token"]
            public_token = data.get("public_token", "")

            # PRIMARY: session_state
            _ss_save(access_token, public_token)
            # SECONDARY: file (local only, silent on cloud)
            _file_save(access_token, public_token)

            self._access_token = access_token
            self._init_kite(access_token)

            st.query_params.clear()
            log.info("✅ Zerodha authentication successful")
            return True

        except Exception as e:
            st.error(f"❌ Zerodha token exchange failed: {e}")
            log.error(f"Token exchange error: {e}")
            # Don't clear query_params — keep for debug
            return False

    # ── KITE OBJECT ───────────────────────────────────────────────────────────

    def _init_kite(self, access_token: str) -> None:
        if _kite_available():
            from kiteconnect import KiteConnect
            kite = KiteConnect(api_key=ZERODHA_API_KEY)
            kite.set_access_token(access_token)
            self._kite_obj = kite

    def kite(self):
        return self._kite_obj

    def access_token(self) -> str | None:
        return self._access_token

    def logout(self) -> None:
        if self._kite_obj:
            try:
                self._kite_obj.invalidate_access_token()
            except Exception:
                pass
        _ss_clear()
        _file_clear()
        self._access_token = None
        self._kite_obj     = None


# ══════════════════════════════════════════════════════════════════════════════
#  RAW API HELPERS  (no SDK needed)
# ══════════════════════════════════════════════════════════════════════════════

def _auth_headers(access_token: str) -> dict:
    return {**_KITE_HEADERS,
            "Authorization": f"token {ZERODHA_API_KEY}:{access_token}"}


def _raw_get(endpoint: str, access_token: str, params: dict = None) -> dict:
    resp = requests.get(
        f"{_KITE_API_BASE}{endpoint}",
        headers=_auth_headers(access_token),
        params=params or {},
        timeout=15,
    )
    body = resp.json()
    if body.get("status") != "success":
        raise ValueError(f"Kite API: {body.get('message', body)}")
    return body.get("data", {})


def _raw_post(endpoint: str, access_token: str, data: dict = None) -> dict:
    resp = requests.post(
        f"{_KITE_API_BASE}{endpoint}",
        headers=_auth_headers(access_token),
        data=data or {},
        timeout=15,
    )
    body = resp.json()
    if body.get("status") != "success":
        raise ValueError(f"Kite API: {body.get('message', body)}")
    return body.get("data", {})


# ══════════════════════════════════════════════════════════════════════════════
#  DATA & ORDERS
# ══════════════════════════════════════════════════════════════════════════════

def get_live_quote(kite_or_token, symbols: list) -> dict:
    try:
        if _kite_available() and hasattr(kite_or_token, "quote"):
            return kite_or_token.quote(symbols)
        return _raw_get("/quote", kite_or_token, params={"i": symbols})
    except Exception as e:
        log.warning(f"Quote fetch error: {e}")
        return {}


def get_instrument_token(kite_or_token, symbol: str, exchange: str = "NSE"):
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
        log.warning(f"Token lookup failed {symbol}: {e}")
        return None


def place_order(kite_or_token, tradingsymbol, quantity,
                transaction_type="BUY", order_type="MARKET",
                price=None, trigger_price=None,
                exchange="NSE", product="MIS",
                tag="meezan_edge") -> dict:
    try:
        if _kite_available() and hasattr(kite_or_token, "place_order"):
            kite = kite_or_token
            params = dict(
                variety=kite.VARIETY_REGULAR, exchange=exchange,
                tradingsymbol=tradingsymbol,
                transaction_type=(kite.TRANSACTION_TYPE_BUY
                                  if transaction_type == "BUY"
                                  else kite.TRANSACTION_TYPE_SELL),
                quantity=quantity,
                product=kite.PRODUCT_MIS if product == "MIS" else kite.PRODUCT_CNC,
                order_type={"MARKET": kite.ORDER_TYPE_MARKET,
                             "LIMIT":  kite.ORDER_TYPE_LIMIT,
                             "SL":     kite.ORDER_TYPE_SL,
                             "SL-M":   kite.ORDER_TYPE_SLM
                             }.get(order_type, kite.ORDER_TYPE_MARKET),
                tag=tag,
            )
            if price:         params["price"]         = price
            if trigger_price: params["trigger_price"] = trigger_price
            order_id = kite.place_order(**params)
        else:
            access_token = kite_or_token if isinstance(kite_or_token, str) else None
            if not access_token:
                return {"success": False, "error": "No access token"}
            d = {"variety": "regular", "exchange": exchange,
                 "tradingsymbol": tradingsymbol,
                 "transaction_type": transaction_type,
                 "quantity": str(quantity), "product": product,
                 "order_type": order_type, "tag": tag}
            if price:         d["price"]         = str(price)
            if trigger_price: d["trigger_price"] = str(trigger_price)
            result   = _raw_post("/orders/regular", access_token, d)
            order_id = result.get("order_id", "")

        return {"success": True, "order_id": order_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_orders(kite_or_token) -> list:
    try:
        if _kite_available() and hasattr(kite_or_token, "orders"):
            return kite_or_token.orders() or []
        return _raw_get("/orders", kite_or_token) or []
    except Exception as e:
        log.warning(f"get_orders: {e}")
        return []


def get_positions(kite_or_token) -> dict:
    try:
        if _kite_available() and hasattr(kite_or_token, "positions"):
            return kite_or_token.positions() or {}
        return _raw_get("/portfolio/positions", kite_or_token) or {}
    except Exception as e:
        log.warning(f"get_positions: {e}")
        return {}


def get_holdings(kite_or_token) -> list:
    try:
        if _kite_available() and hasattr(kite_or_token, "holdings"):
            return kite_or_token.holdings() or []
        return _raw_get("/portfolio/holdings", kite_or_token) or []
    except Exception as e:
        log.warning(f"get_holdings: {e}")
        return []


def parse_postback(raw: dict) -> dict:
    status = raw.get("status", "").upper()
    symbol = raw.get("tradingsymbol", "")
    txn    = raw.get("transaction_type", "")
    qty    = raw.get("filled_quantity", 0)
    avg    = raw.get("average_price", 0)
    oid    = raw.get("order_id", "")
    emoji  = {"COMPLETE": "✅", "REJECTED": "❌", "CANCELLED": "⚠️"}.get(status, "🔄")
    msg    = f"{emoji} {oid} | {txn} {qty} {symbol} @ ₹{avg} | {status}"
    log.info(f"Postback: {msg}")
    return {"order_id": oid, "status": status, "tradingsymbol": symbol,
            "transaction_type": txn, "filled_quantity": qty,
            "average_price": avg, "message": msg, "raw": raw}


# ══════════════════════════════════════════════════════════════════════════════
#  STREAMLIT UI HELPER
# ══════════════════════════════════════════════════════════════════════════════

def render_login_ui(zs: ZerodhaSession) -> bool:
    import streamlit as st
    if zs.handle_redirect():
        st.success("✅ Zerodha login successful!")
        st.rerun()
    if zs.is_authenticated():
        return True
    if not zs.credentials_configured():
        st.error("API Key/Secret not set. Add them in Streamlit Secrets.")
        return False
    url = zs.login_url()
    st.markdown(
        f'<a href="{url}" target="_blank">'
        '<button style="background:#387ed1;color:white;border:none;'
        'padding:12px 28px;border-radius:6px;font-size:16px;'
        'cursor:pointer;font-weight:600">🔐 Login with Zerodha ↗</button></a>',
        unsafe_allow_html=True,
    )
    return False
