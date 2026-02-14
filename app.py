"""
app.py – Streamlit dashboard for the Halal Stock Trading System.
Run with:  streamlit run app.py
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import json, os

# ── page config (MUST be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="🕌 Halal Stock Trading System",
    page_icon="🕌",
    layout="wide",
    initial_sidebar_state="expanded",
)

from config import (TOTAL_CAPITAL, CAPITAL_PER_TRADE, BACKTEST_WEEKS,
                    CACHE_FILE, PATTERN_WINDOW_DAYS,
                    PRICE_MIN, PRICE_MAX)
from scraper       import scrape_halal_stocks
from market_data   import fetch_all, company_info
from trend_filter  import filter_uptrend_stocks, build_summary_table, classify_trend
from pattern_engine import find_similar_patterns, pattern_summary
from backtester    import backtest_ticker, best_strategy, summary_table, expected_value_table
from live_engine   import (generate_live_signals, calc_levels_2to1,
                            monitor_open_positions, fetch_live_daily)


# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stSidebar"] { background: #0f1117; }
h1,h2,h3 { font-family: 'Segoe UI', sans-serif; }
.metric-card {
    background: #1e2130; border-radius: 10px;
    padding: 16px; text-align: center; margin: 4px;
}
.green  { color: #00c49f; }
.red    { color: #ff4d4f; }
.amber  { color: #ffc107; }
div[data-testid="stMetricValue"] { font-size: 1.6rem; font-weight: 700; }
</style>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  SESSION STATE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _init_state():
    defaults = dict(
        halal_stocks=[], market_data={}, trend_list=[],
        backtest_results={}, capital=TOTAL_CAPITAL,
        per_trade=CAPITAL_PER_TRADE, weeks=BACKTEST_WEEKS,
        price_min=PRICE_MIN, price_max=PRICE_MAX,
        data_loaded=False,
        live_signals=[], open_positions=[],
    )
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()
S = st.session_state

# ── Zerodha redirect handler (runs on EVERY page load) ───────────────────────
# After Zerodha login, the browser is sent back to this app with
# ?request_token=XXXX in the URL.  We must catch it here — before any page
# renders — so the token is exchanged and cached immediately.
try:
    from zerodha_auth import ZerodhaSession
    from config import ZERODHA_API_KEY, ZERODHA_API_SECRET
    if ZERODHA_API_KEY and ZERODHA_API_SECRET:
        _zs = ZerodhaSession()
        if _zs.handle_redirect():
            st.rerun()          # re-render clean (URL query params now gone)
except Exception:
    pass   # silently skip if kiteconnect not installed yet


# ══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.title("🕌 Halal Trading")
    st.markdown("---")

    page = st.radio("Navigate", [
        "🏠 Overview",
        "📋 Stock Universe",
        "📈 Trend Analysis",
        "🔬 Backtest Results",
        "🔍 Pattern Analysis",
        "🎯 Trade Recommendations",
        "🔴 Live Signals",
        "⚙️ Settings",
    ], label_visibility="collapsed")

    st.markdown("---")
    st.markdown("**Capital Settings**")
    S.capital   = st.number_input("Total Capital (₹)", 10_000, 50_00_000,
                                   S.capital, step=10_000)
    S.per_trade = st.number_input("Per Trade (₹)", 5_000, S.capital,
                                   min(S.per_trade, S.capital), step=5_000)
    S.weeks     = st.slider("Backtest Window (weeks)", 2, 12, S.weeks)

    st.markdown("---")
    st.markdown("**📊 Price Range Filter**")
    st.caption("Only stocks in this ₹ range are downloaded & analysed. "
               "Narrowing the range speeds up Refresh Data significantly.")

    S.price_min = st.number_input(
        "Min Price (₹)", min_value=0, max_value=99_999,
        value=S.price_min, step=50,
        help="Skip stocks cheaper than this price")

    S.price_max = st.number_input(
        "Max Price (₹)  [0 = no limit]", min_value=0, max_value=1_00_000,
        value=S.price_max, step=50,
        help="Skip stocks more expensive than this. Set 0 to disable the cap.")

    # Live indicator showing current range
    if S.price_max > 0:
        st.info(f"🔍 Filter: ₹{S.price_min:,} – ₹{S.price_max:,}")
    else:
        st.info(f"🔍 Filter: ₹{S.price_min:,} and above (no upper limit)")

    st.markdown("---")

    col1, col2 = st.columns(2)
    if col1.button("🔄 Refresh\nData", use_container_width=True):
        with st.spinner("Scraping halal list…"):
            S.halal_stocks = scrape_halal_stocks(force_refresh=True)
        tickers = [s["nse_ticker"] for s in S.halal_stocks if s["nse_ticker"]]

        # ── progress callback with skipped-stock awareness ────────────────
        bar      = st.progress(0, text="Checking prices…")
        skipped_count   = [0]
        downloaded_count = [0]

        def _cb(i, total, ticker, skipped=False, price=None, reason=""):
            pct       = i / total
            price_str = f"₹{price:,.0f}" if price else "N/A"
            if skipped:
                skipped_count[0] += 1
                bar.progress(pct,
                    text=f"⏭ Skipped {ticker} ({price_str} — outside range)  "
                         f"[{i}/{total}]")
            else:
                downloaded_count[0] += 1
                bar.progress(pct,
                    text=f"📥 Fetching {ticker} ({price_str})  [{i}/{total}]")

        S.market_data = fetch_all(
            tickers,
            weeks_back = S.weeks,
            price_min  = S.price_min,
            price_max  = S.price_max,
            progress_cb= _cb,
        )
        bar.empty()

        with st.spinner("Classifying trends…"):
            S.trend_list = filter_uptrend_stocks(S.market_data)
        S.backtest_results = {}
        S.data_loaded = True
        st.success(
            f"✅ Loaded **{downloaded_count[0]}** stocks  |  "
            f"⏭ Skipped **{skipped_count[0]}** (outside ₹{S.price_min:,}"
            f"{'–₹'+str(f'{S.price_max:,}') if S.price_max > 0 else '+'} range)"
        )
        st.rerun()

    if col2.button("🧪 Backtest\nAll", use_container_width=True):
        if not S.market_data:
            st.warning("Click Refresh Data first.")
        else:
            uptrend_tickers = [t["ticker"] for t in S.trend_list if t["is_uptrend"]]
            bar = st.progress(0, text="Backtesting…")
            for i, ticker in enumerate(uptrend_tickers, 1):
                df = S.market_data.get(ticker)
                if df is not None:
                    S.backtest_results[ticker] = backtest_ticker(
                        df, S.capital, S.per_trade, S.weeks)
                bar.progress(i/len(uptrend_tickers),
                             text=f"Backtesting {ticker} ({i}/{len(uptrend_tickers)})")
            bar.empty()
            st.success(f"Backtested {len(S.backtest_results)} stocks")
            st.rerun()

    st.markdown("---")
    if S.data_loaded:
        up = sum(1 for t in S.trend_list if t["is_uptrend"])
        st.metric("Halal Stocks",   len(S.halal_stocks))
        st.metric("Data Loaded",    len(S.market_data))
        st.metric("In Uptrend",     up)
        st.metric("Backtested",     len(S.backtest_results))


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _candle_chart(df, ticker, title=""):
    fig = go.Figure()
    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"], name="Price",
        increasing_line_color="#00c49f", decreasing_line_color="#ff4d4f"))

    for ma, color in [("SMA_20","#ffc107"),("SMA_50","#00aaff"),("SMA_200","#ff6b6b")]:
        if ma in df.columns:
            fig.add_trace(go.Scatter(x=df.index, y=df[ma],
                                     name=ma, line=dict(color=color,width=1)))
    fig.update_layout(title=title or ticker, height=420,
                      xaxis_rangeslider_visible=False,
                      template="plotly_dark", margin=dict(l=0,r=0,t=40,b=0))
    return fig


def _rsi_chart(df):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df["RSI"], name="RSI",
                             line=dict(color="#ffc107")))
    fig.add_hline(y=70, line_dash="dash", line_color="red",   annotation_text="70")
    fig.add_hline(y=30, line_dash="dash", line_color="green", annotation_text="30")
    fig.update_layout(height=200, template="plotly_dark",
                      margin=dict(l=0,r=0,t=10,b=0), showlegend=False)
    return fig


def _equity_chart(eq_df, label=""):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=eq_df["date"], y=eq_df["equity"],
                             fill="tozeroy", name=label,
                             line=dict(color="#00c49f")))
    fig.update_layout(height=260, template="plotly_dark",
                      margin=dict(l=0,r=0,t=10,b=0))
    return fig


def _no_data_warning():
    st.info("👆 Click **Refresh Data** in the sidebar to load the latest Halal stock universe.")


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════

if page == "🏠 Overview":
    st.title("🕌 Halal Stock Trading System")
    st.caption("Automated Shariah-compliant swing trading · Powered by halalstock.in + yfinance")

    if not S.data_loaded:
        _no_data_warning()
        with st.expander("ℹ️ How this works", expanded=True):
            st.markdown("""
**Step 1:** Click **Refresh Data** (sidebar) — scrapes halalstock.in, fetches market data, classifies trends.

**Step 2:** Click **Backtest All** — runs all 5 strategies on every uptrend stock using recent weeks.

**Step 3:** Navigate pages to explore:
- 📋 **Stock Universe** — full Halal list with trend status
- 📈 **Trend Analysis** — filtered uptrend stocks with charts
- 🔬 **Backtest Results** — strategy comparison tables
- 🔍 **Pattern Analysis** — finds similar historical patterns
- 🎯 **Trade Recommendations** — best stock + strategy combos
""")
    else:
        up  = sum(1 for t in S.trend_list if t["is_uptrend"])
        bt  = len(S.backtest_results)

        c1,c2,c3,c4 = st.columns(4)
        c1.metric("📋 Halal Stocks",   len(S.halal_stocks))
        c2.metric("📊 Data Loaded",    len(S.market_data))
        c3.metric("🟢 In Uptrend",     up)
        c4.metric("🔬 Backtested",     bt)

        # Top performers from trend_list
        st.markdown("### 🏆 Top Uptrend Stocks")
        top = [t for t in S.trend_list if t["is_uptrend"]][:10]
        if top:
            df_top = build_summary_table(top)
            st.dataframe(df_top, use_container_width=True, hide_index=True)

        if S.backtest_results:
            st.markdown("### 🎯 Top Strategy Recommendations")
            recs = []
            for ticker, strat_results in S.backtest_results.items():
                b = best_strategy(strat_results)
                if b and b["total_profit"] > 0:
                    recs.append({
                        "Ticker":          ticker,
                        "Best Strategy":   b["strategy"],
                        "Recommendation":  b["recommendation"],
                        "Return %":        b["total_return_pct"],
                        "Win Rate %":      b["win_rate"],
                        "Profit (₹)":      b["total_profit"],
                        "Profit Factor":   b["profit_factor"],
                    })
            if recs:
                df_recs = pd.DataFrame(recs).sort_values("Return %",ascending=False)
                st.dataframe(df_recs.head(10), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: STOCK UNIVERSE
# ══════════════════════════════════════════════════════════════════════════════

elif page == "📋 Stock Universe":
    st.title("📋 Halal Stock Universe")

    if not S.halal_stocks:
        _no_data_warning()
    else:
        # Merge halal info with trend data
        trend_map = {t["ticker"]: t for t in S.trend_list}

        rows = []
        for s in S.halal_stocks:
            tick = s["nse_ticker"]
            tr   = trend_map.get(tick, {})
            rows.append({
                "NSE Ticker":  tick,
                "Company":     s["company"],
                "Industry":    s["industry"],
                "Trend":       tr.get("trend_label", "⏳ No data"),
                "Score":       tr.get("trend_score", "-"),
                "Price (₹)":   tr.get("current_price", "-"),
                "RSI":         tr.get("rsi", "-"),
                "ADX":         tr.get("adx", "-"),
                "20D Ret %":   tr.get("change_20d_pct", "-"),
            })

        df_all = pd.DataFrame(rows)

        # Filters
        col1, col2 = st.columns(2)
        trend_filter = col1.multiselect(
            "Filter by Trend",
            ["🟢 STRONG UP","🟢 UP","🟡 NEUTRAL","🔴 DOWN","🔴 STRONG DOWN"],
            default=["🟢 STRONG UP","🟢 UP"])
        industry_list = sorted(df_all["Industry"].dropna().unique().tolist())
        ind_filter    = col2.multiselect("Filter by Industry", industry_list, default=[])

        mask = df_all["Trend"].isin(trend_filter) if trend_filter else pd.Series([True]*len(df_all))
        if ind_filter:
            mask = mask & df_all["Industry"].isin(ind_filter)

        st.dataframe(df_all[mask].reset_index(drop=True),
                     use_container_width=True, hide_index=True)
        st.caption(f"Showing {mask.sum()} of {len(df_all)} Halal stocks")


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: TREND ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

elif page == "📈 Trend Analysis":
    st.title("📈 Trend Analysis")

    if not S.trend_list:
        _no_data_warning()
    else:
        uptrend = [t for t in S.trend_list if t["is_uptrend"]]
        st.success(f"**{len(uptrend)} stocks** are in confirmed uptrend "
                   f"(out of {len(S.trend_list)} fetched)")

        tab1, tab2 = st.tabs(["📊 Summary Table", "🔍 Individual Stock"])

        with tab1:
            df_up = build_summary_table(uptrend)
            st.dataframe(df_up, use_container_width=True, hide_index=True)

            # Scatter: RSI vs 20D Return
            fig = px.scatter(df_up, x="RSI", y="20D Return %",
                             size="ADX", color="Score",
                             hover_name="Ticker",
                             color_continuous_scale="RdYlGn",
                             title="RSI vs 20-Day Return (bubble = ADX strength)",
                             template="plotly_dark")
            st.plotly_chart(fig, use_container_width=True)

        with tab2:
            tickers_up = [t["ticker"] for t in uptrend]
            if tickers_up:
                sel = st.selectbox("Select stock", tickers_up)
                df_sel = S.market_data.get(sel)
                trend_info = next((t for t in uptrend if t["ticker"]==sel), {})

                if df_sel is not None:
                    # Metrics row
                    m1,m2,m3,m4,m5 = st.columns(5)
                    m1.metric("Price (₹)",  trend_info.get("current_price","—"))
                    m2.metric("RSI",        trend_info.get("rsi","—"))
                    m3.metric("ADX",        trend_info.get("adx","—"))
                    m4.metric("20D Return", f"{trend_info.get('change_20d_pct',0):.2f}%")
                    m5.metric("Trend Score",trend_info.get("trend_score","—"))

                    # Signal checklist
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown("**Technical Signals**")
                        flags = [
                            ("Price > SMA 200", trend_info.get("price_above_sma200")),
                            ("Price > SMA 50",  trend_info.get("price_above_sma50")),
                            ("Golden Cross",    trend_info.get("golden_cross")),
                            ("MACD Bullish",    trend_info.get("macd_bullish")),
                            ("RSI Healthy",     trend_info.get("rsi_healthy")),
                            ("ADX Trending",    trend_info.get("adx_trending")),
                        ]
                        for label, val in flags:
                            st.write("✅" if val else "❌", label)

                    with c2:
                        st.markdown("**Key Levels**")
                        st.write(f"Support:    ₹{trend_info.get('support','—')}")
                        st.write(f"Resistance: ₹{trend_info.get('resistance','—')}")
                        st.write(f"vs SMA50:   {trend_info.get('pct_from_sma50','—')}%")
                        st.write(f"vs SMA200:  {trend_info.get('pct_from_sma200','—')}%")

                    recent_df = df_sel[df_sel.index >= df_sel.index[-1] - timedelta(weeks=max(S.weeks*2,8))]
                    st.plotly_chart(_candle_chart(recent_df, sel), use_container_width=True)
                    st.plotly_chart(_rsi_chart(recent_df),         use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: BACKTEST RESULTS
# ══════════════════════════════════════════════════════════════════════════════

elif page == "🔬 Backtest Results":
    st.title("🔬 Backtest Results")

    if not S.backtest_results:
        st.info("Click **Backtest All** in the sidebar first.")
    else:
        # Aggregate best-per-ticker table
        agg_rows = []
        for ticker, strat_results in S.backtest_results.items():
            b = best_strategy(strat_results)
            if b:
                agg_rows.append({
                    "Ticker":         ticker,
                    "Best Strategy":  b["strategy"],
                    "Return %":       b["total_return_pct"],
                    "Annualised %":   b["annualised_return"],
                    "Win Rate %":     b["win_rate"],
                    "Profit (₹)":     b["total_profit"],
                    "Profit Factor":  b["profit_factor"],
                    "Max DD %":       b["max_drawdown"],
                    "Trades":         b["total_trades"],
                    "Recommendation": b["recommendation"],
                })
        df_agg = pd.DataFrame(agg_rows).sort_values("Return %",ascending=False)

        st.markdown("### 🏆 Best Strategy per Stock")
        st.dataframe(df_agg.reset_index(drop=True),
                     use_container_width=True, hide_index=True)

        # Detailed view for one stock
        st.markdown("---")
        st.markdown("### 🔍 Deep Dive – Single Stock")
        sel_ticker = st.selectbox("Select ticker", list(S.backtest_results.keys()))

        if sel_ticker and sel_ticker in S.backtest_results:
            strat_results = S.backtest_results[sel_ticker]
            df_sum = summary_table(strat_results)

            tab1, tab2, tab3 = st.tabs(["📊 Strategy Comparison",
                                         "📋 Trade Log",
                                         "📈 Equity Curves"])
            with tab1:
                st.dataframe(df_sum, use_container_width=True, hide_index=True)

                fig = px.bar(df_sum, x="Strategy", y="Return %",
                             color="Win Rate %", color_continuous_scale="RdYlGn",
                             title="Total Return % by Strategy",
                             template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)

            with tab2:
                sel_strat = st.selectbox("Strategy", list(strat_results.keys()))
                if sel_strat in strat_results:
                    tr_df = strat_results[sel_strat]["trades_df"]
                    st.dataframe(tr_df, use_container_width=True, hide_index=True)
                    wins = len(tr_df[tr_df["result"]=="WIN"])
                    loss = len(tr_df[tr_df["result"]=="LOSS"])
                    fig2 = go.Figure(data=[go.Pie(
                        labels=["Wins","Losses"], values=[wins, loss],
                        marker_colors=["#00c49f","#ff4d4f"])])
                    fig2.update_layout(height=280, template="plotly_dark")
                    st.plotly_chart(fig2, use_container_width=True)

            with tab3:
                fig3 = go.Figure()
                colors = ["#00c49f","#ffc107","#00aaff","#ff6b6b","#c97cf5"]
                for i, (name, r) in enumerate(strat_results.items()):
                    eq = r["equity_curve"]
                    fig3.add_trace(go.Scatter(
                        x=eq["date"], y=eq["equity"], name=name,
                        line=dict(color=colors[i % len(colors)])))
                fig3.add_hline(y=S.capital, line_dash="dash",
                               line_color="white", annotation_text="Initial Capital")
                fig3.update_layout(height=400, template="plotly_dark",
                                   title="Equity Curves – All Strategies")
                st.plotly_chart(fig3, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: PATTERN ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

elif page == "🔍 Pattern Analysis":
    st.title("🔍 Pattern Recognition")
    st.caption("Finds historical windows that look like the current setup and shows what happened next.")

    if not S.market_data:
        _no_data_warning()
    else:
        all_tickers = list(S.market_data.keys())
        sel = st.selectbox("Select stock", all_tickers)
        window = st.slider("Pattern window (days)", 5, 20, PATTERN_WINDOW_DAYS)

        if sel:
            df = S.market_data[sel]
            with st.spinner("Searching for similar patterns…"):
                matches  = find_similar_patterns(df, window=window, backtest_weeks=S.weeks)
                pat_sum  = pattern_summary(matches)

            if not matches:
                st.warning("No strong pattern matches found. Try a wider window or different stock.")
            else:
                # Summary metrics
                c1,c2,c3,c4 = st.columns(4)
                c1.metric("Matches Found",    pat_sum["num_matches"])
                c2.metric("Avg Similarity",   f"{pat_sum['avg_similarity']}%")
                c3.metric("Historical Win Rate", f"{pat_sum['win_rate_pct']}%")
                c4.metric("Avg Outcome",      f"{pat_sum['avg_outcome_pct']:+.2f}%")

                conf_color = {"HIGH":"green","MEDIUM":"amber","LOW":"red"}
                cconf = conf_color.get(pat_sum["confidence"],"amber")
                st.markdown(f"**Pattern Confidence:** "
                            f"<span class='{cconf}'>{pat_sum['confidence']}</span>",
                            unsafe_allow_html=True)

                st.markdown("---")

                # Current pattern chart
                st.subheader("Current Price Pattern (Last N Days)")
                cur = df["Close"].iloc[-window:]
                cur_norm = (cur - cur.min()) / (cur.max() - cur.min() + 1e-9)
                fig_cur = go.Figure()
                fig_cur.add_trace(go.Scatter(
                    x=list(range(window)), y=cur_norm.values,
                    name="Current Pattern",
                    line=dict(color="#00c49f", width=3)))
                fig_cur.update_layout(height=200, template="plotly_dark",
                                      margin=dict(t=10,b=0))
                st.plotly_chart(fig_cur, use_container_width=True)

                # Individual matches
                st.subheader("📅 Historical Similar Patterns")
                for i, m in enumerate(matches, 1):
                    with st.expander(
                        f"Match #{i} | {m['date_start']} – {m['date_end']} | "
                        f"Similarity {m['similarity_pct']}% | "
                        f"Outcome: {m['outcome_pct']:+.2f}% {m['outcome_label']}"
                    ):
                        col1, col2 = st.columns(2)
                        col1.metric("Similarity",     f"{m['similarity_pct']}%")
                        col1.metric("Entry Price",    f"₹{m['entry_price']}")
                        col2.metric("Outcome",        f"{m['outcome_pct']:+.2f}%")
                        col2.metric("Exit Price",     f"₹{m['exit_price']}")

                        # Overlay chart: matched pattern vs what followed
                        fig_ov = go.Figure()
                        fig_ov.add_trace(go.Scatter(
                            x=list(range(window)), y=m["pattern_norm"],
                            name="Historical Match",
                            line=dict(color="#ffc107")))
                        fig_ov.add_trace(go.Scatter(
                            x=list(range(window, window*2)), y=m["future_norm"],
                            name="What Happened Next",
                            line=dict(color="#00c49f" if m["outcome_pct"]>0 else "#ff4d4f",
                                      dash="dot")))
                        fig_ov.add_vline(x=window-0.5, line_dash="dash",
                                         line_color="white",
                                         annotation_text="Entry Point")
                        fig_ov.update_layout(height=220, template="plotly_dark",
                                              margin=dict(t=10,b=0))
                        st.plotly_chart(fig_ov, use_container_width=True)

                        col1.write(f"**Period:** {m['date_start']} → {m['date_end']}")
                        col2.write(f"**Label:** {m['outcome_label']}")


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: TRADE RECOMMENDATIONS
# ══════════════════════════════════════════════════════════════════════════════

elif page == "🎯 Trade Recommendations":
    st.title("🎯 Trade Recommendations")

    if not S.backtest_results:
        st.info("Click **Backtest All** in the sidebar to generate recommendations.")
    else:
        trend_map = {t["ticker"]: t for t in S.trend_list}

        # Build recommendation list
        recs = []
        for ticker, strat_results in S.backtest_results.items():
            b   = best_strategy(strat_results)
            tr  = trend_map.get(ticker, {})
            if not b or b["total_profit"] <= 0:
                continue

            df   = S.market_data.get(ticker)
            atr  = tr.get("atr", 0) or 0
            price= tr.get("current_price", 0) or 0
            stop = round(price - 2 * atr, 2) if atr else round(price * 0.98, 2)
            risk = price - stop
            tgt1 = round(price + 2.0 * risk, 2)
            tgt2 = round(price + 2.5 * risk, 2)
            qty  = int(S.per_trade / price) if price > 0 else 0
            inv  = round(qty * price, 2)
            max_loss = round(qty * risk, 2)
            exp_prof = round(qty * (tgt1 - price), 2)

            recs.append({
                "ticker":      ticker,
                "company":     next((s["company"] for s in S.halal_stocks
                                     if s["nse_ticker"]==ticker), ticker),
                "strategy":    b["strategy"],
                "rec":         b["recommendation"],
                "price":       price,
                "stop":        stop,
                "target1":     tgt1,
                "target2":     tgt2,
                "qty":         qty,
                "investment":  inv,
                "max_loss":    max_loss,
                "exp_profit":  exp_prof,
                "win_rate":    b["win_rate"],
                "return_pct":  b["total_return_pct"],
                "pf":          b["profit_factor"],
                "trend_score": tr.get("trend_score", 0),
            })

        # Sort: STRONG BUY first, then return %
        order = {"⭐ STRONG BUY":4,"✅ BUY":3,"🟡 WATCH":2,"❌ SKIP":1}
        recs.sort(key=lambda x:(order.get(x["rec"],0), x["return_pct"]), reverse=True)

        st.success(f"**{len(recs)} actionable trades** identified from Halal uptrend stocks")

        for i, r in enumerate(recs[:10], 1):
            with st.expander(
                f"{r['rec']}  **{r['ticker']}** — {r['strategy']} | "
                f"Return: {r['return_pct']:+.1f}% | "
                f"Win Rate: {r['win_rate']}%",
                expanded=(i <= 3)
            ):
                st.markdown(f"### {r['company']} ({r['ticker']})")

                # Trade setup
                c1,c2,c3,c4,c5 = st.columns(5)
                c1.metric("Buy At (₹)",     r["price"])
                c2.metric("Stop Loss (₹)",  r["stop"],
                           delta=f"-{abs(r['price']-r['stop']):.2f}",
                           delta_color="inverse")
                c3.metric("Target 1 (₹)",  r["target1"],
                           delta=f"+{abs(r['target1']-r['price']):.2f}")
                c4.metric("Target 2 (₹)",  r["target2"],
                           delta=f"+{abs(r['target2']-r['price']):.2f}")
                c5.metric("Qty (shares)",   r["qty"])

                c1b,c2b,c3b,c4b = st.columns(4)
                c1b.metric("Investment (₹)",  r["investment"])
                c2b.metric("Max Loss (₹)",    r["max_loss"])
                c3b.metric("Expected Profit", f"₹{r['exp_profit']}")
                c4b.metric("Risk/Reward",     f"1 : {r['target1']-r['price']:.0f}/{r['price']-r['stop']:.0f}" )

                # Why selected
                st.markdown("#### 🔍 Why This Stock Was Selected")
                tr = trend_map.get(r["ticker"], {})
                col_why, col_bt = st.columns(2)
                with col_why:
                    st.markdown("**Technical Criteria Met:**")
                    checks = [
                        ("Price > SMA 200", tr.get("price_above_sma200")),
                        ("Price > SMA 50",  tr.get("price_above_sma50")),
                        ("Golden Cross",    tr.get("golden_cross")),
                        ("MACD Bullish",    tr.get("macd_bullish")),
                        ("ADX Trending",    tr.get("adx_trending")),
                        ("RSI Healthy",     tr.get("rsi_healthy")),
                    ]
                    for label, val in checks:
                        st.write(("✅" if val else "❌"), label)

                with col_bt:
                    st.markdown("**Backtest Performance:**")
                    bt = S.backtest_results.get(r["ticker"], {}).get(r["strategy"], {})
                    if bt:
                        st.write(f"📊 Trades (last {S.weeks}w): {bt.get('total_trades',0)}")
                        st.write(f"🎯 Win Rate: {bt.get('win_rate',0):.1f}%")
                        st.write(f"💰 Profit Factor: {bt.get('profit_factor',0):.2f}")
                        st.write(f"📈 Total Return: {bt.get('total_return_pct',0):+.2f}%")
                        st.write(f"📉 Max Drawdown: {bt.get('max_drawdown',0):.2f}%")
                        st.write(f"⏱️ Avg Hold: {bt.get('avg_hold_days',0):.1f} days")

                # Pattern analysis summary
                df_stock = S.market_data.get(r["ticker"])
                if df_stock is not None:
                    matches = find_similar_patterns(df_stock, backtest_weeks=S.weeks)
                    ps      = pattern_summary(matches)
                    if ps:
                        st.markdown("**📐 Pattern Recognition:**")
                        st.write(f"Found {ps['num_matches']} similar historical patterns | "
                                 f"Avg outcome: {ps['avg_outcome_pct']:+.2f}% | "
                                 f"Historical win rate: {ps['win_rate_pct']}% | "
                                 f"Confidence: **{ps['confidence']}**")

                # Equity curve
                if bt:
                    st.plotly_chart(_equity_chart(bt.get("equity_curve", pd.DataFrame()),
                                                  r["strategy"]),
                                    use_container_width=True)

                # Price chart
                df_s = S.market_data.get(r["ticker"])
                if df_s is not None:
                    recent = df_s[df_s.index >= df_s.index[-1] - timedelta(weeks=S.weeks*2)]
                    fig_t = _candle_chart(recent, r["ticker"])
                    # Add stop / target lines
                    fig_t.add_hline(y=r["stop"],    line_color="red",   line_dash="dash",
                                    annotation_text="Stop")
                    fig_t.add_hline(y=r["target1"], line_color="green", line_dash="dash",
                                    annotation_text="T1")
                    fig_t.add_hline(y=r["target2"], line_color="cyan",  line_dash="dot",
                                    annotation_text="T2")
                    st.plotly_chart(fig_t, use_container_width=True)

        # Export button
        if recs:
            st.markdown("---")
            export_rows = []
            for r in recs:
                export_rows.append({
                    "Ticker":r["ticker"],"Company":r["company"],
                    "Strategy":r["strategy"],"Recommendation":r["rec"],
                    "Entry (₹)":r["price"],"Stop Loss (₹)":r["stop"],
                    "Target 1 (₹)":r["target1"],"Target 2 (₹)":r["target2"],
                    "Quantity":r["qty"],"Investment (₹)":r["investment"],
                    "Max Loss (₹)":r["max_loss"],"Expected Profit (₹)":r["exp_profit"],
                    "Win Rate %":r["win_rate"],"Return %":r["return_pct"],
                })
            df_exp = pd.DataFrame(export_rows)
            csv = df_exp.to_csv(index=False).encode()
            st.download_button("📥 Download Recommendations CSV",
                               csv, "trade_recommendations.csv",
                               "text/csv", use_container_width=True)



# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: LIVE SIGNALS  (★ NEW)
# ══════════════════════════════════════════════════════════════════════════════

elif page == "🔴 Live Signals":
    st.title("🔴 Live Signals — 2:1 Risk:Reward Engine")
    st.caption("Fetches real-time prices · validates via recent backtest · enforces strict 2:1 R:R")

    # ── 2:1 explainer ─────────────────────────────────────────────────────────
    with st.expander("📐 How 2:1 Risk:Reward Works", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("""
**Strict 2:1 Rule applied to every trade:**
- **Stop Loss** = Entry − (1.5 × ATR)
- **Target 1**  = Entry + (1 × Risk)  → exit 50%, move stop to breakeven
- **Target 2**  = Entry + (2 × Risk)  → exit remaining 50%

**Why 2:1?**
- Break-even win rate = **only 33.3%**
- At 40% win rate → EV = +0.2R per trade
- At 50% win rate → EV = +0.5R per trade
- *Even losing more than you win, you still profit!*
""")
        with c2:
            ev_df = expected_value_table(risk_per_trade=S.per_trade * 0.02)
            st.markdown("**Expected Value Table** (at 2:1 R:R)")
            st.dataframe(ev_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── Controls ───────────────────────────────────────────────────────────────
    col_btn1, col_btn2, col_btn3 = st.columns([2,2,3])

    run_live = col_btn1.button("🔴 Scan Live Signals", use_container_width=True, type="primary")
    refresh_pos = col_btn2.button("🔄 Refresh Positions", use_container_width=True)

    if run_live:
        if not S.halal_stocks:
            st.warning("Click **Refresh Data** first to load Halal stock list.")
        else:
            uptrend_tickers = [t["ticker"] for t in S.trend_list if t["is_uptrend"]]
            if not uptrend_tickers:
                st.warning("No uptrend stocks found. Run Refresh Data + Backtest All first.")
            else:
                bar = st.progress(0, text="Scanning live signals…")
                def _live_cb(i, total, ticker):
                    bar.progress(i/total, text=f"Scanning {ticker} ({i}/{total})")

                S.live_signals = generate_live_signals(
                    tickers          = uptrend_tickers,
                    halal_info       = S.halal_stocks,
                    total_capital    = S.capital,
                    capital_per_trade= S.per_trade,
                    weeks_back       = S.weeks,
                    progress_cb      = _live_cb,
                )
                bar.empty()
                st.success(f"Found **{len(S.live_signals)} live signals** across uptrend Halal stocks!")
                st.rerun()

    # ── Live signal cards ──────────────────────────────────────────────────────
    if S.live_signals:
        # Summary metrics
        strong = [s for s in S.live_signals if s["recommendation"] == "⭐ STRONG SIGNAL"]
        good   = [s for s in S.live_signals if s["recommendation"] == "✅ GOOD SIGNAL"]
        weak   = [s for s in S.live_signals if s["recommendation"] == "🟡 WEAK SIGNAL"]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Signals",    len(S.live_signals))
        m2.metric("⭐ Strong",         len(strong))
        m3.metric("✅ Good",           len(good))
        m4.metric("🟡 Weak",           len(weak))

        st.caption(f"Last scanned: {datetime.now().strftime('%d %b %Y %H:%M:%S')}")
        st.markdown("---")

        # ── Filter ────────────────────────────────────────────────────────────
        filter_rec = st.multiselect(
            "Show signals",
            ["⭐ STRONG SIGNAL","✅ GOOD SIGNAL","🟡 WEAK SIGNAL"],
            default=["⭐ STRONG SIGNAL","✅ GOOD SIGNAL"])

        filtered = [s for s in S.live_signals if s["recommendation"] in filter_rec]

        if not filtered:
            st.info("No signals match the selected filter.")
        else:
            # ── Signal cards ──────────────────────────────────────────────────
            for sig in filtered:
                conf_color = (
                    "#00c49f" if sig["confidence"] >= 75 else
                    "#ffc107" if sig["confidence"] >= 55 else "#ff6b6b"
                )
                bt_edge = "above" if sig["bt_win_rate"] > 33.3 else "below"
                intra_tag = "✅ Intraday confirmed" if sig["intra_confirmed"] else "⚠️ Daily signal only"

                with st.expander(
                    f"{sig['recommendation']}  **{sig['ticker']}** — {sig['strategy']}  |  "
                    f"Confidence: {sig['confidence']}/100  |  {intra_tag}",
                    expanded=(sig["confidence"] >= 75)
                ):
                    st.markdown(f"### {sig['company']} ({sig['ticker']})"
                                f"  —  *{sig['industry']}*")

                    # ── TOP METRICS ───────────────────────────────────────────
                    c1,c2,c3,c4,c5,c6 = st.columns(6)
                    c1.metric("Live Price (₹)",  sig["live_price"])
                    c2.metric("RSI",             sig["rsi"])
                    c3.metric("ADX",             sig["adx"])
                    c4.metric("Vol Ratio",       sig["vol_ratio"])
                    c5.metric("ATR (₹)",         sig["atr"])
                    c6.metric("Confidence",      f"{sig['confidence']}/100")

                    st.markdown("---")

                    # ── 2:1 TRADE SETUP ───────────────────────────────────────
                    st.markdown("#### 🎯 Trade Setup (Strict 2:1 R:R)")

                    ta, tb, tc, td = st.columns(4)
                    ta.metric("📥 Entry (₹)",   sig["entry"],
                               help="Buy at this price")
                    tb.metric("🛑 Stop Loss (₹)", sig["stop"],
                               delta=f"−₹{sig['risk_per_share']:.2f} per share",
                               delta_color="inverse",
                               help="Exit 100% here — hard stop")
                    tc.metric("🎯 Target 1 (₹)", sig["target_1"],
                               delta=f"+₹{sig['risk_per_share']:.2f} (1:1)",
                               help="Exit 50% here, move stop to breakeven")
                    td.metric("🏆 Target 2 (₹)", sig["target_2"],
                               delta=f"+₹{2*sig['risk_per_share']:.2f} (2:1)",
                               help="Exit remaining 50% here — main target")

                    te, tf, tg, th = st.columns(4)
                    te.metric("Qty (shares)",   sig["qty"])
                    tf.metric("Investment (₹)", sig["investment"])
                    tg.metric("Max Loss (₹)",   sig["max_loss"],
                               help="If stop hit — total loss on this trade")
                    th.metric("Exp Profit (₹)", sig["avg_expected_profit"],
                               help="Average expected profit: 50% exit at T1, 50% at T2")

                    # R:R diagram
                    risk_r  = sig["risk_per_share"]
                    rw1     = sig["target_1"] - sig["entry"]
                    rw2     = sig["target_2"] - sig["entry"]
                    st.markdown(
                        f"""
<div style='background:#1e2130;border-radius:8px;padding:12px;margin:8px 0;font-family:monospace'>
<b>Risk:Reward Breakdown</b><br>
Risk&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;= ₹{risk_r:.2f} per share (stop distance)<br>
Reward T1 = ₹{rw1:.2f} per share → <b style='color:#ffc107'>1:1</b> (exit 50%)<br>
Reward T2 = ₹{rw2:.2f} per share → <b style='color:#00c49f'>2:1 ★</b> (exit 50%)<br>
Capital at risk: <b>{sig['risk_pct_of_capital']:.2f}%</b> of ₹{S.capital:,}<br>
Expected reward: <b>{sig['reward_pct_of_capital']:.2f}%</b> of capital if T2 hit
</div>
""", unsafe_allow_html=True)

                    st.markdown("---")

                    # ── BACKTEST VALIDATION ───────────────────────────────────
                    st.markdown("#### 🔬 Backtest Validation (Last"
                                f" {S.weeks} weeks — 2:1 R:R)")

                    if sig["bt_trades"] == 0:
                        st.info("No trades in backtest window yet — signal is new. "
                                "EV calculated at assumed 45% win rate.")
                    else:
                        b1,b2,b3,b4,b5 = st.columns(5)
                        b1.metric("Trades",        sig["bt_trades"])
                        b2.metric("Win Rate",       f"{sig['bt_win_rate']:.1f}%",
                                   delta=f"Break-even: 33.3%",
                                   delta_color="normal" if sig["bt_win_rate"]>33.3 else "inverse")
                        b3.metric("Profit Factor",  f"{sig['bt_profit_factor']:.2f}")
                        b4.metric("Return %",       f"{sig['bt_return_pct']:+.2f}%")
                        b5.metric("Max DD %",       f"{sig['bt_max_dd']:.2f}%")

                        # EV bar
                        ev = sig["ev_total"]
                        ev_color = "#00c49f" if ev > 0 else "#ff4d4f"
                        st.markdown(
                            f"**Expected Value per trade:** "
                            f"<span style='color:{ev_color};font-size:1.2em'>"
                            f"₹{ev:+,.2f}</span>  "
                            f"({'profitable edge ✅' if ev>0 else 'negative edge ❌'})",
                            unsafe_allow_html=True
                        )
                        st.markdown(
                            f"Break-even win rate at 2:1 R:R = **33.3%**  |  "
                            f"Your strategy win rate = **{sig['bt_win_rate']:.1f}%**  |  "
                            f"Edge = **{sig['bt_win_rate']-33.3:+.1f}%** above break-even",
                        )

                    st.markdown("---")

                    # ── PRICE CHART ───────────────────────────────────────────
                    df_s = S.market_data.get(sig["ticker"])
                    if df_s is not None:
                        recent = df_s[df_s.index >= df_s.index[-1] - timedelta(weeks=S.weeks*3)]
                        fig = _candle_chart(recent, sig["ticker"],
                                            f"{sig['ticker']} — {sig['strategy']}")

                        entry_val = sig["entry"]
                        fig.add_hline(y=sig["stop"],     line_color="#ff4d4f",
                                      line_dash="dash", line_width=2,
                                      annotation_text=f"Stop ₹{sig['stop']}")
                        fig.add_hline(y=sig["target_1"], line_color="#ffc107",
                                      line_dash="dash", line_width=2,
                                      annotation_text=f"T1 ₹{sig['target_1']} (1:1)")
                        fig.add_hline(y=sig["target_2"], line_color="#00c49f",
                                      line_dash="dash", line_width=2,
                                      annotation_text=f"T2 ₹{sig['target_2']} (2:1)")
                        # Shade risk zone (stop → entry) and reward zone (entry → T2)
                        fig.add_hrect(y0=sig["stop"],  y1=entry_val,
                                      fillcolor="rgba(255,77,79,0.1)",  line_width=0)
                        fig.add_hrect(y0=entry_val, y1=sig["target_2"],
                                      fillcolor="rgba(0,196,159,0.08)", line_width=0)
                        st.plotly_chart(fig, use_container_width=True)

                    # ── ADD TO WATCHLIST ──────────────────────────────────────
                    if st.button(f"➕ Add {sig['ticker']} to Open Positions",
                                  key=f"add_{sig['ticker']}_{sig['strategy']}"):
                        pos = {
                            "ticker":    sig["ticker"],
                            "strategy":  sig["strategy"],
                            "entry":     sig["entry"],
                            "stop":      sig["stop"],
                            "target_1":  sig["target_1"],
                            "target_2":  sig["target_2"],
                            "qty":       sig["qty"],
                            "investment":sig["investment"],
                            "added_at":  datetime.now().strftime("%d %b %Y %H:%M"),
                        }
                        # Avoid duplicates
                        existing = [p["ticker"] for p in S.open_positions]
                        if sig["ticker"] not in existing:
                            S.open_positions.append(pos)
                            st.success(f"Added {sig['ticker']} to Open Positions tracker!")
                        else:
                            st.info(f"{sig['ticker']} already in open positions.")

        # ── CSV EXPORT ────────────────────────────────────────────────────────
        if filtered:
            st.markdown("---")
            export_rows = [{
                "Ticker":         s["ticker"],
                "Company":        s["company"],
                "Strategy":       s["strategy"],
                "Signal":         s["recommendation"],
                "Confidence":     s["confidence"],
                "Live Price":     s["live_price"],
                "Entry":          s["entry"],
                "Stop Loss":      s["stop"],
                "Target 1 (1:1)": s["target_1"],
                "Target 2 (2:1)": s["target_2"],
                "Qty":            s["qty"],
                "Investment":     s["investment"],
                "Max Loss":       s["max_loss"],
                "Expected Profit":s["avg_expected_profit"],
                "BT Win Rate %":  s["bt_win_rate"],
                "BT Profit Factor": s["bt_profit_factor"],
                "EV per Trade":   s["ev_total"],
                "Intraday OK":    s["intra_confirmed"],
            } for s in filtered]
            csv = pd.DataFrame(export_rows).to_csv(index=False).encode()
            st.download_button("📥 Download Live Signals CSV", csv,
                               "live_signals.csv", "text/csv",
                               use_container_width=True)

    # ── OPEN POSITIONS MONITOR ─────────────────────────────────────────────────
    if S.open_positions or refresh_pos:
        st.markdown("---")
        st.markdown("## 📊 Open Positions Monitor")

        if refresh_pos and S.open_positions:
            with st.spinner("Fetching latest prices…"):
                S.open_positions = monitor_open_positions(S.open_positions)
            st.success("Positions refreshed!")

        if not S.open_positions:
            st.info("No open positions tracked. Add trades from the signals above.")
        else:
            for j, pos in enumerate(S.open_positions):
                live_px   = pos.get("live_price",  pos["entry"])
                pnl       = pos.get("unrealised_pnl", 0) or 0
                status    = pos.get("status", "🟡 IN TRADE")
                pnl_color = "#00c49f" if pnl >= 0 else "#ff4d4f"

                with st.expander(
                    f"{status}  **{pos['ticker']}** — {pos['strategy']}  |  "
                    f"P&L: ₹{pnl:+,.2f}",
                    expanded=True
                ):
                    p1,p2,p3,p4,p5,p6 = st.columns(6)
                    p1.metric("Entry",       f"₹{pos['entry']}")
                    p2.metric("Live Price",  f"₹{live_px}")
                    p3.metric("Stop",        f"₹{pos['stop']}")
                    p4.metric("T1",          f"₹{pos['target_1']}")
                    p5.metric("T2",          f"₹{pos['target_2']}")
                    p6.metric("P&L",         f"₹{pnl:+,.2f}")

                    if pos.get("pct_to_stop"):
                        st.progress(
                            min(1.0, max(0.0, abs(pos.get("pct_to_t2",1)) /
                                         (abs(pos.get("pct_to_stop",1)) + abs(pos.get("pct_to_t2",1)) + 0.001))),
                            text=f"Position progress  |  "
                                 f"Stop: {pos.get('pct_to_stop',0):+.2f}%  "
                                 f"T1: {pos.get('pct_to_t1',0):+.2f}%  "
                                 f"T2: {pos.get('pct_to_t2',0):+.2f}%"
                        )

                    if st.button(f"❌ Remove {pos['ticker']}", key=f"rm_{j}"):
                        S.open_positions = [p for p in S.open_positions
                                              if p["ticker"] != pos["ticker"]]
                        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: SETTINGS
# ══════════════════════════════════════════════════════════════════════════════

elif page == "⚙️ Settings":
    st.title("⚙️ Settings & Capital Configuration")

    st.markdown("### 💰 Capital Management Explained")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("""
**Total Capital** — Your full trading budget.
All risk calculations are based on this.

**Per Trade Capital** — Fixed amount invested in each trade.
*Recommended:* 20-25% of total (allows 4-5 simultaneous positions).

**Backtest Window** — How many recent weeks to test.
*Recommended:* 4 weeks = current market conditions.
""")
    with c2:
        cap    = S.capital
        pt     = S.per_trade
        wks    = S.weeks

        # Example calc
        price_ex  = 3500
        stop_ex   = price_ex * 0.98
        qty_ex    = int(pt / price_ex)
        risk_ex   = round(qty_ex * (price_ex - stop_ex), 2)
        tgt_ex    = round(price_ex + 2.5 * (price_ex - stop_ex), 2)
        profit_ex = round(qty_ex * (tgt_ex - price_ex), 2)

        st.markdown("**Example Trade Calculation:**")
        st.table(pd.DataFrame({
            "Item": ["Total Capital","Per Trade","Stock Price","Qty Bought",
                     "Max Loss (stop)","Target","Expected Profit"],
            "Value": [f"₹{cap:,}", f"₹{pt:,}", f"₹{price_ex}",
                      f"{qty_ex} shares", f"₹{risk_ex}",
                      f"₹{tgt_ex}", f"₹{profit_ex}"]
        }))

    st.markdown("---")
    st.markdown("### 📊 Return Percentage Guide")
    st.markdown("""
| Term | Formula | Meaning |
|------|---------|---------|
| **Trade Return %** | Profit ÷ Trade Investment | % gain on the money you put in |
| **Capital Return %** | Profit ÷ Total Capital | % gain on your FULL capital |
| **Monthly Return %** | Sum of all trade profits ÷ Total Capital | Month's performance |
| **Annualised Return** | Monthly % × 12 | Projected yearly return |

> **Example:** ₹980 profit on ₹25,000 trade = **3.92% trade return** but only **0.98% capital return** (on ₹1 lakh total).
> Run 8 such trades in a month → **7.84% monthly return** → **~94% annualised**.
""")

    st.markdown("---")
    st.markdown("### 🔌 Zerodha Kite Connect — Live Trading")

    from zerodha_auth import ZerodhaSession, render_login_ui
    from config import (ZERODHA_API_KEY, ZERODHA_API_SECRET,
                        ZERODHA_REDIRECT_URL, ZERODHA_POSTBACK_URL,
                        ZERODHA_TOKEN_FILE)

    # ── Credential status ──────────────────────────────────────────────────────
    creds_ok = bool(ZERODHA_API_KEY and ZERODHA_API_SECRET)

    col_c1, col_c2 = st.columns(2)
    with col_c1:
        st.markdown("**Credential Status**")
        st.write("API Key:    ", "✅ Set" if ZERODHA_API_KEY    else "❌ Not set")
        st.write("API Secret: ", "✅ Set" if ZERODHA_API_SECRET else "❌ Not set")

    with col_c2:
        st.markdown("**URL Configuration**")
        st.code(f"Redirect URL : {ZERODHA_REDIRECT_URL or '(not set)'}")
        st.code(f"Postback URL : {ZERODHA_POSTBACK_URL or '(not set — optional for local dev)'}")

    if not creds_ok:
        st.warning(
            "**To go live:** open `config.py` and fill in your "
            "`ZERODHA_API_KEY`, `ZERODHA_API_SECRET`, and "
            "`ZERODHA_REDIRECT_URL`.  "
            "Get these from [developers.kite.trade](https://developers.kite.trade)."
        )
    else:
        st.success("Credentials configured — ready to authenticate.")

        # ── Auth panel ────────────────────────────────────────────────────────
        zs = ZerodhaSession()

        # Always handle redirect first (reads ?request_token= from URL)
        if zs.handle_redirect():
            st.success("✅ Zerodha login successful! Token cached for today.")
            st.rerun()

        if zs.is_authenticated():
            st.success("🟢 **Authenticated** — access token is valid for today.")

            if st.button("🚪 Logout / Refresh Token"):
                zs.logout()
                st.info("Logged out. Click Login to get a fresh token.")
                st.rerun()

            # ── Live order test panel ─────────────────────────────────────────
            st.markdown("#### 📤 Place a Test Order")
            st.caption("Use small quantity to verify everything works before going live.")

            with st.form("test_order_form"):
                oc1, oc2, oc3 = st.columns(3)
                sym = oc1.text_input("Symbol (NSE)", value="TCS",
                                      help="NSE trading symbol, e.g. TCS")
                qty = oc2.number_input("Quantity", min_value=1, value=1)
                txn = oc3.selectbox("Buy / Sell", ["BUY","SELL"])

                ot1, ot2, ot3 = st.columns(3)
                order_type = ot1.selectbox("Order Type", ["MARKET","LIMIT","SL","SL-M"])
                price      = ot2.number_input("Limit Price (₹)", min_value=0.0, value=0.0,
                                               help="Required for LIMIT orders")
                trigger    = ot3.number_input("Trigger Price (₹)", min_value=0.0, value=0.0,
                                               help="Required for SL / SL-M orders")

                product = st.radio("Product", ["MIS (Intraday)","CNC (Delivery)"],
                                    horizontal=True)

                submitted = st.form_submit_button("📤 Place Order", type="primary")

            if submitted:
                from zerodha_auth import place_order
                kite = zs.kite()
                if kite:
                    result = place_order(
                        kite, sym, qty,
                        transaction_type = txn,
                        order_type       = order_type,
                        price            = price   or None,
                        trigger_price    = trigger or None,
                        product          = "MIS" if "MIS" in product else "CNC",
                    )
                    if result["success"]:
                        st.success(f"✅ Order placed! Order ID: `{result['order_id']}`")
                    else:
                        st.error(f"❌ Order failed: {result['error']}")

            # ── Live positions ─────────────────────────────────────────────────
            if st.button("📊 View Positions & Orders"):
                from zerodha_auth import get_orders, get_positions
                kite = zs.kite()
                if kite:
                    orders = get_orders(kite)
                    pos    = get_positions(kite)

                    st.markdown("**Today's Orders:**")
                    if orders:
                        st.dataframe(pd.DataFrame(orders), use_container_width=True)
                    else:
                        st.info("No orders placed today.")

                    st.markdown("**Open Positions:**")
                    net = pos.get("net", [])
                    if net:
                        st.dataframe(pd.DataFrame(net), use_container_width=True)
                    else:
                        st.info("No open positions.")

        else:
            # ── Login button ──────────────────────────────────────────────────
            st.markdown("#### 🔐 Login to Zerodha")
            st.info(
                "After clicking Login, you will be taken to Zerodha's login page. "
                "Once you log in, Zerodha redirects you back here automatically "
                f"with a token in the URL (`{ZERODHA_REDIRECT_URL}?request_token=...`)."
                "  The app reads it, exchanges it, and you're authenticated."
            )
            login_url = zs.login_url()
            st.markdown(
                f"""<a href="{login_url}" target="_self">
  <button style="background:#387ed1;color:white;border:none;
    padding:12px 32px;border-radius:6px;font-size:16px;
    cursor:pointer;font-weight:600;width:100%">
    🔐 Login with Zerodha
  </button></a>""",
                unsafe_allow_html=True,
            )
            st.caption(f"Redirect URL: `{ZERODHA_REDIRECT_URL}`")

    # ── How to install kiteconnect ─────────────────────────────────────────────
    st.markdown("---")
    with st.expander("📦 How to install kiteconnect SDK"):
        st.code("pip install kiteconnect", language="bash")
        st.markdown("""
Once installed, the app automatically uses Zerodha for:
- Live price quotes
- Historical OHLCV data (replaces yfinance)
- Order placement (BUY / SELL)
- Real-time order status via postback

**To switch data source** after login, change in `config.py`:
```python
DATA_SOURCE = "zerodha"   # was "yfinance"
```
""")

    # ── Postback URL setup guide ───────────────────────────────────────────────
    st.markdown("---")
    with st.expander("📬 Postback URL Setup (order notifications)"):
        st.markdown("""
**What is it?**
Zerodha sends a POST request to your postback URL every time an order is
filled, rejected, or cancelled — in real time.

**Local development (no postback needed):**
Leave `ZERODHA_POSTBACK_URL` blank in `config.py`.
Use `get_orders(kite)` to poll order status manually.

**Production (live server):**
1. Deploy the app on a server with a public domain
2. Set `ZERODHA_POSTBACK_URL = "https://yourdomain.com/postback"` in `config.py`
3. Add this Flask/FastAPI endpoint to your server:

```python
# postback_server.py  (run separately on port 5000)
from flask import Flask, request
from zerodha_auth import parse_postback

app = Flask(__name__)

@app.route("/postback", methods=["POST"])
def postback():
    data = parse_postback(request.form.to_dict())
    print(data["message"])
    # Update your database / notify users here
    return "OK", 200
```

4. Enter `https://yourdomain.com/postback` in the Kite developer portal.
""")

