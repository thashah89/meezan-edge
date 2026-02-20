"""
engines/capital_allocator.py — Intelligent Capital Allocation Engine

Autonomously decides how much capital to deploy, split between intraday/swing,
and how to size each position based on market regime and risk parameters.

This is the "CFO" of the hedge fund.
"""

import logging
from typing import Dict, List, Tuple
from datetime import date

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  CAPITAL ALLOCATION AI
# ══════════════════════════════════════════════════════════════════════════════

class CapitalAllocator:
    """
    Autonomous capital allocation decision engine.
    
    Given total capital and market sentiment, determines:
    - How much to deploy today
    - Intraday vs swing split
    - Position sizing per trade
    - Number of positions to take
    """
    
    def __init__(self, config: Dict = None):
        self.config = config or {}
        
        # Risk parameters (configurable)
        self.max_deployment_pct = self.config.get('max_deployment_pct', 0.70)  # 70% max
        self.min_deployment_pct = self.config.get('min_deployment_pct', 0.30)  # 30% min
        self.max_position_size_pct = self.config.get('max_position_size_pct', 0.05)  # 5% per trade
        self.max_risk_per_trade_pct = self.config.get('max_risk_per_trade_pct', 0.02)  # 2% risk
        self.max_daily_loss_pct = self.config.get('max_daily_loss_pct', 0.03)  # 3% daily stop
        
    def allocate(self, 
                 total_capital: float,
                 market_sentiment: Dict,
                 opportunities: List[Dict],
                 current_positions: List[Dict] = None) -> Dict:
        """
        Main allocation decision.
        
        Args:
            total_capital: Total available capital
            market_sentiment: Market regime from intelligence engine
            opportunities: Ranked opportunity list
            current_positions: Currently open positions
        
        Returns:
            {
                'total_capital': float,
                'deployed_capital': float,
                'available_capital': float,
                'deployment_pct': float,
                'intraday_capital': float,
                'swing_capital': float,
                'intraday_pct': float,
                'swing_pct': float,
                'max_positions': int,
                'position_size': float,
                'trades_to_take': int
            }
        """
        current_positions = current_positions or []
        
        # ── Step 1: Market-driven deployment percentage ──────────────────────
        deployment_pct = self._calculate_deployment_pct(market_sentiment)
        
        # ── Step 2: Account for current exposure ─────────────────────────────
        current_exposure = sum(p.get('capital_used', 0) for p in current_positions)
        available_for_new = total_capital - current_exposure
        
        deployed_capital = min(
            total_capital * deployment_pct,
            available_for_new
        )
        
        # ── Step 3: Intraday vs Swing split ──────────────────────────────────
        intraday_pct, swing_pct = self._calculate_mode_split(market_sentiment)
        
        intraday_capital = deployed_capital * intraday_pct
        swing_capital = deployed_capital * swing_pct
        
        # ── Step 4: Position sizing ──────────────────────────────────────────
        max_positions = self._calculate_max_positions(
            deployed_capital, 
            total_capital
        )
        
        avg_position_size = deployed_capital / max_positions if max_positions > 0 else 0
        
        # ── Step 5: How many trades to take today ────────────────────────────
        high_quality_opps = [o for o in opportunities 
                           if o.get('opportunity_score', 0) >= 70
                           and o.get('win_probability', 0) >= 0.55]
        
        trades_to_take = min(len(high_quality_opps), max_positions - len(current_positions))
        trades_to_take = max(trades_to_take, 0)
        
        log.info(f"Capital Allocation: Deploy {deployment_pct:.0%} "
                f"({deployed_capital:,.0f} of {total_capital:,.0f}), "
                f"{trades_to_take} trades")
        
        return {
            'total_capital': total_capital,
            'deployed_capital': deployed_capital,
            'available_capital': total_capital - deployed_capital,
            'deployment_pct': deployment_pct,
            'intraday_capital': intraday_capital,
            'swing_capital': swing_capital,
            'intraday_pct': intraday_pct,
            'swing_pct': swing_pct,
            'max_positions': max_positions,
            'avg_position_size': avg_position_size,
            'trades_to_take': trades_to_take,
            'current_exposure': current_exposure,
        }
    
    def _calculate_deployment_pct(self, market_sentiment: Dict) -> float:
        """
        Determine deployment % based on market regime.
        
        Aggressive markets → higher deployment
        Uncertain/bearish → lower deployment
        """
        sentiment = market_sentiment.get('sentiment', 'sideways')
        confidence = market_sentiment.get('confidence', 50) / 100.0
        
        # Base deployment from sentiment
        base_deployment = market_sentiment.get('deployment_pct', 0.50)
        
        # Adjust by confidence
        # High confidence → closer to base
        # Low confidence → reduce toward min
        adjusted = base_deployment * confidence + self.min_deployment_pct * (1 - confidence)
        
        # Clamp to limits
        return max(self.min_deployment_pct, min(adjusted, self.max_deployment_pct))
    
    def _calculate_mode_split(self, market_sentiment: Dict) -> Tuple[float, float]:
        """
        Split between intraday and swing based on market volatility and trend.
        
        Returns: (intraday_pct, swing_pct) that sum to 1.0
        """
        sentiment = market_sentiment.get('sentiment', 'sideways')
        volatility = market_sentiment.get('volatility', 'moderate')
        
        # Get base split from sentiment
        intraday_pct = market_sentiment.get('intraday_pct', 0.50)
        swing_pct = market_sentiment.get('swing_pct', 0.50)
        
        # Adjust for volatility
        if volatility == 'high':
            # High volatility → favor intraday (faster exits)
            intraday_pct = min(intraday_pct + 0.15, 0.75)
            swing_pct = 1.0 - intraday_pct
        
        return (intraday_pct, swing_pct)
    
    def _calculate_max_positions(self, deployed_capital: float, total_capital: float) -> int:
        """
        Determine maximum number of concurrent positions.
        
        More capital → more positions
        But never too concentrated
        """
        # Base: 5% per position → max 20 positions at 100% deployment
        # Adjust by actual deployment level
        
        min_position_size = total_capital * self.max_position_size_pct
        
        if min_position_size == 0:
            return 0
        
        max_positions = int(deployed_capital / min_position_size)
        
        # Cap at reasonable level
        max_positions = min(max_positions, 15)  # Never more than 15 concurrent
        max_positions = max(max_positions, 3)   # Always allow at least 3
        
        return max_positions
    
    def calculate_position_size(self,
                                capital_available: float,
                                risk_per_trade: float,
                                stock_price: float,
                                stop_loss: float,
                                mode: str = 'swing') -> int:
        """
        Calculate exact position size (quantity) for a trade.
        
        Uses fixed fractional position sizing + risk-based adjustment.
        
        Args:
            capital_available: Capital allocated for this trade type
            risk_per_trade: Risk amount in rupees (entry - SL) * quantity
            stock_price: Entry price
            stop_loss: Stop loss price
            mode: 'intraday' or 'swing'
        
        Returns:
            Integer quantity to buy
        """
        # Max capital per position
        max_position_value = capital_available * self.max_position_size_pct
        
        # Risk-based sizing
        risk_per_share = abs(stock_price - stop_loss)
        
        if risk_per_share == 0:
            risk_per_share = stock_price * 0.02  # Default 2% risk
        
        # Max shares based on risk
        max_risk_amt = capital_available * self.max_risk_per_trade_pct
        max_shares_by_risk = int(max_risk_amt / risk_per_share)
        
        # Max shares based on position size
        max_shares_by_capital = int(max_position_value / stock_price)
        
        # Take the more conservative
        quantity = min(max_shares_by_risk, max_shares_by_capital)
        
        # Minimum 1 share (if can afford)
        if quantity < 1 and stock_price <= max_position_value:
            quantity = 1
        
        return max(quantity, 0)


# ══════════════════════════════════════════════════════════════════════════════
#  KELLY CRITERION (OPTIONAL ADVANCED MODE)
# ══════════════════════════════════════════════════════════════════════════════

def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """
    Calculate optimal bet size using Kelly Criterion.
    
    Formula: f = (p * b - q) / b
    where:
        p = win probability
        q = loss probability (1 - p)
        b = avg_win / avg_loss ratio
    
    Returns fraction of capital to risk (0.0 to 1.0)
    """
    if avg_loss == 0:
        return 0.0
    
    p = win_rate
    q = 1 - p
    b = avg_win / avg_loss
    
    kelly = (p * b - q) / b
    
    # Never bet more than 25% even if Kelly says so (half-kelly for safety)
    kelly = max(0.0, min(kelly * 0.5, 0.25))
    
    return kelly


# ══════════════════════════════════════════════════════════════════════════════
#  RISK MANAGER
# ══════════════════════════════════════════════════════════════════════════════

class RiskManager:
    """
    Monitors portfolio-level risk and enforces limits.
    """
    
    def __init__(self, max_daily_loss_pct: float = 0.03):
        self.max_daily_loss_pct = max_daily_loss_pct
        self.daily_start_capital = None
    
    def check_daily_loss_limit(self, current_capital: float, start_capital: float = None) -> Tuple[bool, str]:
        """
        Check if daily loss limit has been hit.
        
        Returns: (can_trade: bool, reason: str)
        """
        if start_capital is None:
            start_capital = self.daily_start_capital or current_capital
        
        if self.daily_start_capital is None:
            self.daily_start_capital = start_capital
        
        loss = start_capital - current_capital
        loss_pct = loss / start_capital if start_capital > 0 else 0
        
        if loss_pct >= self.max_daily_loss_pct:
            return (False, f"Daily loss limit hit: {loss_pct:.1%} (max {self.max_daily_loss_pct:.1%})")
        
        return (True, "Within limits")
    
    def reset_daily(self, current_capital: float):
        """Call this at start of each trading day."""
        self.daily_start_capital = current_capital
        log.info(f"Daily risk reset. Starting capital: ₹{current_capital:,.0f}")


if __name__ == "__main__":
    # Test capital allocator
    logging.basicConfig(level=logging.INFO)
    
    allocator = CapitalAllocator()
    
    market_sentiment = {
        'sentiment': 'aggressive_bullish',
        'volatility': 'moderate',
        'confidence': 85,
        'deployment_pct': 0.70,
        'intraday_pct': 0.40,
        'swing_pct': 0.60
    }
    
    opportunities = [
        {'symbol': 'TCS', 'opportunity_score': 94, 'win_probability': 0.72},
        {'symbol': 'INFY', 'opportunity_score': 89, 'win_probability': 0.68},
        {'symbol': 'RELIANCE', 'opportunity_score': 85, 'win_probability': 0.65},
    ]
    
    allocation = allocator.allocate(
        total_capital=500_000,
        market_sentiment=market_sentiment,
        opportunities=opportunities
    )
    
    print("\nCapital Allocation Plan:")
    for key, value in allocation.items():
        if isinstance(value, float):
            if 'pct' in key:
                print(f"  {key}: {value:.1%}")
            else:
                print(f"  {key}: ₹{value:,.0f}")
        else:
            print(f"  {key}: {value}")
    
    # Test position sizing
    print("\nPosition Sizing for TCS @ ₹3,500:")
    qty = allocator.calculate_position_size(
        capital_available=allocation['swing_capital'],
        risk_per_trade=3500 - 3422,  # 78 rupees risk
        stock_price=3500,
        stop_loss=3422,
        mode='swing'
    )
    print(f"  Quantity: {qty} shares")
    print(f"  Position value: ₹{qty * 3500:,.0f}")
    print(f"  Risk: ₹{qty * 78:,.0f}")
