# Meezan Edge — Changelog

All notable changes to this project are documented here.
Format: `[v{major}.{minor}.{patch}] — YYYY-MM-DD`

---

## [v1.5.0] — 2026-02-15
### Added
- **Persistent data cache** (`data_cache.py`) — market data now survives browser tab close, server restarts, and redeployments. Stores trend results + halal list in JSON.
- **Cache age alerts** — amber warning after 14 days, red alert after 60 days
- **Download / Upload cache** — export cache as JSON to restore after redeployment without re-fetching
- **Strategy filter** — new "Best For" column in Stock Universe: tags each stock as Swing, Momentum, Breakout, Mean Revert, or None based on indicator profile
- **Strategy quick-filter buttons** — one-click filter to show only stocks suited to a chosen strategy
- **Changelog page** — version history accessible from ⚙️ Settings → Changelog tab
- **App version badge** — version shown in sidebar footer

### Changed
- Refresh Data now saves to persistent cache automatically
- Sidebar data-age banner replaces generic "Data Loaded" metric
- Stock Universe page reorganised with strategy filter panel at top

---

## [v1.4.0] — 2026-02-15
### Fixed
- **Redirect loop** (`too many redirects`) — removed all `st.query_params.clear()` calls; replaced with `_SS_PROCESSED` session-state flag so token is exchanged exactly once per session without HTTP redirects
- `handle_redirect()` now returns `True/False` only; no internal URL manipulation

---

## [v1.3.0] — 2026-02-14
### Fixed
- Zerodha token exchange failing with `Missing or empty field authorize` — root cause was missing `X-Kite-Version: 3` header in raw HTTPS fallback path
- Added `_KITE_HEADERS` constant shared across all Kite API calls
- `render_login_ui()` no longer calls `handle_redirect()` internally (prevented double-exchange)
- Login button changed from `target="_self"` to `target="_blank"` — prevents Zerodha JS being blocked inside iframe context

---

## [v1.2.0] — 2026-02-14
### Added
- **Zerodha Kite Connect integration** (`zerodha_auth.py`) — full OAuth flow, token caching, order placement, positions, holdings
- `DATA_SOURCE` config toggle: `"yfinance"` ↔ `"zerodha"`
- `active_data_source()` helper — shows live data source in sidebar
- Sidebar login banner — always-visible 🟡/🟢 Zerodha status + one-click login button
- Manual token fallback form in Settings for when automatic redirect fails
- Debug panel in Settings showing exact URLs and received query params

### Changed
- `config.py` credentials now read from `st.secrets` (Streamlit Cloud safe) — API keys never hardcoded
- `market_data.py` fully refactored with `_fetch_yfinance` / `_fetch_zerodha` layers — routes based on `DATA_SOURCE`
- Zerodha token stored in `st.session_state` (primary) + file (local fallback)

---

## [v1.1.0] — 2026-02-14
### Added
- **Price range filter** — two-phase fetch: quick 2-day price check before full history download
- `quick_price_check()` and `in_price_range()` in `market_data.py`
- Price range filter UI in sidebar (Min/Max price inputs)
- Progress bar now shows price of each stock and skipped stocks
- Speed improvement: 60–87% fewer API calls for typical price ranges

### Changed
- `fetch_all()` now accepts `price_min` / `price_max` params

---

## [v1.0.0] — 2026-02-13
### Initial Release
- Halal stock list scraper (halalstock.in via BeautifulSoup)
- Market data fetcher (yfinance) with full indicator suite
- Trend classifier (9-signal score, 5 levels)
- 5 trading strategies: MA Crossover, RSI Mean Revert, MACD Momentum, BB Squeeze, ADX Breakout
- Backtester with strict 2:1 R:R enforcement
- Pattern recognition engine (cosine similarity, top-3 matches)
- Live signals engine with intraday data
- Streamlit dashboard (8 pages)
- GitHub private repo + Streamlit Cloud deployment guide
- Zerodha developer portal registration guide

---

## Version Numbering

| Digit | Meaning | Example trigger |
|-------|---------|----------------|
| Major | Breaking change or major new feature set | New trading engine, full UI rewrite |
| Minor | New feature, non-breaking | New page, new filter, new integration |
| Patch | Bug fix, small improvement | Fix crash, tweak label, correct formula |
