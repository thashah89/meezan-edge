"""
halal_scraper.py – Scrapes halalstock.in for Halal/Shariah compliant stocks
Zerodha-ready + backward compatible (keeps 'symbol')
"""

import requests
from bs4 import BeautifulSoup, FeatureNotFound
import json, os, time, logging
from datetime import datetime

# ===== CONFIG (kept here to avoid import errors) =====
SCRAPER_URL = "https://halalstock.in/halal-shariah-compliant-shares-list/"
CACHE_FILE = "halal_stock_cache.json"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://halalstock.in/",
    "Accept-Language": "en-US,en;q=0.9",
}


# =====================================================
# MAIN SCRAPER
# =====================================================
def scrape_halal_stocks(force_refresh: bool = False) -> list[dict]:
    """
    Returns halal stock list

    Each item:
    {
        company,
        symbol,          # master key (used everywhere)
        tradingsymbol,   # Zerodha key
        nse_symbol,
        bse_symbol,
        industry,
        exchange
    }
    """

    cache_path = os.path.join(os.getcwd(), CACHE_FILE)

    # ── LOAD CACHE ─────────────────────────────────────
    if not force_refresh and os.path.exists(cache_path):
        age = time.time() - os.path.getmtime(cache_path)
        if age < 86400:
            with open(cache_path) as f:
                data = json.load(f)
            log.info(f"Loaded {len(data)} stocks from cache")
            return data

    log.info(f"Scraping halal list from: {SCRAPER_URL}")

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        r = session.get(SCRAPER_URL, timeout=30)
        r.raise_for_status()
    except Exception as e:
        log.error(f"Scrape failed: {e}")

        if os.path.exists(cache_path):
            log.warning("Returning stale cache")
            with open(cache_path) as f:
                return json.load(f)

        return []

    # Streamlit Cloud may not always have lxml installed.
    try:
        soup = BeautifulSoup(r.text, "lxml")
    except FeatureNotFound:
        soup = BeautifulSoup(r.text, "html.parser")
    tbody = soup.select_one("tbody.row-striping") or soup.find("tbody")

    if not tbody:
        log.error("Table not found — website layout changed")
        return []

    stocks = []

    for row in tbody.find_all("tr"):
        cols = row.find_all("td")
        if len(cols) < 5:
            continue

        # Check halal tick image
        img = cols[0].find("img")
        if img and "hs-yes" not in img.get("src", ""):
            continue

        nse_symbol = cols[3].get_text(strip=True).upper() if len(cols) > 3 else ""
        bse_symbol = cols[2].get_text(strip=True).upper() if len(cols) > 2 else ""

        if not nse_symbol:
            continue

        detail_tag = cols[-1].find("a")
        detail_url = detail_tag["href"] if detail_tag else ""

        company = cols[1].get_text(strip=True)
        industry = cols[4].get_text(strip=True) if len(cols) > 4 else ""

        stocks.append({
            "company": company,
            "symbol": nse_symbol,            # ← MASTER KEY (fixes your crash)
            "tradingsymbol": nse_symbol,     # Zerodha
            "nse_symbol": nse_symbol,
            "bse_symbol": bse_symbol,
            "industry": industry,
            "details_url": detail_url,
            "exchange": "NSE",
            "scraped_at": datetime.now().isoformat(),
        })

    log.info(f"✅ Scraped {len(stocks)} halal stocks")

    # ── SAVE CACHE ─────────────────────────────────────
    try:
        with open(cache_path, "w") as f:
            json.dump(stocks, f, indent=2)
        log.info("Cache saved")
    except Exception as e:
        log.warning(f"Cache save failed: {e}")

    return stocks


# =====================================================
# HELPERS
# =====================================================
def get_tradingsymbols(force_refresh: bool = False) -> list[str]:
    """Zerodha tradingsymbol list"""
    stocks = scrape_halal_stocks(force_refresh)
    return [s["tradingsymbol"] for s in stocks if s.get("tradingsymbol")]


def get_symbols(force_refresh: bool = False) -> list[str]:
    """Universal symbol list"""
    stocks = scrape_halal_stocks(force_refresh)
    return [s["symbol"] for s in stocks if s.get("symbol")]


# =====================================================
# TEST RUN
# =====================================================
if __name__ == "__main__":
    stocks = scrape_halal_stocks(force_refresh=True)

    print(f"\nTotal halal stocks: {len(stocks)}\n")

    for s in stocks[:10]:
        print(s)
