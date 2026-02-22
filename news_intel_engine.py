"""
News intelligence engine for breakout catalyst discovery.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional
import logging
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus, urlparse

import requests

log = logging.getLogger(__name__)


class NewsIntelEngine:
    """Lightweight, dependency-free news scoring engine."""

    POSITIVE_TERMS = {
        "breakout", "surge", "rally", "upgrade", "beats", "strong", "record",
        "order win", "contract", "guidance raised", "buyback", "acquisition",
        "outperform", "overweight", "target raised", "bullish",
    }
    NEGATIVE_TERMS = {
        "downgrade", "misses", "weak", "fall", "lawsuit", "probe", "fraud",
        "selloff", "target cut", "underperform", "warning", "bearish",
        "debt concern", "pledge", "default",
    }
    CATALYST_TERMS = {
        "results", "earnings", "guidance", "order", "deal", "fii", "dii",
        "stake", "merger", "demerger", "approval", "policy", "tariff", "capex",
        "new product", "promoter", "buyback",
    }

    SOURCE_WEIGHT = {
        "moneycontrol.com": 1.00,
        "economictimes.indiatimes.com": 0.95,
        "livemint.com": 0.92,
        "business-standard.com": 0.90,
        "reuters.com": 1.00,
        "bloomberg.com": 1.00,
        "cnbctv18.com": 0.90,
        "ndtvprofit.com": 0.88,
    }

    def __init__(self, timeout_sec: float = 2.0):
        self.timeout_sec = timeout_sec

    @staticmethod
    def _safe_text(value: Optional[str]) -> str:
        return (value or "").strip()

    @staticmethod
    def _extract_domain(url: str) -> str:
        try:
            return urlparse(url).netloc.lower().replace("www.", "")
        except Exception:
            return ""

    def _google_news_rss(self, query: str, max_items: int = 12) -> List[Dict]:
        rss_url = (
            "https://news.google.com/rss/search"
            f"?q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"
        )
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            resp = requests.get(rss_url, timeout=self.timeout_sec, headers=headers)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception as exc:
            log.debug("News RSS fetch failed for query '%s': %s", query, exc)
            return []

        out: List[Dict] = []
        for item in root.findall(".//item")[:max_items]:
            title = self._safe_text(item.findtext("title"))
            link = self._safe_text(item.findtext("link"))
            pub_date = self._safe_text(item.findtext("pubDate"))
            source_node = item.find("source")
            source = self._safe_text(source_node.text if source_node is not None else "")
            out.append(
                {
                    "title": title,
                    "link": link,
                    "source": source,
                    "pub_date": pub_date,
                }
            )
        return out

    def _score_headline(self, title: str, source_url: str, source_name: str) -> Dict:
        t = title.lower()
        pos_hits = sum(1 for w in self.POSITIVE_TERMS if w in t)
        neg_hits = sum(1 for w in self.NEGATIVE_TERMS if w in t)
        cat_hits = sum(1 for w in self.CATALYST_TERMS if w in t)

        domain = self._extract_domain(source_url)
        src_weight = self.SOURCE_WEIGHT.get(domain, 0.80 if source_name else 0.75)

        sentiment = pos_hits - neg_hits
        raw = (sentiment * 1.4) + (cat_hits * 0.7)
        weighted = raw * src_weight
        label = "positive" if sentiment > 0 else "negative" if sentiment < 0 else "neutral"
        return {
            "sentiment_score": sentiment,
            "catalyst_hits": cat_hits,
            "source_weight": src_weight,
            "weighted_score": weighted,
            "label": label,
        }

    def analyze_symbol(self, symbol: str, company_name: str = "") -> Dict:
        symbol = self._safe_text(symbol).upper()
        if not symbol:
            return {
                "symbol": "",
                "news_items": 0,
                "news_breakout_score": 50.0,
                "confidence": 0.0,
                "sentiment_bias": "neutral",
                "top_headlines": [],
            }

        query = f"{symbol} NSE stock breakout OR results OR order OR upgrade"
        if company_name:
            query = f"{company_name} {query}"
        news = self._google_news_rss(query=query, max_items=12)

        if not news:
            return {
                "symbol": symbol,
                "news_items": 0,
                "news_breakout_score": 50.0,
                "confidence": 0.0,
                "sentiment_bias": "neutral",
                "top_headlines": [],
            }

        scored = []
        weighted_sum = 0.0
        sentiment_total = 0
        catalyst_total = 0
        for n in news:
            row = n.copy()
            s = self._score_headline(
                title=row.get("title", ""),
                source_url=row.get("link", ""),
                source_name=row.get("source", ""),
            )
            row.update(s)
            scored.append(row)
            weighted_sum += float(s["weighted_score"])
            sentiment_total += int(s["sentiment_score"])
            catalyst_total += int(s["catalyst_hits"])

        # Map weighted score to 0..100 with neutral around 50.
        normalized = 50.0 + max(-35.0, min(35.0, weighted_sum * 2.0))
        confidence = min(100.0, max(0.0, (len(news) / 12.0) * 70.0 + (min(10, catalyst_total) * 3.0)))
        if sentiment_total > 2:
            bias = "bullish"
        elif sentiment_total < -2:
            bias = "bearish"
        else:
            bias = "neutral"

        top_headlines = sorted(scored, key=lambda x: float(x.get("weighted_score", 0.0)), reverse=True)[:5]
        return {
            "symbol": symbol,
            "news_items": len(news),
            "news_breakout_score": round(float(normalized), 2),
            "confidence": round(float(confidence), 2),
            "sentiment_bias": bias,
            "catalyst_hits": catalyst_total,
            "top_headlines": top_headlines,
            "analyzed_at_utc": datetime.now(timezone.utc).isoformat(),
        }

    def rank_breakout_candidates(self, symbols: List[str], company_map: Optional[Dict[str, str]] = None) -> List[Dict]:
        company_map = company_map or {}
        out: List[Dict] = []
        for sym in symbols:
            s = self.analyze_symbol(sym, company_map.get(sym.upper(), ""))
            out.append(s)
        out.sort(key=lambda x: (x.get("news_breakout_score", 50.0), x.get("confidence", 0.0)), reverse=True)
        return out

