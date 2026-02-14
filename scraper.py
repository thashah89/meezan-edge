"""
scraper.py – Scrapes halalstock.in for the Halal/Shariah-compliant stock list.
Saves to a local JSON cache so repeated runs are fast.
"""

import requests
from bs4 import BeautifulSoup
import json, os, time, logging
from datetime import datetime
from config import SCRAPER_URL, CACHE_FILE

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


def scrape_halal_stocks(force_refresh: bool = False) -> list[dict]:
    """
    Returns a list of Halal stocks.
    Uses cache if available (< 24 h old) unless force_refresh=True.

    Each item: {
        company, nse_symbol, bse_symbol, industry,
        details_url, nse_ticker  (e.g. 'TCS.NS')
    }
    """
    cache_path = os.path.join(os.getcwd(), CACHE_FILE)

    # ── try cache ─────────────────────────────────────────────────────────────
    if not force_refresh and os.path.exists(cache_path):
        age = time.time() - os.path.getmtime(cache_path)
        if age < 86_400:                        # 24 h
            with open(cache_path) as f:
                data = json.load(f)
            log.info(f"Loaded {len(data)} stocks from cache.")
            return data

    # ── scrape live ───────────────────────────────────────────────────────────
    log.info(f"Scraping {SCRAPER_URL} …")
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        r = session.get(SCRAPER_URL, timeout=30)
        r.raise_for_status()
    except Exception as e:
        log.error(f"Scrape failed: {e}")
        # Fall back to stale cache if available
        if os.path.exists(cache_path):
            log.warning("Returning stale cache.")
            with open(cache_path) as f:
                return json.load(f)
        return []

    soup = BeautifulSoup(r.text, "lxml")
    tbody = soup.select_one("tbody.row-striping") or soup.find("tbody")

    if not tbody:
        log.error("Table body not found – site layout may have changed.")
        return []

    stocks = []
    for row in tbody.find_all("tr"):
        cols = row.find_all("td")
        if len(cols) < 5:
            continue

        # Check halal tick (image src contains 'hs-yes')
        img = cols[0].find("img") if cols[0].find("img") else None
        if img and "hs-yes" not in img.get("src", ""):
            continue

        nse_raw = cols[3].get_text(strip=True).upper() if len(cols) > 3 else ""
        bse_raw = cols[2].get_text(strip=True).upper() if len(cols) > 2 else ""

        # Skip rows with no usable symbol
        if not nse_raw and not bse_raw:
            continue

        nse_ticker = f"{nse_raw}.NS" if nse_raw else ""

        detail_tag = cols[-1].find("a") if cols[-1].find("a") else None
        detail_url = detail_tag["href"] if detail_tag else ""

        stocks.append({
            "company":     cols[1].get_text(strip=True) if len(cols) > 1 else "",
            "nse_symbol":  nse_raw,
            "bse_symbol":  bse_raw,
            "industry":    cols[4].get_text(strip=True) if len(cols) > 4 else "",
            "details_url": detail_url,
            "nse_ticker":  nse_ticker,
            "scraped_at":  datetime.now().isoformat(),
        })

    log.info(f"✅ Scraped {len(stocks)} Halal stocks.")

    # ── save cache ────────────────────────────────────────────────────────────
    with open(cache_path, "w") as f:
        json.dump(stocks, f, indent=2)

    return stocks


def get_nse_tickers(force_refresh: bool = False) -> list[str]:
    """Return only the NSE ticker strings (e.g. ['TCS.NS', 'INFY.NS', …])"""
    stocks = scrape_halal_stocks(force_refresh)
    return [s["nse_ticker"] for s in stocks if s["nse_ticker"]]


if __name__ == "__main__":
    stocks = scrape_halal_stocks(force_refresh=True)
    print(f"\nTotal Halal stocks: {len(stocks)}")
    for s in stocks[:5]:
        print(s)
