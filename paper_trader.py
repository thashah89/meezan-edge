"""
engines/paper_trader.py — Paper Trading Execution Engine

Simulates live trade execution using real Zerodha prices.
NO REAL ORDERS ARE PLACED. Pure simulation for learning and testing.

Tracks:
- Entry execution
- Stop-loss hits
- Target hits
- Position P&L
- Exit management
"""

import sqlite3
import logging
from datetime import datetime, date
from typing import Dict, List, Optional
import pandas as pd

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  PAPER TRADING ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class PaperTradingEngine:
    """
    Simulates trade execution and manages paper positions.
    
    Uses live prices from Zerodha for realistic simulation.
    Applies slippage and brokerage costs.
    """
    
    def __init__(self, db_path: str, config: Dict = None):
        self.db_path = db_path
        self.config = config or {}
        
        # Simulation parameters
        self.slippage_pct = self.config.get('slippage_pct', 0.001)  # 0.1%
        self.brokerage_per_trade = self.config.get('brokerage', 20)  # ₹20 per trade
        
    def enter_trade(self, trade: Dict, current_price: float = None) -> int:
        """
        Simulate trade entry.
        
        Args:
            trade: Trade dict from TradeSelector
            current_price: Current market price (if different from trade['entry'])
        
        Returns:
            trade_id: Database ID of created trade
        """
        entry_price = current_price or trade['entry']
        
        # Apply slippage (unfavorable)
        entry_price_actual = entry_price * (1 + self.slippage_pct)
        
        # Recalculate levels with actual entry
        sl = trade['stop_loss']
        risk_actual = entry_price_actual - sl
        target_actual = entry_price_actual + (risk_actual * trade['rr_ratio'])
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO trades_simulated (
                    symbol, entry_date, entry_time, entry_price,
                    quantity, stop_loss, target,
                    mode, strategy, status,
                    risk_amount, reward_amount, rr_ratio, capital_used,
                    ml_win_prob, ml_expected_return,
                    entry_rsi, entry_adx, entry_trend_score,
                    market_regime
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade['symbol'],
                date.today(),
                datetime.now().time(),
                entry_price_actual,
                trade['quantity'],
                sl,
                target_actual,
                trade['mode'],
                trade['strategy'],
                'open',
                trade['total_risk'],
                trade['potential_profit'],
                trade['rr_ratio'],
                trade['position_value'],
                trade.get('win_probability'),
                trade.get('expected_return'),
                trade.get('entry_rsi'),
                trade.get('entry_adx'),
                trade.get('entry_trend_score'),
                trade.get('market_regime', 'unknown')
            ))
            
            trade_id = cursor.lastrowid
            conn.commit()
            
            log.info(f"📊 Entered {trade['mode']} trade: {trade['symbol']} × {trade['quantity']} "
                    f"@ ₹{entry_price_actual:.2f} (ID: {trade_id})")
            
            return trade_id
            
        except Exception as e:
            log.error(f"Failed to enter trade: {e}")
            conn.rollback()
            return -1
        finally:
            conn.close()
    
    def update_positions(self, live_prices: Dict[str, float]) -> Dict:
        """
        Update all open positions with current prices.
        Check for SL/target hits.
        
        Args:
            live_prices: {symbol: current_price}
        
        Returns:
            Summary dict with exits and P&L
        """
        open_trades = self._get_open_trades()
        
        exits = {
            'sl_hits': [],
            'target_hits': [],
            'intraday_closes': []
        }
        
        for trade in open_trades:
            symbol = trade['symbol']
            current_price = live_prices.get(symbol)
            
            if current_price is None:
                continue
            
            trade_id = trade['id']
            entry = trade['entry_price']
            sl = trade['stop_loss']
            target = trade['target']
            mode = trade['mode']
            
            # ── Check Stop Loss ───────────────────────────────────────────────
            if current_price <= sl:
                self.exit_trade(
                    trade_id=trade_id,
                    exit_price=sl,
                    exit_reason='stop_loss'
                )
                exits['sl_hits'].append(symbol)
                continue
            
            # ── Check Target ──────────────────────────────────────────────────
            if current_price >= target:
                self.exit_trade(
                    trade_id=trade_id,
                    exit_price=target,
                    exit_reason='target'
                )
                exits['target_hits'].append(symbol)
                continue
            
            # ── Intraday: Auto-square off at 3:20 PM ─────────────────────────
            if mode == 'intraday' and datetime.now().hour >= 15 and datetime.now().minute >= 20:
                self.exit_trade(
                    trade_id=trade_id,
                    exit_price=current_price,
                    exit_reason='intraday_close'
                )
                exits['intraday_closes'].append(symbol)
        
        return exits
    
    def exit_trade(self, trade_id: int, exit_price: float, exit_reason: str):
        """
        Close a trade.
        
        Args:
            trade_id: Database ID
            exit_price: Exit price
            exit_reason: 'stop_loss' | 'target' | 'manual' | 'intraday_close'
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Get trade details
            cursor.execute("SELECT * FROM trades_simulated WHERE id = ?", (trade_id,))
            row = cursor.fetchone()
            
            if not row:
                log.warning(f"Trade ID {trade_id} not found")
                return
            
            trade = dict(zip([d[0] for d in cursor.description], row))
            
            # Apply slippage (unfavorable)
            exit_price_actual = exit_price * (1 - self.slippage_pct) if exit_reason == 'target' \
                              else exit_price * (1 + self.slippage_pct)
            
            # Calculate P&L
            entry = trade['entry_price']
            quantity = trade['quantity']
            
            profit_loss = (exit_price_actual - entry) * quantity
            profit_loss -= (2 * self.brokerage_per_trade)  # Entry + Exit brokerage
            
            profit_pct = (profit_loss / (entry * quantity)) * 100
            
            # Determine status
            if profit_loss > 10:
                status = 'win'
            elif profit_loss < -10:
                status = 'loss'
            else:
                status = 'breakeven'
            
            # Update database
            cursor.execute("""
                UPDATE trades_simulated
                SET exit_date = ?,
                    exit_time = ?,
                    exit_price = ?,
                    exit_reason = ?,
                    profit_loss = ?,
                    profit_pct = ?,
                    status = ?,
                    closed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                date.today(),
                datetime.now().time(),
                exit_price_actual,
                exit_reason,
                profit_loss,
                profit_pct,
                status,
                trade_id
            ))
            
            conn.commit()
            
            emoji = "🎯" if status == 'win' else "🛑" if status == 'loss' else "⚖️"
            log.info(f"{emoji} Exited {trade['symbol']}: "
                    f"₹{profit_loss:,.0f} ({profit_pct:+.2f}%) via {exit_reason}")
            
        except Exception as e:
            log.error(f"Failed to exit trade {trade_id}: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    def close_all_intraday(self, live_prices: Dict[str, float]):
        """
        Force-close all intraday positions (call at 3:20 PM).
        """
        open_trades = self._get_open_trades()
        
        for trade in open_trades:
            if trade['mode'] == 'intraday':
                price = live_prices.get(trade['symbol'], trade['entry_price'])
                self.exit_trade(trade['id'], price, 'intraday_close')
    
    def _get_open_trades(self) -> List[Dict]:
        """Get all currently open trades."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            # Backward-compatible query for legacy schemas.
            cursor.execute("PRAGMA table_info(trades_simulated)")
            cols = {row["name"] for row in cursor.fetchall()}
            if not cols:
                conn.close()
                return []

            where_clause = "WHERE status = 'open'" if "status" in cols else ""
            order_parts = []
            if "entry_date" in cols:
                order_parts.append("entry_date DESC")
            if "entry_time" in cols:
                order_parts.append("entry_time DESC")

            order_clause = f"ORDER BY {', '.join(order_parts)}" if order_parts else ""
            sql = f"SELECT * FROM trades_simulated {where_clause} {order_clause}"
            cursor.execute(sql)
            trades = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return trades
        except sqlite3.OperationalError:
            conn.close()
            return []
    
    def get_position_summary(self) -> Dict:
        """
        Get current position summary.
        
        Returns:
            {
                'total_positions': int,
                'intraday': int,
                'swing': int,
                'capital_deployed': float,
                'unrealized_pnl': float,
                'positions': List[Dict]
            }
        """
        open_trades = self._get_open_trades()
        
        intraday_count = sum(1 for t in open_trades if t.get('mode') == 'intraday')
        swing_count = sum(1 for t in open_trades if t.get('mode') == 'swing')
        capital_deployed = sum(float(t.get('capital_used') or 0.0) for t in open_trades)
        
        return {
            'total_positions': len(open_trades),
            'intraday': intraday_count,
            'swing': swing_count,
            'capital_deployed': capital_deployed,
            'positions': open_trades
        }
    
    def calculate_portfolio_pnl(self, live_prices: Dict[str, float]) -> Dict:
        """
        Calculate current portfolio P&L (realized + unrealized).
        
        Returns:
            {
                'realized_pnl': float,
                'unrealized_pnl': float,
                'total_pnl': float,
                'today_pnl': float
            }
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Realized P&L (closed trades)
        cursor.execute("""
            SELECT COALESCE(SUM(profit_loss), 0) as realized_pnl
            FROM trades_simulated
            WHERE status IN ('win', 'loss', 'breakeven')
        """)
        realized_pnl = cursor.fetchone()['realized_pnl']
        
        # Today's realized P&L
        cursor.execute("""
            SELECT COALESCE(SUM(profit_loss), 0) as today_pnl
            FROM trades_simulated
            WHERE status IN ('win', 'loss', 'breakeven')
            AND exit_date = date('now')
        """)
        today_pnl = cursor.fetchone()['today_pnl']
        
        conn.close()
        
        # Unrealized P&L (open positions)
        open_trades = self._get_open_trades()
        unrealized_pnl = 0
        
        for trade in open_trades:
            symbol = trade['symbol']
            current_price = live_prices.get(symbol, trade['entry_price'])
            
            pnl = (current_price - trade['entry_price']) * trade['quantity']
            unrealized_pnl += pnl
        
        return {
            'realized_pnl': realized_pnl,
            'unrealized_pnl': unrealized_pnl,
            'total_pnl': realized_pnl + unrealized_pnl,
            'today_pnl': today_pnl
        }


# ══════════════════════════════════════════════════════════════════════════════
#  PERFORMANCE TRACKER
# ══════════════════════════════════════════════════════════════════════════════

def get_performance_metrics(db_path: str, period: str = 'all') -> Dict:
    """
    Calculate performance metrics.
    
    Args:
        db_path: Database path
        period: 'today' | 'week' | 'month' | 'all'
    
    Returns:
        Comprehensive performance dict
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Backward-compatible column detection for legacy DBs.
    cursor.execute("PRAGMA table_info(trades_simulated)")
    existing_cols = {row["name"] for row in cursor.fetchall()}

    if "status" not in existing_cols:
        conn.close()
        return {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0.0,
            'avg_win_pct': 0.0,
            'avg_loss_pct': 0.0,
            'avg_win_loss_ratio': 0.0,
            'net_pnl': 0.0,
            'profit_factor': 0.0,
            'best_trade_pct': 0.0,
            'worst_trade_pct': 0.0,
        }

    date_col = "exit_date" if "exit_date" in existing_cols else "entry_date" if "entry_date" in existing_cols else None
    if period == 'today':
        date_filter = f"{date_col} = date('now')" if date_col else "1=1"
    elif period == 'week':
        date_filter = f"{date_col} >= date('now', '-7 days')" if date_col else "1=1"
    elif period == 'month':
        date_filter = f"{date_col} >= date('now', '-30 days')" if date_col else "1=1"
    else:
        date_filter = "1=1"

    profit_pct_expr = "profit_pct" if "profit_pct" in existing_cols else "0"
    profit_loss_expr = "profit_loss" if "profit_loss" in existing_cols else "0"

    cursor.execute(f"""
        SELECT
            COUNT(*) as total_trades,
            SUM(CASE WHEN status = 'win' THEN 1 ELSE 0 END) as winning_trades,
            SUM(CASE WHEN status = 'loss' THEN 1 ELSE 0 END) as losing_trades,
            AVG(CASE WHEN status = 'win' THEN {profit_pct_expr} ELSE NULL END) as avg_win_pct,
            AVG(CASE WHEN status = 'loss' THEN {profit_pct_expr} ELSE NULL END) as avg_loss_pct,
            SUM(CASE WHEN status = 'win' THEN {profit_loss_expr} ELSE 0 END) as total_wins_amt,
            SUM(CASE WHEN status = 'loss' THEN {profit_loss_expr} ELSE 0 END) as total_loss_amt,
            SUM({profit_loss_expr}) as net_pnl,
            MAX({profit_pct_expr}) as best_trade_pct,
            MIN({profit_pct_expr}) as worst_trade_pct
        FROM trades_simulated
        WHERE {date_filter}
        AND status IN ('win', 'loss', 'breakeven')
    """)
    
    row = cursor.fetchone()
    conn.close()
    
    total_trades = row['total_trades'] or 0
    winning_trades = row['winning_trades'] or 0
    losing_trades = row['losing_trades'] or 0
    
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    
    avg_win = row['avg_win_pct'] or 0
    avg_loss = abs(row['avg_loss_pct'] or 0)
    
    avg_win_loss_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0
    
    total_wins_amt = row['total_wins_amt'] or 0
    total_loss_amt = abs(row['total_loss_amt'] or 0)
    
    profit_factor = (total_wins_amt / total_loss_amt) if total_loss_amt > 0 else 0
    
    return {
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'win_rate': round(win_rate, 1),
        'avg_win_pct': round(avg_win, 2),
        'avg_loss_pct': round(avg_loss, 2),
        'avg_win_loss_ratio': round(avg_win_loss_ratio, 2),
        'net_pnl': round(row['net_pnl'] or 0, 2),
        'profit_factor': round(profit_factor, 2),
        'best_trade_pct': round(row['best_trade_pct'] or 0, 2),
        'worst_trade_pct': round(row['worst_trade_pct'] or 0, 2),
    }


if __name__ == "__main__":
    # Test paper trading engine
    logging.basicConfig(level=logging.INFO)
    
    # Mock database
    import tempfile
    db_path = tempfile.mktemp(suffix='.db')
    
    # Initialize schema
    from database_schema import init_database
    import shutil
    shutil.copy('meezan_v3.db', db_path)
    
    engine = PaperTradingEngine(db_path)
    
    # Mock trade
    mock_trade = {
        'symbol': 'TCS',
        'entry': 3500,
        'stop_loss': 3422,
        'target': 3656,
        'quantity': 10,
        'position_value': 35000,
        'total_risk': 780,
        'potential_profit': 1560,
        'rr_ratio': 2.0,
        'mode': 'swing',
        'strategy': 'momentum',
        'win_probability': 0.72,
        'expected_return': 2.5,
        'entry_rsi': 62,
        'entry_adx': 32,
        'entry_trend_score': 85
    }
    
    # Enter trade
    trade_id = engine.enter_trade(mock_trade)
    print(f"\nEntered trade ID: {trade_id}")
    
    # Check position summary
    summary = engine.get_position_summary()
    print(f"\nOpen positions: {summary['total_positions']}")
    print(f"Capital deployed: ₹{summary['capital_deployed']:,.0f}")
    
    # Simulate target hit
    live_prices = {'TCS': 3656}
    exits = engine.update_positions(live_prices)
    print(f"\nTarget hits: {exits['target_hits']}")
    
    # Get metrics
    metrics = get_performance_metrics(db_path, 'all')
    print(f"\nPerformance:")
    for k, v in metrics.items():
        print(f"  {k}: {v}")
