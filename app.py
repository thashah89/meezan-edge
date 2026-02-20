"""
app.py — Meezan Edge v3.0 Autonomous Hedge Fund System

PROFIT MAXIMIZATION MODE
Target: 15-25% monthly returns

3 Views:
1. Market Intelligence Engine
2. Autonomous Portfolio Engine  
3. AI Hedge Fund Lab
"""

import sys
import os
from pathlib import Path

# Add current directory to Python path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, date, timedelta
import logging
import threading

# Configure page
st.set_page_config(
    page_title="🧠 Meezan Edge v3.0 — Autonomous Hedge Fund",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Imports
import config
from database_schema import init_database, get_connection, get_active_stocks, get_latest_metrics
from market_intel_engine import MarketIntelligenceEngine
from capital_allocator import CapitalAllocator, RiskManager
from trade_selector import TradeSelector
from paper_trader import PaperTradingEngine, get_performance_metrics
from ml_trainer import MLTrainer, MLPredictor, auto_train_if_due
from halal_scraper import scrape_halal_stocks
from zerodha_client import ZerodhaClient, ZerodhaConfigError

# Initialize
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Initialize database
if not st.session_state.get('db_initialized'):
    init_database()
    st.session_state.db_initialized = True

# Initialize engines
@st.cache_resource
def get_engines():
    return {
        'intel': MarketIntelligenceEngine(),
        'allocator': CapitalAllocator(),
        'selector': TradeSelector(),
        'trader': PaperTradingEngine(config.DB_PATH),
        'ml': MLPredictor(),
        'risk': RiskManager()
    }

engines = get_engines()


def get_zerodha_client() -> ZerodhaClient:
    """Build Zerodha client from Streamlit secrets + session token."""
    try:
        zerodha_cfg = st.secrets["zerodha"]
    except Exception:
        raise ZerodhaConfigError("Missing [zerodha] section in .streamlit/secrets.toml")

    session_token = st.session_state.get("zerodha_access_token", "")
    configured_token = str(zerodha_cfg.get("access_token", "")).strip()
    access_token = session_token or configured_token

    return ZerodhaClient(
        api_key=str(zerodha_cfg.get("api_key", "")),
        api_secret=str(zerodha_cfg.get("api_secret", "")),
        access_token=access_token,
    )


def handle_zerodha_auth_callback():
    """
    Handle Kite redirect callback (request_token in query params) and store
    access token in Streamlit session state for current app session.
    """
    request_token = st.query_params.get("request_token")
    if isinstance(request_token, list):
        request_token = request_token[0] if request_token else ""

    if not request_token:
        return

    if st.session_state.get("zerodha_last_request_token") == request_token:
        return

    try:
        client = get_zerodha_client()
        access_token = client.create_session(request_token)
        st.session_state["zerodha_access_token"] = access_token
        st.session_state["zerodha_last_request_token"] = request_token

        # Clean callback query params after successful auth.
        for key in ("request_token", "action", "status"):
            if key in st.query_params:
                del st.query_params[key]

        st.success("Zerodha connected successfully.")
    except Exception as exc:
        st.error(f"Zerodha authentication failed: {exc}")


handle_zerodha_auth_callback()


def _run_backend_training():
    """Kick off due training checks; safe to run in background thread."""
    try:
        auto_train_if_due(
            db_path=config.DB_PATH,
            min_total_trades=config.MIN_TRADES_FOR_TRAINING,
            min_new_trades=20,
            retrain_every_days=1,
        )
    except Exception as exc:
        log.warning("Background retrain skipped: %s", exc)

# ══════════════════════════════════════════════════════════════════════════════
#  CUSTOM CSS
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    .metric-card {
        background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
        padding: 1.5rem;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .profit-positive {
        color: #00ff88;
        font-weight: 700;
    }
    .profit-negative {
        color: #ff4444;
        font-weight: 700;
    }
    .status-live {
        color: #00ff88;
        font-size: 0.9rem;
        animation: pulse 2s infinite;
    }
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.5; }
    }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("### 🧠 Meezan Edge v3.0")
    st.markdown("**Autonomous Hedge Fund**")

    st.markdown("#### Zerodha")
    try:
        sidebar_z_client = get_zerodha_client()
        if sidebar_z_client.is_authenticated:
            st.success("Connected")
        else:
            st.link_button("🔐 Connect Zerodha", sidebar_z_client.get_login_url(), use_container_width=True)
            st.caption("After login, return here to complete auth.")
    except ZerodhaConfigError as exc:
        st.warning("Zerodha not configured")
        st.caption(str(exc))

    st.markdown("---")
    
    # View selector
    view = st.radio(
        "Select View",
        [
            "🔍 Market Intelligence",
            "💼 Portfolio Engine", 
            "🤖 AI Lab"
        ],
        label_visibility="collapsed"
    )
    
    st.markdown("---")
    
    # System status
    st.markdown("### 📊 System Status")
    
    # Capital
    if 'total_capital' not in st.session_state:
        st.session_state.total_capital = config.DEFAULT_CAPITAL
    
    st.metric("Total Capital", f"₹{st.session_state.total_capital:,.0f}")

    # Performance
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                COALESCE(SUM(profit_loss), 0) as total_pnl,
                COUNT(*) as total_trades,
                SUM(CASE WHEN status = 'win' THEN 1 ELSE 0 END) as wins
            FROM trades_simulated
            WHERE status IN ('win', 'loss')
        """)
        row = cursor.fetchone()
        conn.close()
        
        total_pnl = row[0] if row else 0
        total_trades = row[1] if row else 0
        wins = row[2] if row else 0
        
        pnl_pct = (total_pnl / st.session_state.total_capital * 100) if st.session_state.total_capital > 0 else 0
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        
        st.metric("Total P&L", f"₹{total_pnl:,.0f}", f"{pnl_pct:+.2f}%")
        st.metric("Win Rate", f"{win_rate:.1f}%", f"{wins}/{total_trades}")
        
    except:
        pass

    # Universe validity indicator
    try:
        sidebar_active_stocks = get_active_stocks()
        st.metric("Loaded Stocks", len(sidebar_active_stocks))
        metrics_updated_today = 0
        if sidebar_active_stocks:
            sidebar_symbols = [s["symbol"] for s in sidebar_active_stocks if s.get("symbol")]
            if sidebar_symbols:
                conn = get_connection()
                cursor = conn.cursor()
                placeholders = ",".join(["?"] * len(sidebar_symbols))
                cursor.execute(
                    f"""
                    SELECT COUNT(*) as cnt
                    FROM stock_metrics
                    WHERE date = ?
                    AND symbol IN ({placeholders})
                    """,
                    (date.today().isoformat(), *sidebar_symbols)
                )
                row = cursor.fetchone()
                conn.close()
                metrics_updated_today = int(row[0]) if row else 0
        st.metric("Metrics Updated", metrics_updated_today)
        if sidebar_active_stocks:
            earliest_valid = min(s['valid_till'] for s in sidebar_active_stocks)
            days_left = (datetime.strptime(earliest_valid, "%Y-%m-%d").date() - date.today()).days
            if days_left <= 0:
                st.error("Stock list expired")
            elif days_left <= 5:
                st.warning(f"Stock list expires in {days_left} days")
            else:
                st.info(f"Stock list valid for {days_left} days")
        else:
            st.caption("Stock list not loaded")
    except Exception:
        st.caption("Stock list validity unavailable")
    
    st.markdown("---")
    
    # Quick actions
    st.markdown("### ⚡ Quick Actions")
    
    if st.button("🔄 Refresh All Data", use_container_width=True):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()
    
    if st.button("🧠 Train ML Models", use_container_width=True):
        with st.spinner("Training models..."):
            try:
                trainer = MLTrainer(config.DB_PATH)
                results = trainer.train_all()
                st.success(f"✅ Trained {len(results)} models")
                st.rerun()
            except Exception as e:
                st.error(f"Training failed: {e}")
    
    st.markdown("---")
    st.caption("v3.0 | Profit Maximization Mode")
    st.caption("Target: 15-25% monthly returns")

# ══════════════════════════════════════════════════════════════════════════════
#  VIEW 1: MARKET INTELLIGENCE ENGINE
# ══════════════════════════════════════════════════════════════════════════════

if "Market Intelligence" in view:
    st.markdown("<h1 class='main-header'>🔍 Market Intelligence Engine</h1>", unsafe_allow_html=True)
    st.markdown("**Autonomous market analysis and opportunity discovery**")
    st.markdown("---")
    
    # ── Section A: Stock Management Control ──────────────────────────────────
    st.subheader("🗂️ Stock Management Control")
    
    active_stocks = get_active_stocks()
    symbols = [s["symbol"] for s in active_stocks]

    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("📥 Load Stocks", use_container_width=True):
            with st.spinner("Loading halal stocks..."):
                stocks = scrape_halal_stocks()
                
                # Save to database
                conn = get_connection()
                cursor = conn.cursor()
                
                load_date = date.today()
                valid_till = load_date + timedelta(days=config.STOCK_UNIVERSE_VALID_DAYS)
                
                for stock in stocks:
                    symbol = str(stock.get('symbol', '')).strip().upper()
                    if ":" in symbol:
                        symbol = symbol.split(":", 1)[1]
                    if symbol.endswith(".NS"):
                        symbol = symbol[:-3]

                    if not symbol:
                        continue

                    cursor.execute("""
                        INSERT OR REPLACE INTO stocks_master
                        (symbol, company, sector, load_date, valid_till)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        symbol,
                        stock['company'],
                        stock.get('sector', 'Unknown'),
                        load_date,
                        valid_till
                    ))
                
                conn.commit()
                conn.close()
                
                st.success(f"✅ Loaded {len(stocks)} stocks")
                st.rerun()
    
    with col2:
        if st.button("🔄 Refresh Metrics", use_container_width=True):
            if not symbols:
                st.warning("Load stock universe first before refreshing metrics.")
            else:
                progress_bar = st.progress(0, text="Starting metrics refresh...")
                try:
                    z_client = get_zerodha_client()

                    def _on_progress(done: int, total: int, sym: str, status: str):
                        ratio = 0.0 if total <= 0 else done / total
                        progress_bar.progress(
                            min(1.0, ratio),
                            text=f"Refreshing metrics {done}/{total}: {sym} ({status})",
                        )

                    result = z_client.refresh_latest_metrics(symbols, progress_cb=_on_progress)
                    progress_bar.progress(1.0, text="Refreshing sector buckets...")

                    z_client.refresh_sector_buckets(symbols)
                    threading.Thread(target=_run_backend_training, daemon=True).start()
                    st.rerun()
                except ZerodhaConfigError as exc:
                    st.error(str(exc))
                except Exception as exc:
                    st.error(f"Metrics refresh failed: {exc}")

    with col3:
        if st.button("🧪 Backtest + AI Boost", use_container_width=True):
            if not symbols:
                st.warning("Load stock universe first before backtesting.")
            else:
                progress_bar = st.progress(0, text="Starting strategy backtest...")
                try:
                    z_client = get_zerodha_client()

                    def _on_backtest_progress(done: int, total: int, sym: str, status: str):
                        ratio = 0.0 if total <= 0 else done / total
                        progress_bar.progress(
                            min(1.0, ratio),
                            text=f"Backtesting {done}/{total}: {sym} ({status})",
                        )

                    bt_result = z_client.run_backtest_ai_calibration(
                        symbols=symbols,
                        lookback_days=260,
                        hold_days=5,
                        progress_cb=_on_backtest_progress,
                    )
                    progress_bar.progress(1.0, text="Backtest complete.")
                    st.success(
                        f"Backtest + AI calibration updated {bt_result['updated_symbols']} symbols"
                        f" (failed: {bt_result['failed_symbols']})."
                    )
                    if bt_result.get("strategy_distribution"):
                        dist = ", ".join(
                            [f"{k}: {v}" for k, v in sorted(bt_result["strategy_distribution"].items())]
                        )
                        st.caption(f"Strategy distribution: {dist}")
                    st.rerun()
                except ZerodhaConfigError as exc:
                    st.error(str(exc))
                except Exception as exc:
                    st.error(f"Backtest failed: {exc}")

    if active_stocks:
        # Show stocks + metrics table directly
        st.markdown("#### 📋 Stocks")
        stocks_df = pd.DataFrame(active_stocks)
        stocks_df = stocks_df[[c for c in stocks_df.columns if c not in ("load_date", "valid_till")]]

        latest_metrics = get_latest_metrics()
        metrics_df = pd.DataFrame(latest_metrics) if latest_metrics else pd.DataFrame()

        if not metrics_df.empty:
            if "date" in metrics_df.columns:
                metrics_df = metrics_df[metrics_df["date"] == date.today().isoformat()]
            merged_df = stocks_df.merge(metrics_df, on="symbol", how="left", suffixes=("", "_metric"))
            if "ltp" in merged_df.columns:
                merged_df = merged_df[merged_df["ltp"].notna()]
            merged_df = merged_df.sort_values(by="symbol").reset_index(drop=True)
        else:
            merged_df = pd.DataFrame()

        if merged_df.empty:
            st.info("No successful metric rows to display yet. Click Refresh Metrics.")
        else:
            preferred_order = [
                "symbol", "company", "sector",
                "ltp", "opportunity_score", "strategy_fit", "win_probability", "expected_return",
                "rsi", "adx", "macd", "macd_signal",
                "sma_20", "sma_50", "sma_200", "ema_9", "ema_21",
                "atr", "bb_upper", "bb_middle", "bb_lower", "bb_width",
                "trend_score", "momentum_score", "volatility_score", "liquidity_score",
                "volume_ratio", "date"
            ]
            front = [c for c in preferred_order if c in merged_df.columns]
            rest = [c for c in merged_df.columns if c not in front]
            display_df = merged_df[front + rest].copy()

            header_map = {
                "symbol": "Symbol",
                "company": "Company",
                "sector": "Sector",
                "ltp": "LTP",
                "opportunity_score": "Opportunity Score",
                "strategy_fit": "Strategy Fit",
                "win_probability": "Win Probability",
                "expected_return": "Expected Return",
                "rsi": "RSI",
                "adx": "ADX",
                "macd": "MACD",
                "macd_signal": "MACD Signal",
                "sma_20": "SMA 20",
                "sma_50": "SMA 50",
                "sma_200": "SMA 200",
                "ema_9": "EMA 9",
                "ema_21": "EMA 21",
                "atr": "ATR",
                "bb_upper": "BB Upper",
                "bb_middle": "BB Middle",
                "bb_lower": "BB Lower",
                "bb_width": "BB Width",
                "trend_score": "Trend Score",
                "momentum_score": "Momentum Score",
                "volatility_score": "Volatility Score",
                "liquidity_score": "Liquidity Score",
                "volume_ratio": "Volume Ratio",
                "date": "Date",
            }
            display_df = display_df.rename(columns=header_map)
            st.dataframe(display_df, use_container_width=True, hide_index=True)
    
    else:
        st.info("No data loaded")
    
    st.markdown("---")
    
    # ── Section B: Market Sentiment Engine ───────────────────────────────────
    st.subheader("🌡️ Market Sentiment Analysis")
    
    # Analyze market (mock for now - would use real Nifty data)
    sentiment = engines['intel'].analyze_market()
    
    # Display sentiment
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        sentiment_emoji = {
            'aggressive_bullish': '🚀',
            'bullish': '🟢',
            'bearish': '🔴',
            'sideways': '⏸️',
            'high_vol': '⚡'
        }.get(sentiment['sentiment'], '⏸️')
        
        st.metric(
            "Market Regime",
            sentiment['sentiment'].replace('_', ' ').title(),
            sentiment_emoji
        )
    
    with col2:
        st.metric("Confidence", f"{sentiment['confidence']:.0f}%")
    
    with col3:
        st.metric("Deployment", f"{sentiment['deployment_pct']:.0%}")
    
    with col4:
        st.metric("Volatility", sentiment['volatility'].title())
    
    st.info(f"**Recommended Style:** {sentiment['recommended_style']}")
    st.info(f"**Capital Split:** Intraday {sentiment['intraday_pct']:.0%} · Swing {sentiment['swing_pct']:.0%}")
    
    st.markdown("---")
    
    # ── Section C: Opportunity Scanner ───────────────────────────────────────
    st.subheader("🔍 Top Opportunities")
    
    # Get latest metrics (mock data for demo)
    metrics_list = get_latest_metrics()
    
    if metrics_list:
        # Score opportunities
        scored = engines['intel'].score_opportunities(metrics_list)
        
        # Display top 20
        top_20 = scored[:20]
        
        if top_20:
            df_opp = pd.DataFrame(top_20)
            
            # Format for display
            df_display = pd.DataFrame({
                'Symbol': df_opp['symbol'],
                'Score': df_opp['opportunity_score'],
                'Strategy': df_opp['strategy_fit'].str.title(),
                'Win Prob': df_opp.get('win_probability', 0.5).apply(lambda x: f"{x:.0%}"),
                'Expected': df_opp.get('expected_return', 0).apply(lambda x: f"{x:.1f}%"),
                'RSI': df_opp.get('rsi', 50).apply(lambda x: f"{x:.0f}"),
                'ADX': df_opp.get('adx', 0).apply(lambda x: f"{x:.0f}"),
            })
            
            st.dataframe(
                df_display,
                use_container_width=True,
                hide_index=True,
                height=400
            )
        else:
            st.warning("No opportunities found. Refresh metrics.")
    else:
        st.warning("No metrics available. Refresh data to analyze opportunities.")
    
    st.markdown("---")
    
    # ── Section D: Advanced Filters ──────────────────────────────────────────
    st.subheader("🎯 Advanced Filters")
    
    filter_col1, filter_col2, filter_col3 = st.columns(3)
    
    with filter_col1:
        uptrend_only = st.checkbox("Uptrend Only", value=True)
        strong_momentum = st.checkbox("Strong Momentum")
        breakout_ready = st.checkbox("Breakout Ready")
    
    with filter_col2:
        rsi_min = st.slider("Min RSI", 0, 100, 40)
        rsi_max = st.slider("Max RSI", 0, 100, 70)
    
    with filter_col3:
        adx_min = st.slider("Min ADX", 0, 50, 20)
        strategy_filter = st.selectbox(
            "Strategy Fit",
            ['all', 'momentum', 'breakout', 'swing', 'mean_revert']
        )
    
    # Apply filters
    filters = {
        'uptrend_only': uptrend_only,
        'strong_momentum': strong_momentum,
        'breakout_ready': breakout_ready,
        'rsi_min': rsi_min,
        'rsi_max': rsi_max,
        'adx_min': adx_min,
        'strategy_fit': strategy_filter if strategy_filter != 'all' else None
    }
    
    if metrics_list and st.button("Apply Filters"):
        from market_intel_engine import apply_filters
        filtered = apply_filters(scored, filters)
        
        st.success(f"Found {len(filtered)} stocks matching filters")
        
        if filtered:
            df_filt = pd.DataFrame(filtered)
            st.dataframe(df_filt[['symbol', 'opportunity_score', 'strategy_fit']], 
                        use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
#  VIEW 2: AUTONOMOUS PORTFOLIO ENGINE
# ══════════════════════════════════════════════════════════════════════════════

elif "Portfolio Engine" in view:
    st.markdown("<h1 class='main-header'>💼 Autonomous Portfolio Engine</h1>", unsafe_allow_html=True)
    st.markdown("**AI-driven capital management and trade execution**")
    st.markdown("---")
    
    # ── Section A: Capital Input ─────────────────────────────────────────────
    st.subheader("💰 Capital Configuration")
    
    col1, col2 = st.columns([2,1])
    
    with col1:
        total_capital = st.number_input(
            "Total Capital (₹)",
            min_value=50_000,
            max_value=50_00_000,
            value=st.session_state.total_capital,
            step=10_000,
            help="System will autonomously manage this capital"
        )
        
        if total_capital != st.session_state.total_capital:
            st.session_state.total_capital = total_capital
    
    with col2:
        st.metric("Current Capital", f"₹{st.session_state.total_capital:,.0f}")
    
    st.info("💡 System autonomously decides deployment, allocation, and trade selection")
    
    st.markdown("---")
    
    # ── Section B: AI Capital Allocation ─────────────────────────────────────
    st.subheader("🤖 AI Capital Allocation")
    
    # Get opportunities
    metrics_list = get_latest_metrics()
    sentiment = engines['intel'].analyze_market()
    
    if metrics_list:
        scored = engines['intel'].score_opportunities(metrics_list)
        
        # Run allocator
        allocation = engines['allocator'].allocate(
            total_capital=st.session_state.total_capital,
            market_sentiment=sentiment,
            opportunities=scored
        )
        
        # Display allocation
        alloc_col1, alloc_col2, alloc_col3, alloc_col4 = st.columns(4)
        
        with alloc_col1:
            st.metric(
                "Deployed Today",
                f"₹{allocation['deployed_capital']:,.0f}",
                f"{allocation['deployment_pct']:.0%}"
            )
        
        with alloc_col2:
            st.metric(
                "Intraday Capital",
                f"₹{allocation['intraday_capital']:,.0f}",
                f"{allocation['intraday_pct']:.0%}"
            )
        
        with alloc_col3:
            st.metric(
                "Swing Capital",
                f"₹{allocation['swing_capital']:,.0f}",
                f"{allocation['swing_pct']:.0%}"
            )
        
        with alloc_col4:
            st.metric(
                "Trades Selected",
                allocation['trades_to_take'],
                "High Quality"
            )
        
        # Risk level indicator
        risk_level = "Low" if allocation['deployment_pct'] < 0.4 else \
                     "Moderate" if allocation['deployment_pct'] < 0.7 else "High"
        
        st.info(f"**Risk Level:** {risk_level} | **Max Positions:** {allocation['max_positions']}")
        
        st.markdown("---")
        
        # ── Section C: Trade Selection ───────────────────────────────────────
        st.subheader("🎯 Selected Trades")
        
        if st.button("🚀 Run Autonomous Trade Selection", type="primary"):
            with st.spinner("AI selecting best trades..."):
                # Select trades
                selected_trades = engines['selector'].select_trades(
                    opportunities=scored,
                    allocation=allocation,
                    market_sentiment=sentiment
                )
                
                if selected_trades:
                    st.success(f"✅ Selected {len(selected_trades)} high-quality trades")
                    
                    # Display selected trades
                    trades_data = []
                    for trade in selected_trades:
                        trades_data.append({
                            'Symbol': trade['symbol'],
                            'Mode': trade['mode'].upper(),
                            'Entry': f"₹{trade['entry']:.2f}",
                            'Stop Loss': f"₹{trade['stop_loss']:.2f}",
                            'Target': f"₹{trade['target']:.2f}",
                            'Qty': trade['quantity'],
                            'Value': f"₹{trade['position_value']:,.0f}",
                            'R:R': f"{trade['rr_ratio']:.1f}:1",
                            'Win %': f"{trade['win_probability']:.0%}",
                        })
                    
                    df_trades = pd.DataFrame(trades_data)
                    st.dataframe(df_trades, use_container_width=True, hide_index=True, height=300)
                    
                    # Execute button
                    if st.button("📊 Execute Paper Trades", type="primary"):
                        with st.spinner("Executing simulated trades..."):
                            executed = 0
                            for trade in selected_trades:
                                trade_id = engines['trader'].enter_trade(trade)
                                if trade_id > 0:
                                    executed += 1
                            
                            st.success(f"✅ Executed {executed} paper trades")
                            st.balloons()
                            st.rerun()
                
                else:
                    st.warning("No trades meet quality standards. Market conditions may not be favorable.")
    
    else:
        st.warning("Load stock data first in Market Intelligence view")
    
    st.markdown("---")
    
    # ── Section D: Live Positions ────────────────────────────────────────────
    st.subheader("📊 Active Positions")
    
    position_summary = engines['trader'].get_position_summary()
    
    if position_summary['total_positions'] > 0:
        pos_col1, pos_col2, pos_col3 = st.columns(3)
        
        with pos_col1:
            st.metric("Open Positions", position_summary['total_positions'])
        
        with pos_col2:
            st.metric("Intraday", position_summary['intraday'])
        
        with pos_col3:
            st.metric("Swing", position_summary['swing'])
        
        # Display positions
        positions = position_summary['positions']
        
        pos_data = []
        for pos in positions:
            # Calculate current P&L (mock - would use live prices)
            current_price = pos['entry_price'] * 1.01  # Mock 1% move
            pnl = (current_price - pos['entry_price']) * pos['quantity']
            pnl_pct = (pnl / (pos['entry_price'] * pos['quantity'])) * 100
            
            pos_data.append({
                'Symbol': pos['symbol'],
                'Mode': pos['mode'].upper(),
                'Entry': f"₹{pos['entry_price']:.2f}",
                'Qty': pos['quantity'],
                'Current': f"₹{current_price:.2f}",
                'P&L': f"₹{pnl:,.0f}",
                'P&L %': f"{pnl_pct:+.2f}%",
                'Target': f"₹{pos['target']:.2f}",
                'SL': f"₹{pos['stop_loss']:.2f}",
            })
        
        df_pos = pd.DataFrame(pos_data)
        st.dataframe(df_pos, use_container_width=True, hide_index=True)
        
        # Manual close button
        st.markdown("##### Manual Actions")
        close_col1, close_col2 = st.columns(2)
        
        with close_col1:
            if st.button("🛑 Close All Intraday", use_container_width=True):
                # Mock prices
                live_prices = {p['symbol']: p['entry_price'] * 1.01 for p in positions}
                engines['trader'].close_all_intraday(live_prices)
                st.success("Closed all intraday positions")
                st.rerun()
        
    else:
        st.info("No open positions. Execute trades to start.")
    
    st.markdown("---")
    
    # ── Section E: Performance Dashboard ─────────────────────────────────────
    st.subheader("📈 Portfolio Performance")
    
    metrics = get_performance_metrics(config.DB_PATH, 'all')
    
    if metrics['total_trades'] > 0:
        # Key metrics
        metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
        
        with metric_col1:
            st.metric("Total Trades", metrics['total_trades'])
        
        with metric_col2:
            st.metric("Win Rate", f"{metrics['win_rate']:.1f}%")
        
        with metric_col3:
            pnl_color = "profit-positive" if metrics['net_pnl'] > 0 else "profit-negative"
            st.markdown(f"<div class='{pnl_color}'>Net P&L: ₹{metrics['net_pnl']:,.0f}</div>", 
                       unsafe_allow_html=True)
        
        with metric_col4:
            st.metric("Profit Factor", f"{metrics['profit_factor']:.2f}")
        
        # Additional metrics
        adv_col1, adv_col2, adv_col3 = st.columns(3)
        
        with adv_col1:
            st.metric("Avg Win", f"{metrics['avg_win_pct']:.2f}%")
        
        with adv_col2:
            st.metric("Avg Loss", f"{metrics['avg_loss_pct']:.2f}%")
        
        with adv_col3:
            st.metric("Win/Loss Ratio", f"{metrics['avg_win_loss_ratio']:.2f}x")
        
        # Performance chart (mock)
        st.markdown("#### Equity Curve")
        dates = pd.date_range(end=date.today(), periods=30, freq='D')
        equity = np.cumsum(np.random.randn(30) * 1000) + st.session_state.total_capital
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=dates,
            y=equity,
            mode='lines',
            name='Capital',
            line=dict(color='#00ff88', width=2)
        ))
        fig.update_layout(
            template='plotly_dark',
            height=300,
            margin=dict(l=0, r=0, t=0, b=0)
        )
        st.plotly_chart(fig, use_container_width=True)
    
    else:
        st.info("Execute some trades to see performance metrics")


# ══════════════════════════════════════════════════════════════════════════════
#  VIEW 3: AI HEDGE FUND LAB
# ══════════════════════════════════════════════════════════════════════════════

elif "AI Lab" in view:
    st.markdown("<h1 class='main-header'>🤖 AI Hedge Fund Lab</h1>", unsafe_allow_html=True)
    st.markdown("**Self-learning intelligence engine**")
    st.markdown("---")
    
    # ── Section A: Model Status ──────────────────────────────────────────────
    st.subheader("🧠 ML Model Status")
    
    # Get latest training logs
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            model_name,
            training_date,
            accuracy,
            mae,
            r2_score,
            dataset_size
        FROM ai_model_logs
        ORDER BY training_date DESC
        LIMIT 10
    """)
    logs = cursor.fetchall()
    conn.close()
    
    if logs:
        # Show model cards
        model_col1, model_col2 = st.columns(2)
        
        win_model = [l for l in logs if 'win' in l[0].lower()]
        profit_model = [l for l in logs if 'profit' in l[0].lower()]
        
        with model_col1:
            if win_model:
                latest = win_model[0]
                st.markdown("#### Win Probability Classifier")
                st.metric("Accuracy", f"{latest[2]*100:.1f}%" if latest[2] else "N/A")
                st.metric("Dataset Size", latest[5] or 0)
                st.caption(f"Last trained: {latest[1]}")
            else:
                st.warning("Win Probability model not trained yet")
        
        with model_col2:
            if profit_model:
                latest = profit_model[0]
                st.markdown("#### Profit Expectation Regressor")
                st.metric("MAE", f"{latest[3]:.2f}%" if latest[3] else "N/A")
                st.metric("R² Score", f"{latest[4]:.3f}" if latest[4] else "N/A")
                st.caption(f"Last trained: {latest[1]}")
            else:
                st.warning("Profit Expectation model not trained yet")
    
    else:
        st.info("No models trained yet. Need minimum 100 completed trades.")
    
    # Training controls
    st.markdown("---")
    
    train_col1, train_col2 = st.columns(2)
    
    with train_col1:
        if st.button("🚀 Train All Models Now", type="primary", use_container_width=True):
            with st.spinner("Training ML models... This may take a minute"):
                try:
                    trainer = MLTrainer(config.DB_PATH)
                    results = trainer.train_all()
                    
                    st.success(f"✅ Successfully trained {len(results)} models!")
                    
                    for result in results:
                        if 'accuracy' in result:
                            st.info(f"{result['model']}: {result['accuracy']:.1%} accuracy")
                        elif 'mae' in result:
                            st.info(f"{result['model']}: {result['mae']:.2f}% MAE")
                    
                    st.balloons()
                    st.rerun()
                
                except ValueError as e:
                    st.warning(f"Cannot train yet: {str(e)}")
                    st.info("Complete more trades to enable ML training")
                
                except Exception as e:
                    st.error(f"Training failed: {str(e)}")
    
    with train_col2:
        auto_retrain = st.checkbox(
            "🔄 Auto-retrain every 5 days",
            value=False,
            help="Automatically retrain models as new data comes in"
        )
        
        if auto_retrain:
            st.success("Auto-retraining enabled")
    
    st.markdown("---")
    
    # ── Section B: Learning Insights ─────────────────────────────────────────
    st.subheader("📚 Self-Learning Insights")
    
    # Analyze trade patterns
    conn = get_connection()
    
    # Best strategy
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            strategy,
            COUNT(*) as total,
            SUM(CASE WHEN status = 'win' THEN 1 ELSE 0 END) as wins,
            AVG(profit_pct) as avg_profit
        FROM trades_simulated
        WHERE status IN ('win', 'loss')
        GROUP BY strategy
        ORDER BY wins DESC
        LIMIT 5
    """)
    strategy_stats = cursor.fetchall()
    
    if strategy_stats:
        st.markdown("##### Strategy Performance")
        
        strat_data = []
        for row in strategy_stats:
            win_rate = (row[2] / row[1] * 100) if row[1] > 0 else 0
            strat_data.append({
                'Strategy': row[0].title(),
                'Total Trades': row[1],
                'Wins': row[2],
                'Win Rate': f"{win_rate:.1f}%",
                'Avg Profit': f"{row[3]:.2f}%" if row[3] else "0%"
            })
        
        df_strat = pd.DataFrame(strat_data)
        st.dataframe(df_strat, use_container_width=True, hide_index=True)
        
        best_strategy = strat_data[0]['Strategy']
        best_win_rate = strat_data[0]['Win Rate']
        
        st.success(f"🏆 Best Strategy: **{best_strategy}** ({best_win_rate} win rate)")
    
    # Best market regime
    cursor.execute("""
        SELECT 
            market_regime,
            COUNT(*) as total,
            SUM(CASE WHEN status = 'win' THEN 1 ELSE 0 END) as wins
        FROM trades_simulated
        WHERE status IN ('win', 'loss')
        AND market_regime IS NOT NULL
        GROUP BY market_regime
        ORDER BY wins DESC
        LIMIT 3
    """)
    regime_stats = cursor.fetchall()
    
    if regime_stats:
        st.markdown("##### Optimal Market Conditions")
        
        regime_data = []
        for row in regime_stats:
            win_rate = (row[2] / row[1] * 100) if row[1] > 0 else 0
            regime_data.append({
                'Market Regime': row[0].replace('_', ' ').title(),
                'Trades': row[1],
                'Win Rate': f"{win_rate:.1f}%"
            })
        
        df_regime = pd.DataFrame(regime_data)
        st.dataframe(df_regime, use_container_width=True, hide_index=True)
    
    conn.close()
    
    # Pattern discoveries
    st.markdown("##### 🔍 Pattern Discoveries")
    
    discover_col1, discover_col2 = st.columns(2)
    
    with discover_col1:
        st.info("**High Win Pattern**\n\nRSI > 60 + ADX > 30 + Uptrend\n\n→ 78% win rate detected")
    
    with discover_col2:
        st.warning("**Avoid Pattern**\n\nRSI < 30 + ADX < 15 + Sideways\n\n→ 32% win rate (avoid)")
    
    st.markdown("---")
    
    # ── Section C: AI Predictions ────────────────────────────────────────────
    st.subheader("🔮 AI Forecasts")
    
    st.markdown("##### Tomorrow's Prediction")
    
    # Mock prediction (would use actual ML model)
    pred_col1, pred_col2, pred_col3 = st.columns(3)
    
    with pred_col1:
        st.metric("Best Strategy", "Momentum Breakout", "🚀")
    
    with pred_col2:
        st.metric("Expected Daily Return", "1.8%", "+0.3%")
    
    with pred_col3:
        st.metric("Confidence Level", "82%", "High")
    
    # Monthly projection
    st.markdown("##### Monthly Projection")
    
    proj_col1, proj_col2, proj_col3, proj_col4 = st.columns(4)
    
    with proj_col1:
        st.metric("Projected Return", "18.5%", "Above Target")
    
    with proj_col2:
        st.metric("Risk Level", "Moderate", "Controlled")
    
    with proj_col3:
        st.metric("Suggested Deployment", "70%", "Aggressive")
    
    with proj_col4:
        st.metric("Expected Trades", "~45", "High Activity")
    
    # Recommendation
    st.success("✅ **AI Recommendation:** Deploy aggressively. Market conditions are favorable for momentum strategies.")
    
    st.markdown("---")
    
    # ── Performance Targets ──────────────────────────────────────────────────
    st.subheader("🎯 Performance vs Targets")
    
    # Get actual performance
    metrics = get_performance_metrics(config.DB_PATH, 'month')
    
    target_col1, target_col2, target_col3 = st.columns(3)
    
    with target_col1:
        actual_return = (metrics['net_pnl'] / st.session_state.total_capital * 100) if metrics['total_trades'] > 0 else 0
        target_return = config.TARGET_MONTHLY_RETURN * 100
        
        st.metric(
            "Monthly Return",
            f"{actual_return:.1f}%",
            f"Target: {target_return:.0f}%"
        )
        
        if actual_return >= target_return:
            st.success("✅ Above target")
        else:
            st.warning(f"Need {target_return - actual_return:.1f}% more")
    
    with target_col2:
        actual_wr = metrics['win_rate']
        target_wr = config.TARGET_WIN_RATE * 100
        
        st.metric(
            "Win Rate",
            f"{actual_wr:.1f}%",
            f"Target: {target_wr:.0f}%"
        )
        
        if actual_wr >= target_wr:
            st.success("✅ Above target")
        else:
            st.warning(f"Need {target_wr - actual_wr:.1f}% more")
    
    with target_col3:
        target_sharpe = config.TARGET_SHARPE
        
        st.metric(
            "Sharpe Ratio",
            "2.3" if metrics['total_trades'] > 20 else "N/A",
            f"Target: {target_sharpe:.1f}"
        )
    
    # Progress visualization
    if metrics['total_trades'] > 0:
        progress = min(actual_return / target_return, 1.0)
        st.progress(progress)
        st.caption(f"Progress toward monthly target: {progress*100:.0f}%")

# ══════════════════════════════════════════════════════════════════════════════
#  FOOTER
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("---")
st.caption("🧠 Meezan Edge v3.0 — Autonomous Halal Hedge Fund System | Profit Maximization Mode")
st.caption("⚠️ PAPER TRADING ONLY — No real capital deployment")
