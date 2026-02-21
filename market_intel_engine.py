"""
engines/market_intel.py — Market Intelligence Engine for Meezan Edge v3.0

Autonomous market analysis, sentiment detection, and opportunity scoring.
This is the "brain" that evaluates all stocks and market conditions.
"""

import pandas as pd
import numpy as np
from datetime import date, timedelta
from typing import Dict, List, Tuple
import logging

log = logging.getLogger(__name__)


def _safe_float(value, default: float) -> float:
    """Best-effort numeric coercion for partially populated metric rows."""
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return default
        return float(value)
    except (TypeError, ValueError):
        return default


# ══════════════════════════════════════════════════════════════════════════════
#  MARKET SENTIMENT DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def detect_market_sentiment(nifty_data: pd.DataFrame = None) -> Dict:
    """
    Analyze market conditions and return sentiment + recommended approach.
    
    Args:
        nifty_data: DataFrame with Nifty index OHLCV + indicators
    
    Returns:
        {
            'sentiment': str,      # bullish, bearish, sideways, high_vol, breakout
            'volatility': str,     # low, moderate, high
            'confidence': float,   # 0-100
            'recommended_style': str,
            'deployment_pct': float,
            'intraday_pct': float,
            'swing_pct': float
        }
    """
    # If no Nifty data provided, use conservative defaults
    if nifty_data is None or len(nifty_data) < 50:
        log.warning("No Nifty data — using conservative default sentiment")
        return {
            'sentiment': 'sideways',
            'volatility': 'moderate',
            'confidence': 50.0,
            'recommended_style': 'Conservative',
            'deployment_pct': 0.50,
            'intraday_pct': 0.50,
            'swing_pct': 0.50
        }
    
    latest = nifty_data.iloc[-1]
    
    # ── Trend Analysis ────────────────────────────────────────────────────────
    sma_20 = latest.get('SMA_20', latest['Close'])
    sma_50 = latest.get('SMA_50', latest['Close'])
    sma_200 = latest.get('SMA_200', latest['Close'])
    close = latest['Close']
    
    above_sma20 = close > sma_20
    above_sma50 = close > sma_50
    above_sma200 = close > sma_200
    golden_cross = sma_50 > sma_200
    
    trend_score = sum([above_sma20, above_sma50, above_sma200, golden_cross])
    
    # ── Momentum ──────────────────────────────────────────────────────────────
    rsi = latest.get('RSI', 50)
    adx = latest.get('ADX', 20)
    macd = latest.get('MACD', 0)
    macd_signal = latest.get('MACD_Signal', 0)
    
    macd_bullish = macd > macd_signal
    rsi_strong = rsi > 55
    adx_trending = adx > 25
    
    # ── Volatility ────────────────────────────────────────────────────────────
    atr = latest.get('ATR', 0)
    bb_width = latest.get('BB_Width', 0)
    
    # Classify volatility
    if atr == 0:
        volatility = 'moderate'
    elif bb_width < 0.02:
        volatility = 'low'
    elif bb_width > 0.05:
        volatility = 'high'
    else:
        volatility = 'moderate'
    
    # ── Sentiment Classification ──────────────────────────────────────────────
    if trend_score >= 3 and macd_bullish and rsi_strong:
        sentiment = 'aggressive_bullish'
        recommended_style = 'Momentum + Breakouts'
        deployment_pct = 0.70
        intraday_pct = 0.40
        swing_pct = 0.60
        confidence = 85.0
        
    elif trend_score >= 2 and macd_bullish:
        sentiment = 'bullish'
        recommended_style = 'Trend Following'
        deployment_pct = 0.60
        intraday_pct = 0.45
        swing_pct = 0.55
        confidence = 75.0
        
    elif trend_score <= 1 and rsi < 40:
        sentiment = 'bearish'
        recommended_style = 'Mean Reversion Only'
        deployment_pct = 0.30
        intraday_pct = 0.70  # Faster exits
        swing_pct = 0.30
        confidence = 70.0
        
    elif volatility == 'high':
        sentiment = 'high_vol'
        recommended_style = 'Volatility Breakouts'
        deployment_pct = 0.40
        intraday_pct = 0.60
        swing_pct = 0.40
        confidence = 65.0
        
    elif bb_width < 0.015 and adx < 20:
        sentiment = 'breakout_setup'
        recommended_style = 'Wait for Breakout'
        deployment_pct = 0.45
        intraday_pct = 0.55
        swing_pct = 0.45
        confidence = 72.0
        
    else:
        sentiment = 'sideways'
        recommended_style = 'Range Trading'
        deployment_pct = 0.50
        intraday_pct = 0.55
        swing_pct = 0.45
        confidence = 60.0
    
    return {
        'sentiment': sentiment,
        'volatility': volatility,
        'confidence': round(confidence, 1),
        'recommended_style': recommended_style,
        'deployment_pct': deployment_pct,
        'intraday_pct': intraday_pct,
        'swing_pct': swing_pct,
        'nifty_trend': f"{'Bullish' if trend_score >= 2 else 'Bearish'}",
        'market_breadth': None,  # To be implemented with advance/decline data
        'sector_strength': None,  # To be implemented
    }


# ══════════════════════════════════════════════════════════════════════════════
#  OPPORTUNITY SCORING ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def calculate_opportunity_score(stock_metrics: Dict, market_sentiment: Dict = None) -> int:
    """
    Calculate 0-100 opportunity score for a stock.
    
    Score components:
    - Trend strength (25%)
    - Momentum quality (20%)
    - Volume confirmation (15%)
    - Volatility fit (15%)
    - ML prediction (25%)
    
    Args:
        stock_metrics: Dict with all technical indicators
        market_sentiment: Optional market regime context
    
    Returns:
        Integer score 0-100
    """
    score = 0
    
    # ── Trend Strength (25 points) ────────────────────────────────────────────
    trend_score = _safe_float(stock_metrics.get('trend_score', 0), 0.0)
    if trend_score >= 80:
        score += 25
    elif trend_score >= 60:
        score += 20
    elif trend_score >= 40:
        score += 12
    elif trend_score >= 20:
        score += 5
    
    # ── Momentum Quality (20 points) ──────────────────────────────────────────
    rsi = _safe_float(stock_metrics.get('rsi', 50), 50.0)
    adx = _safe_float(stock_metrics.get('adx', 0), 0.0)
    macd = _safe_float(stock_metrics.get('macd', 0), 0.0)
    macd_signal = _safe_float(stock_metrics.get('macd_signal', 0), 0.0)
    
    # Ideal: RSI 55-70 (not overbought, strong momentum)
    if 55 <= rsi <= 70:
        score += 8
    elif 45 <= rsi <= 75:
        score += 5
    elif rsi < 35:  # Oversold opportunity
        score += 6
    
    # ADX trending
    if adx >= 30:
        score += 7
    elif adx >= 20:
        score += 5
    
    # MACD bullish
    if macd > macd_signal:
        score += 5
    
    # ── Volume Confirmation (15 points) ───────────────────────────────────────
    volume_ratio = _safe_float(stock_metrics.get('volume_ratio', 1.0), 1.0)
    if volume_ratio >= 1.5:
        score += 15
    elif volume_ratio >= 1.2:
        score += 10
    elif volume_ratio >= 1.0:
        score += 6
    
    # ── Volatility Fit (15 points) ────────────────────────────────────────────
    bb_width = _safe_float(stock_metrics.get('bb_width', 0), 0.0)
    atr = _safe_float(stock_metrics.get('atr', 0), 0.0)
    ltp = _safe_float(stock_metrics.get('ltp', 100), 100.0)
    
    atr_pct = (atr / ltp * 100) if ltp > 0 else 0
    
    # Ideal: Moderate volatility (not too tight, not too wild)
    if 1.5 <= atr_pct <= 4.0:
        score += 15
    elif 1.0 <= atr_pct <= 5.0:
        score += 10
    elif atr_pct < 1.0 and bb_width < 0.02:  # Squeeze = potential breakout
        score += 12
    
    # ── ML Prediction (25 points) ─────────────────────────────────────────────
    win_prob = _safe_float(stock_metrics.get('win_probability', 0.5), 0.5)
    expected_return = _safe_float(stock_metrics.get('expected_return', 0), 0.0)
    
    if win_prob >= 0.70:
        score += 18
    elif win_prob >= 0.60:
        score += 14
    elif win_prob >= 0.55:
        score += 10
    
    if expected_return >= 3.0:
        score += 7
    elif expected_return >= 2.0:
        score += 5
    elif expected_return >= 1.0:
        score += 3
    
    # ── Market Regime Bonus ───────────────────────────────────────────────────
    if market_sentiment:
        sentiment = market_sentiment.get('sentiment', 'sideways')
        
        # Bonus for momentum stocks in bullish market
        if sentiment in ['bullish', 'aggressive_bullish'] and rsi > 60 and adx > 25:
            score = min(score + 5, 100)
        
        # Bonus for mean reversion in bearish/sideways
        if sentiment in ['bearish', 'sideways'] and rsi < 35:
            score = min(score + 5, 100)
    
    return min(max(score, 0), 100)  # Clamp to 0-100


def score_all_stocks(metrics_list: List[Dict], market_sentiment: Dict = None) -> List[Dict]:
    """
    Score all stocks and return ranked list.
    
    Args:
        metrics_list: List of stock metric dicts
        market_sentiment: Market regime context
    
    Returns:
        List of dicts with scores, sorted by opportunity_score desc
    """
    scored = []
    
    for metrics in metrics_list:
        opp_score = calculate_opportunity_score(metrics, market_sentiment)
        
        # Add score to metrics
        enriched = metrics.copy()
        enriched['opportunity_score'] = opp_score
        
        # Determine strategy fit
        enriched['strategy_fit'] = determine_strategy_fit(metrics)
        
        scored.append(enriched)
    
    # Sort by opportunity score descending
    scored.sort(key=lambda x: x['opportunity_score'], reverse=True)
    
    return scored


# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY FIT DETERMINATION
# ══════════════════════════════════════════════════════════════════════════════

def determine_strategy_fit(metrics: Dict) -> str:
    """
    Determine which trading strategy best fits this stock's profile.
    
    Returns: "momentum" | "breakout" | "swing" | "mean_revert" | "none"
    """
    rsi = _safe_float(metrics.get('rsi', 50), 50.0)
    adx = _safe_float(metrics.get('adx', 0), 0.0)
    bb_width = _safe_float(metrics.get('bb_width', 0), 0.0)
    volume_ratio = _safe_float(metrics.get('volume_ratio', 1.0), 1.0)
    trend_score = _safe_float(metrics.get('trend_score', 0), 0.0)
    
    # bb_width may be represented as ratio (0.02) or percent (2.0).
    bb_width_norm = (bb_width / 100.0) if bb_width > 1 else bb_width
    
    # Momentum: Strong trend + RSI 55-70 + ADX 30+
    if trend_score >= 65 and 52 <= rsi <= 72 and adx >= 22:
        return 'momentum'
    
    # Breakout: Squeeze + volume surge + ADX rising
    if bb_width_norm < 0.02 and volume_ratio >= 1.2 and 18 <= adx <= 38:
        return 'breakout'
    
    # Swing: Uptrend + pullback + moderate ADX
    if trend_score >= 55 and 38 <= rsi <= 62 and 16 <= adx <= 42:
        return 'swing'
    
    # Mean Reversion: Oversold + low ADX
    if rsi <= 35 and adx < 20:
        return 'mean_revert'
    
    # Fallback to avoid excessive "none" for otherwise tradable setups.
    if trend_score >= 50:
        return 'swing'
    
    return 'none'


# ══════════════════════════════════════════════════════════════════════════════
#  FILTERS
# ══════════════════════════════════════════════════════════════════════════════

def apply_filters(scored_stocks: List[Dict], filters: Dict) -> List[Dict]:
    """
    Apply user-defined filters to ranked stock list.
    
    Args:
        scored_stocks: List of scored stock dicts
        filters: Dict with filter criteria
    
    Returns:
        Filtered list
    """
    filtered = scored_stocks.copy()
    
    # Uptrend only
    if filters.get('uptrend_only'):
        filtered = [s for s in filtered if s.get('trend_score', 0) >= 60]
    
    # Strong momentum
    if filters.get('strong_momentum'):
        filtered = [s for s in filtered if 
                   s.get('adx', 0) >= 25 and s.get('rsi', 50) > 55]
    
    # Breakout ready
    if filters.get('breakout_ready'):
        filtered = [s for s in filtered if
                   s.get('bb_width', 1) < 0.02 and s.get('volume_ratio', 0) > 1.2]
    
    # Oversold
    if filters.get('oversold'):
        filtered = [s for s in filtered if s.get('rsi', 50) < 35]
    
    # High volume
    if filters.get('high_volume'):
        filtered = [s for s in filtered if s.get('volume_ratio', 0) >= 1.5]
    
    # RSI range
    rsi_min = filters.get('rsi_min')
    rsi_max = filters.get('rsi_max')
    if rsi_min is not None or rsi_max is not None:
        rsi_min = rsi_min if rsi_min is not None else 0
        rsi_max = rsi_max if rsi_max is not None else 100
        filtered = [s for s in filtered if
                   rsi_min <= s.get('rsi', 50) <= rsi_max]
    
    # ADX strength
    adx_min = filters.get('adx_min')
    if adx_min is not None:
        filtered = [s for s in filtered if s.get('adx', 0) >= adx_min]
    
    # Strategy fit
    strategy_fit = filters.get('strategy_fit')
    if strategy_fit and strategy_fit != 'all':
        filtered = [s for s in filtered if s.get('strategy_fit') == strategy_fit]
    
    # Minimum opportunity score
    min_score = filters.get('min_opportunity_score', 0)
    filtered = [s for s in filtered if s.get('opportunity_score', 0) >= min_score]
    
    return filtered


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN INTERFACE
# ══════════════════════════════════════════════════════════════════════════════

class MarketIntelligenceEngine:
    """
    Main interface for market intelligence operations.
    """
    
    def __init__(self):
        self.sentiment = None
        self.scored_stocks = []
    
    def analyze_market(self, nifty_data: pd.DataFrame = None) -> Dict:
        """Run market sentiment analysis."""
        self.sentiment = detect_market_sentiment(nifty_data)
        log.info(f"Market Sentiment: {self.sentiment['sentiment']} "
                f"(confidence: {self.sentiment['confidence']}%)")
        return self.sentiment
    
    def score_opportunities(self, metrics_list: List[Dict]) -> List[Dict]:
        """Score and rank all stocks."""
        self.scored_stocks = score_all_stocks(metrics_list, self.sentiment)
        log.info(f"Scored {len(self.scored_stocks)} stocks. "
                f"Top score: {self.scored_stocks[0]['opportunity_score'] if self.scored_stocks else 0}")
        return self.scored_stocks
    
    def get_top_opportunities(self, n: int = 20, filters: Dict = None) -> List[Dict]:
        """Get top N opportunities with optional filters."""
        stocks = self.scored_stocks
        
        if filters:
            stocks = apply_filters(stocks, filters)
        
        return stocks[:n]
    
    def get_stock_analysis(self, symbol: str) -> Dict:
        """Get detailed analysis for a specific stock."""
        for stock in self.scored_stocks:
            if stock.get('symbol') == symbol:
                return stock
        return None


if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.INFO)
    
    engine = MarketIntelligenceEngine()
    
    # Mock market sentiment
    sentiment = engine.analyze_market()
    print("\nMarket Sentiment:")
    for k, v in sentiment.items():
        print(f"  {k}: {v}")
    
    # Mock stock metrics
    test_stocks = [
        {
            'symbol': 'TCS', 'ltp': 3500, 'rsi': 62, 'adx': 32,
            'trend_score': 75, 'volume_ratio': 1.4, 'bb_width': 0.025,
            'atr': 52, 'macd': 5, 'macd_signal': 3,
            'win_probability': 0.68, 'expected_return': 2.5
        },
        {
            'symbol': 'INFY', 'ltp': 1450, 'rsi': 48, 'adx': 18,
            'trend_score': 55, 'volume_ratio': 0.9, 'bb_width': 0.015,
            'atr': 18, 'macd': -2, 'macd_signal': -1,
            'win_probability': 0.52, 'expected_return': 1.2
        }
    ]
    
    scored = engine.score_opportunities(test_stocks)
    print("\nScored Opportunities:")
    for stock in scored:
        print(f"  {stock['symbol']}: {stock['opportunity_score']} "
              f"(fit: {stock['strategy_fit']})")
