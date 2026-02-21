"""
database/schema.py — SQLite database schema for Meezan Edge v3.0

Production-ready schema with migrations support.
SQLite for development, PostgreSQL-compatible for scaling.
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
import logging

log = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent / "meezan_v3.db"

# ══════════════════════════════════════════════════════════════════════════════
#  SCHEMA DEFINITIONS
# ══════════════════════════════════════════════════════════════════════════════

SCHEMA_VERSION = 1

TABLES = {
    "stocks_master": """
        CREATE TABLE IF NOT EXISTS stocks_master (
            symbol TEXT PRIMARY KEY,
            company TEXT NOT NULL,
            sector TEXT,
            exchange TEXT DEFAULT 'NSE',
            load_date DATE NOT NULL,
            valid_till DATE NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """,
    
    "stock_metrics": """
        CREATE TABLE IF NOT EXISTS stock_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            date DATE NOT NULL,
            -- OHLCV
            ltp REAL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            -- Technical Indicators
            rsi REAL,
            adx REAL,
            macd REAL,
            macd_signal REAL,
            sma_20 REAL,
            sma_50 REAL,
            sma_200 REAL,
            ema_9 REAL,
            ema_21 REAL,
            atr REAL,
            bb_upper REAL,
            bb_middle REAL,
            bb_lower REAL,
            bb_width REAL,
            -- Derived Metrics
            trend_score INTEGER,           -- 0-100
            momentum_score INTEGER,        -- 0-100
            volatility_score INTEGER,      -- 0-100
            liquidity_score INTEGER,       -- 0-100
            opportunity_score INTEGER,     -- 0-100
            volume_ratio REAL,
            -- ML Predictions
            win_probability REAL,
            expected_return REAL,
            strategy_fit TEXT,
            confidence REAL,
            -- Metadata
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (symbol) REFERENCES stocks_master(symbol),
            UNIQUE(symbol, date)
        )
    """,
    
    "market_sentiment": """
        CREATE TABLE IF NOT EXISTS market_sentiment (
            date DATE PRIMARY KEY,
            sentiment TEXT,               -- bullish, bearish, sideways, high_vol, breakout
            volatility TEXT,              -- low, moderate, high
            confidence REAL,              -- 0-100
            nifty_trend TEXT,
            market_breadth REAL,
            sector_strength TEXT,
            recommended_style TEXT,
            deployment_pct REAL,
            intraday_pct REAL,
            swing_pct REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """,
    
    "trades_simulated": """
        CREATE TABLE IF NOT EXISTS trades_simulated (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            entry_date DATE NOT NULL,
            entry_time TIME,
            entry_price REAL NOT NULL,
            quantity INTEGER NOT NULL,
            stop_loss REAL NOT NULL,
            target REAL NOT NULL,
            exit_date DATE,
            exit_time TIME,
            exit_price REAL,
            exit_reason TEXT,
            -- Trade Classification
            mode TEXT,                    -- intraday, swing
            strategy TEXT,
            -- Results
            profit_loss REAL,
            profit_pct REAL,
            status TEXT,                  -- open, win, loss, breakeven
            -- Risk Metrics
            risk_amount REAL,
            reward_amount REAL,
            rr_ratio REAL,
            capital_used REAL,
            -- ML Features (at entry)
            ml_win_prob REAL,
            ml_expected_return REAL,
            entry_rsi REAL,
            entry_adx REAL,
            entry_trend_score INTEGER,
            market_regime TEXT,
            -- Metadata
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            closed_at TIMESTAMP,
            FOREIGN KEY (symbol) REFERENCES stocks_master(symbol)
        )
    """,
    
    "portfolio_daily": """
        CREATE TABLE IF NOT EXISTS portfolio_daily (
            date DATE PRIMARY KEY,
            total_capital REAL NOT NULL,
            deployed_capital REAL,
            available_capital REAL,
            -- Daily Performance
            daily_pnl REAL,
            daily_pnl_pct REAL,
            daily_trades INTEGER,
            daily_wins INTEGER,
            daily_losses INTEGER,
            -- Cumulative Performance
            monthly_pnl REAL,
            monthly_pnl_pct REAL,
            ytd_pnl REAL,
            ytd_pnl_pct REAL,
            -- Trade Metrics
            total_trades INTEGER,
            winning_trades INTEGER,
            losing_trades INTEGER,
            win_rate REAL,
            avg_win REAL,
            avg_loss REAL,
            avg_win_loss_ratio REAL,
            -- Risk Metrics
            max_drawdown REAL,
            current_drawdown REAL,
            sharpe_ratio REAL,
            profit_factor REAL,
            -- Allocation
            intraday_capital REAL,
            swing_capital REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """,
    
    "strategy_performance": """
        CREATE TABLE IF NOT EXISTS strategy_performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name TEXT NOT NULL,
            period_start DATE NOT NULL,
            period_end DATE NOT NULL,
            total_trades INTEGER,
            winning_trades INTEGER,
            losing_trades INTEGER,
            win_rate REAL,
            avg_return REAL,
            total_return REAL,
            max_drawdown REAL,
            sharpe_ratio REAL,
            profit_factor REAL,
            best_market_regime TEXT,
            worst_market_regime TEXT,
            avg_holding_period REAL,
            is_active BOOLEAN DEFAULT 1,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(strategy_name, period_start)
        )
    """,
    
    "ai_model_logs": """
        CREATE TABLE IF NOT EXISTS ai_model_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_name TEXT NOT NULL,
            model_type TEXT,              -- classifier, regressor
            training_date DATE NOT NULL,
            accuracy REAL,
            precision_score REAL,
            recall REAL,
            f1_score REAL,
            mae REAL,
            rmse REAL,
            r2_score REAL,
            dataset_size INTEGER,
            train_samples INTEGER,
            test_samples INTEGER,
            features_used TEXT,
            hyperparameters TEXT,
            model_path TEXT,
            performance_notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """,

    "pattern_signals": """
        CREATE TABLE IF NOT EXISTS pattern_signals (
            pattern_key TEXT PRIMARY KEY,
            trades INTEGER,
            wins INTEGER,
            win_rate REAL,
            avg_return REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """,
    
    "schema_version": """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
}

# Indexes for performance
INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_stock_metrics_symbol_date ON stock_metrics(symbol, date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades_simulated(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_trades_status ON trades_simulated(status)",
    "CREATE INDEX IF NOT EXISTS idx_trades_entry_date ON trades_simulated(entry_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_portfolio_date ON portfolio_daily(date DESC)",
]


# ══════════════════════════════════════════════════════════════════════════════
#  DATABASE CONNECTION & INITIALIZATION
# ══════════════════════════════════════════════════════════════════════════════

def get_connection():
    """Get database connection with foreign key support enabled."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row  # Access columns by name
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_database():
    """Initialize database with all tables and indexes."""
    log.info(f"Initializing database at {DB_PATH}")
    
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Create all tables
        for table_name, schema in TABLES.items():
            cursor.execute(schema)
            log.debug(f"Created/verified table: {table_name}")
        
        # Create indexes
        for index in INDEXES:
            cursor.execute(index)

        # Lightweight migrations for older DB files
        _run_compat_migrations(cursor)
        
        # Record schema version
        cursor.execute(
            "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,)
        )
        
        conn.commit()
        log.info("Database initialization complete")
        return True
        
    except Exception as e:
        log.error(f"Database initialization failed: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def _table_columns(cursor, table_name: str) -> set[str]:
    """Return existing column names for a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}


def _ensure_columns(cursor, table_name: str, columns: dict[str, str]):
    """Add missing columns via ALTER TABLE for backward compatibility."""
    existing = _table_columns(cursor, table_name)
    for col, col_def in columns.items():
        if col not in existing:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col} {col_def}")


def _run_compat_migrations(cursor):
    """
    Ensure older databases contain columns required by current app code.
    This avoids runtime OperationalError when an old DB file is deployed.
    """
    _ensure_columns(cursor, "stocks_master", {
        "sector": "TEXT",
        "exchange": "TEXT DEFAULT 'NSE'",
        "load_date": "DATE",
        "valid_till": "DATE",
        "is_active": "BOOLEAN DEFAULT 1",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    })

    _ensure_columns(cursor, "stock_metrics", {
        "open": "REAL",
        "high": "REAL",
        "low": "REAL",
        "close": "REAL",
        "volume": "INTEGER",
        "macd_signal": "REAL",
        "sma_20": "REAL",
        "sma_50": "REAL",
        "sma_200": "REAL",
        "ema_9": "REAL",
        "ema_21": "REAL",
        "bb_upper": "REAL",
        "bb_middle": "REAL",
        "bb_lower": "REAL",
        "bb_width": "REAL",
        "momentum_score": "INTEGER",
        "volatility_score": "INTEGER",
        "liquidity_score": "INTEGER",
        "volume_ratio": "REAL",
        "win_probability": "REAL",
        "expected_return": "REAL",
        "strategy_fit": "TEXT",
        "confidence": "REAL",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    })

    _ensure_columns(cursor, "trades_simulated", {
        "entry_time": "TIME",
        "exit_date": "DATE",
        "exit_time": "TIME",
        "exit_price": "REAL",
        "exit_reason": "TEXT",
        "mode": "TEXT",
        "strategy": "TEXT",
        "profit_loss": "REAL",
        "profit_pct": "REAL",
        "risk_amount": "REAL",
        "reward_amount": "REAL",
        "rr_ratio": "REAL",
        "capital_used": "REAL",
        "ml_win_prob": "REAL",
        "ml_expected_return": "REAL",
        "entry_rsi": "REAL",
        "entry_adx": "REAL",
        "entry_trend_score": "INTEGER",
        "market_regime": "TEXT",
        "closed_at": "TIMESTAMP",
    })

    # Ensure pattern_signals exists for backend pattern learning.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pattern_signals (
            pattern_key TEXT PRIMARY KEY,
            trades INTEGER,
            wins INTEGER,
            win_rate REAL,
            avg_return REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def reset_database():
    """⚠️ DESTRUCTIVE: Drop all tables and reinitialize. Use with caution."""
    log.warning("Resetting database — all data will be lost")
    
    if DB_PATH.exists():
        DB_PATH.unlink()
    
    return init_database()


# ══════════════════════════════════════════════════════════════════════════════
#  MIGRATION UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def migrate_from_v1_cache(cache_json_path: str):
    """
    Migrate data from v1.5 halal_stocks_cache.json to v3.0 database.
    
    Args:
        cache_json_path: Path to the JSON cache file
    """
    import json
    from datetime import date, timedelta
    
    log.info(f"Migrating v1.5 cache from {cache_json_path}")
    
    with open(cache_json_path) as f:
        cache = json.load(f)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Migrate halal stocks to stocks_master
        halal_stocks = cache.get("halal_stocks", [])
        load_date = date.today()
        valid_till = load_date + timedelta(days=15)
        
        for stock in halal_stocks:
            cursor.execute("""
                INSERT OR REPLACE INTO stocks_master 
                (symbol, company, sector, load_date, valid_till)
                VALUES (?, ?, ?, ?, ?)
            """, (
                stock.get("nse_ticker", "").replace(".NS", ""),
                stock.get("company", ""),
                stock.get("industry", ""),
                load_date,
                valid_till
            ))
        
        log.info(f"Migrated {len(halal_stocks)} stocks")
        
        # Migrate trend_list to initial stock_metrics (today's snapshot)
        trend_list = cache.get("trend_list", [])
        today = date.today()
        
        for trend in trend_list:
            cursor.execute("""
                INSERT OR REPLACE INTO stock_metrics
                (symbol, date, ltp, rsi, adx, trend_score, 
                 opportunity_score, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                trend.get("ticker"),
                today,
                trend.get("current_price"),
                trend.get("rsi"),
                trend.get("adx"),
                trend.get("trend_score", 0) * 10,  # scale 0-9 to 0-90
                0,  # will be calculated later
            ))
        
        log.info(f"Migrated {len(trend_list)} stock metrics")
        
        conn.commit()
        log.info("Migration from v1.5 complete")
        return True
        
    except Exception as e:
        log.error(f"Migration failed: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_db_stats():
    """Return database statistics for monitoring."""
    conn = get_connection()
    cursor = conn.cursor()
    
    stats = {}
    
    for table_name in TABLES.keys():
        if table_name == "schema_version":
            continue
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        stats[table_name] = cursor.fetchone()[0]
    
    conn.close()
    return stats


# ══════════════════════════════════════════════════════════════════════════════
#  UTILITY QUERIES
# ══════════════════════════════════════════════════════════════════════════════

def get_active_stocks():
    """Get all active stocks in the universe."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT symbol, company, sector, load_date, valid_till
        FROM stocks_master
        WHERE is_active = 1
        ORDER BY symbol
    """)
    results = cursor.fetchall()
    conn.close()
    return [dict(row) for row in results]


def get_latest_metrics(symbol: str = None):
    """Get latest metrics for a stock or all stocks."""
    conn = get_connection()
    cursor = conn.cursor()
    
    if symbol:
        cursor.execute("""
            SELECT * FROM stock_metrics
            WHERE symbol = ?
            ORDER BY date DESC
            LIMIT 1
        """, (symbol,))
    else:
        cursor.execute("""
            SELECT m.* FROM stock_metrics m
            INNER JOIN (
                SELECT symbol, MAX(date) as max_date
                FROM stock_metrics
                GROUP BY symbol
            ) latest ON m.symbol = latest.symbol AND m.date = latest.max_date
            ORDER BY m.opportunity_score DESC
        """)
    
    results = cursor.fetchall()
    conn.close()
    return [dict(row) for row in results]


def get_open_trades():
    """Get all currently open trades."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM trades_simulated
        WHERE status = 'open'
        ORDER BY entry_date DESC
    """)
    results = cursor.fetchall()
    conn.close()
    return [dict(row) for row in results]


def get_portfolio_summary():
    """Get latest portfolio summary."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM portfolio_daily
        ORDER BY date DESC
        LIMIT 1
    """)
    result = cursor.fetchone()
    conn.close()
    return dict(result) if result else None


if __name__ == "__main__":
    # Initialize database when run directly
    logging.basicConfig(level=logging.INFO)
    init_database()
    print("Database initialized successfully")
    print("\nDatabase stats:")
    for table, count in get_db_stats().items():
        print(f"  {table}: {count} rows")
