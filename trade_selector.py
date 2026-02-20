"""
engines/trade_selector.py — Autonomous Trade Selection Engine

Evaluates all opportunities and selects the best trades to execute.
Calculates precise entry/SL/target levels with strict 2:1 R:R enforcement.

This is the "Portfolio Manager" making the final trade decisions.
"""

import logging
from typing import Dict, List, Tuple
from datetime import datetime

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  TRADE SELECTOR
# ══════════════════════════════════════════════════════════════════════════════

class TradeSelector:
    """
    Selects best trades from ranked opportunities.
    
    Philosophy: "Would I take this trade if it was my own money?"
    
    Strict filters:
    - Win probability ≥ 55%
    - R:R ratio ≥ 2.0
    - Liquidity score ≥ 60
    - Opportunity score ≥ 70
    """
    
    def __init__(self, config: Dict = None):
        self.config = config or {}
        
        # Selection thresholds
        self.min_win_prob = self.config.get('min_win_prob', 0.55)
        self.min_rr_ratio = self.config.get('min_rr_ratio', 2.0)
        self.min_liquidity = self.config.get('min_liquidity', 60)
        self.min_opp_score = self.config.get('min_opp_score', 70)
        
        # Risk parameters
        self.atr_multiplier = self.config.get('atr_multiplier', 1.5)
        self.rr_ratio = self.config.get('rr_ratio', 2.0)
    
    def select_trades(self,
                     opportunities: List[Dict],
                     allocation: Dict,
                     market_sentiment: Dict,
                     max_trades: int = None) -> List[Dict]:
        """
        Select best trades from opportunity list.
        
        Args:
            opportunities: Ranked list from Market Intelligence Engine
            allocation: Capital allocation plan
            market_sentiment: Current market regime
            max_trades: Maximum trades to select (from allocation.trades_to_take)
        
        Returns:
            List of selected trades with entry/SL/target levels
        """
        if max_trades is None:
            max_trades = allocation.get('trades_to_take', 10)
        
        selected_trades = []
        intraday_capital_used = 0
        swing_capital_used = 0
        
        intraday_capital = allocation.get('intraday_capital', 0)
        swing_capital = allocation.get('swing_capital', 0)
        
        for opp in opportunities:
            if len(selected_trades) >= max_trades:
                break
            
            # ── Filter 1: Quality thresholds ─────────────────────────────────
            if not self._meets_quality_standards(opp):
                continue
            
            # ── Determine trade mode ─────────────────────────────────────────
            mode = self._determine_trade_mode(opp, market_sentiment)
            
            # ── Check capital availability ───────────────────────────────────
            if mode == 'intraday' and intraday_capital_used >= intraday_capital:
                continue
            if mode == 'swing' and swing_capital_used >= swing_capital:
                continue
            
            # ── Calculate trade levels ───────────────────────────────────────
            trade = self._calculate_trade_levels(opp, mode)
            
            if trade is None:
                continue
            
            # ── Position sizing ──────────────────────────────────────────────
            capital_pool = intraday_capital if mode == 'intraday' else swing_capital
            
            from capital_allocator import CapitalAllocator
            allocator = CapitalAllocator()
            
            quantity = allocator.calculate_position_size(
                capital_available=capital_pool,
                risk_per_trade=trade['risk_per_share'],
                stock_price=trade['entry'],
                stop_loss=trade['stop_loss'],
                mode=mode
            )
            
            if quantity == 0:
                continue
            
            # ── Finalize trade ───────────────────────────────────────────────
            position_value = trade['entry'] * quantity
            trade.update({
                'quantity': quantity,
                'position_value': position_value,
                'capital_used': position_value,
                'total_risk': trade['risk_per_share'] * quantity,
                'potential_profit': trade['reward_per_share'] * quantity,
            })
            
            selected_trades.append(trade)
            
            # Update capital usage
            if mode == 'intraday':
                intraday_capital_used += position_value
            else:
                swing_capital_used += position_value
        
        log.info(f"Selected {len(selected_trades)} trades "
                f"(Intraday: {sum(1 for t in selected_trades if t['mode']=='intraday')}, "
                f"Swing: {sum(1 for t in selected_trades if t['mode']=='swing')})")
        
        return selected_trades
    
    def _meets_quality_standards(self, opportunity: Dict) -> bool:
        """
        Check if opportunity meets minimum quality standards.
        """
        opp_score = opportunity.get('opportunity_score', 0)
        win_prob = opportunity.get('win_probability', 0)
        liquidity = opportunity.get('liquidity_score', 0)
        
        if opp_score < self.min_opp_score:
            return False
        
        if win_prob < self.min_win_prob:
            return False
        
        if liquidity < self.min_liquidity:
            return False
        
        return True
    
    def _determine_trade_mode(self, opportunity: Dict, market_sentiment: Dict) -> str:
        """
        Decide if this should be intraday or swing trade.
        
        Intraday: High volatility, breakouts, momentum in volatile markets
        Swing: Trend following, lower volatility, strong setups
        """
        strategy_fit = opportunity.get('strategy_fit', '')
        volatility = market_sentiment.get('volatility', 'moderate')
        bb_width = opportunity.get('bb_width', 0)
        
        # Breakouts and high volatility → intraday
        if strategy_fit in ['breakout', 'momentum'] and volatility == 'high':
            return 'intraday'
        
        # Tight squeeze → likely intraday breakout
        if bb_width < 0.015:
            return 'intraday'
        
        # Strong trends → swing
        if strategy_fit in ['swing', 'momentum'] and volatility in ['low', 'moderate']:
            return 'swing'
        
        # Mean reversion → intraday (quick in-out)
        if strategy_fit == 'mean_revert':
            return 'intraday'
        
        # Default: swing for stability
        return 'swing'
    
    def _calculate_trade_levels(self, opportunity: Dict, mode: str) -> Dict:
        """
        Calculate precise entry, stop-loss, and target levels.
        
        Always enforces minimum 2:1 R:R ratio.
        
        Returns dict with:
            - symbol
            - entry
            - stop_loss
            - target
            - risk_per_share
            - reward_per_share
            - rr_ratio
            - mode
            - strategy
            - confidence
        """
        symbol = opportunity.get('symbol')
        ltp = opportunity.get('ltp', 0)
        atr = opportunity.get('atr', 0)
        
        if ltp == 0 or atr == 0:
            log.warning(f"{symbol}: Invalid LTP or ATR")
            return None
        
        # ── Entry ─────────────────────────────────────────────────────────────
        # Use current LTP as entry
        entry = ltp
        
        # ── Stop Loss ─────────────────────────────────────────────────────────
        # ATR-based stop loss (1.5 × ATR below entry)
        stop_loss = entry - (self.atr_multiplier * atr)
        
        # Ensure SL is not too wide (max 5% from entry)
        max_sl_distance = entry * 0.05
        if (entry - stop_loss) > max_sl_distance:
            stop_loss = entry - max_sl_distance
        
        # ── Risk Calculation ──────────────────────────────────────────────────
        risk_per_share = entry - stop_loss
        
        if risk_per_share <= 0:
            log.warning(f"{symbol}: Invalid risk calculation")
            return None
        
        # ── Target (2:1 R:R minimum) ──────────────────────────────────────────
        reward_per_share = risk_per_share * self.rr_ratio
        target = entry + reward_per_share
        
        # ── Validation ────────────────────────────────────────────────────────
        actual_rr = reward_per_share / risk_per_share
        
        if actual_rr < self.min_rr_ratio:
            log.warning(f"{symbol}: R:R {actual_rr:.2f} below minimum")
            return None
        
        return {
            'symbol': symbol,
            'entry': round(entry, 2),
            'stop_loss': round(stop_loss, 2),
            'target': round(target, 2),
            'risk_per_share': round(risk_per_share, 2),
            'reward_per_share': round(reward_per_share, 2),
            'rr_ratio': round(actual_rr, 2),
            'mode': mode,
            'strategy': opportunity.get('strategy_fit', 'general'),
            'win_probability': opportunity.get('win_probability', 0.5),
            'expected_return': opportunity.get('expected_return', 0),
            'opportunity_score': opportunity.get('opportunity_score', 0),
            'entry_time': datetime.now(),
            
            # Store entry indicators for ML learning
            'entry_rsi': opportunity.get('rsi'),
            'entry_adx': opportunity.get('adx'),
            'entry_trend_score': opportunity.get('trend_score'),
            'entry_volume_ratio': opportunity.get('volume_ratio'),
        }
    
    def validate_trade(self, trade: Dict) -> Tuple[bool, str]:
        """
        Final validation before execution.
        
        Returns: (is_valid: bool, reason: str)
        """
        # Check all required fields present
        required = ['symbol', 'entry', 'stop_loss', 'target', 'quantity', 'mode']
        for field in required:
            if field not in trade or trade[field] is None:
                return (False, f"Missing required field: {field}")
        
        # Validate R:R
        if trade.get('rr_ratio', 0) < self.min_rr_ratio:
            return (False, f"R:R {trade['rr_ratio']:.2f} below minimum {self.min_rr_ratio}")
        
        # Validate quantity
        if trade.get('quantity', 0) <= 0:
            return (False, "Invalid quantity")
        
        # Validate prices
        entry = trade['entry']
        sl = trade['stop_loss']
        target = trade['target']
        
        if not (sl < entry < target):
            return (False, "Invalid price levels: must have SL < Entry < Target")
        
        return (True, "Valid")


# ══════════════════════════════════════════════════════════════════════════════
#  TRADE RANKER
# ══════════════════════════════════════════════════════════════════════════════

def rank_trades(trades: List[Dict], method: str = 'expected_value') -> List[Dict]:
    """
    Rank trades by priority.
    
    Methods:
    - 'expected_value': win_prob × expected_return
    - 'win_probability': highest win prob first
    - 'rr_ratio': highest R:R first
    - 'opportunity_score': highest opp score first
    """
    if method == 'expected_value':
        trades_sorted = sorted(
            trades,
            key=lambda t: t.get('win_probability', 0) * t.get('expected_return', 0),
            reverse=True
        )
    elif method == 'win_probability':
        trades_sorted = sorted(trades, key=lambda t: t.get('win_probability', 0), reverse=True)
    elif method == 'rr_ratio':
        trades_sorted = sorted(trades, key=lambda t: t.get('rr_ratio', 0), reverse=True)
    elif method == 'opportunity_score':
        trades_sorted = sorted(trades, key=lambda t: t.get('opportunity_score', 0), reverse=True)
    else:
        trades_sorted = trades
    
    return trades_sorted


if __name__ == "__main__":
    # Test trade selector
    logging.basicConfig(level=logging.INFO)
    
    selector = TradeSelector()
    
    # Mock opportunities
    opportunities = [
        {
            'symbol': 'TCS',
            'ltp': 3500,
            'atr': 52,
            'rsi': 62,
            'adx': 32,
            'bb_width': 0.025,
            'opportunity_score': 94,
            'win_probability': 0.72,
            'expected_return': 2.5,
            'liquidity_score': 85,
            'strategy_fit': 'momentum',
            'trend_score': 85,
            'volume_ratio': 1.4
        },
        {
            'symbol': 'INFY',
            'ltp': 1450,
            'atr': 18,
            'rsi': 58,
            'adx': 28,
            'bb_width': 0.018,
            'opportunity_score': 89,
            'win_probability': 0.68,
            'expected_return': 2.2,
            'liquidity_score': 82,
            'strategy_fit': 'swing',
            'trend_score': 78,
            'volume_ratio': 1.2
        }
    ]
    
    allocation = {
        'intraday_capital': 140000,
        'swing_capital': 210000,
        'trades_to_take': 5
    }
    
    market_sentiment = {
        'sentiment': 'bullish',
        'volatility': 'moderate'
    }
    
    selected = selector.select_trades(opportunities, allocation, market_sentiment)
    
    print(f"\nSelected {len(selected)} trades:\n")
    for trade in selected:
        print(f"{trade['symbol']} ({trade['mode'].upper()}):")
        print(f"  Entry: ₹{trade['entry']}")
        print(f"  SL: ₹{trade['stop_loss']} | Target: ₹{trade['target']}")
        print(f"  Qty: {trade['quantity']} shares | Value: ₹{trade['position_value']:,.0f}")
        print(f"  Risk: ₹{trade['total_risk']:.0f} | Reward: ₹{trade['potential_profit']:.0f}")
        print(f"  R:R: {trade['rr_ratio']:.2f} | Win Prob: {trade['win_probability']:.0%}")
        print()
