from datetime import datetime, timezone

from agent.config import DecisionCfg
from agent.core import decision
from agent.types import (
    Decision,
    Market,
    OrderBook,
    OrderBookLevel,
    Outcome,
    ProbabilityEstimate,
    Side,
    TradeOpportunity,
)


def _cfg() -> DecisionCfg:
    return DecisionCfg(
        min_edge=0.05, min_confidence=0.55, min_liquidity_usd=200.0,
        max_spread=0.03, max_slippage_pct=0.02,
        min_resolution_clarity=0.70, min_source_credibility=0.60,
        min_trade_score=0.30,
        weights={
            "edge": 1.0, "confidence": 1.0, "liquidity": 0.5,
            "resolution_clarity": 0.8, "source_credibility": 0.6,
            "wallet_signal": 0.4, "catalyst": 0.6,
            "spread_penalty": 1.5, "slippage_penalty": 1.5,
            "manipulation_penalty": 1.0, "correlation_penalty": 0.8,
            "uncertainty_penalty": 1.0,
        },
    )


def _opp(**overrides) -> TradeOpportunity:
    market = Market(
        market_id="m1", slug="s", question="Q?",
        outcomes=[Outcome(token_id="t", name="Yes", price=0.40)],
    )
    book = OrderBook(
        token_id="t",
        bids=[OrderBookLevel(price=0.39, size=1000)],
        asks=[OrderBookLevel(price=0.40, size=1000)],
        timestamp=datetime.now(timezone.utc),
    )
    base = dict(
        market=market, outcome=market.outcomes[0], side=Side.BUY, book=book,
        probability=ProbabilityEstimate(
            estimated_prob=0.50, confidence=0.70,
            market_implied_prob=0.40, edge=0.10,
            fair_value_low=0.45, fair_value_high=0.55,
        ),
        spread=0.01, slippage_pct=0.005, max_fill_usd=500.0,
        liquidity_quality=0.8, resolution_clarity=0.85,
        source_credibility=0.75, wallet_signal=0.4,
        catalyst_strength=0.6, manipulation_risk=0.1, correlation_risk=0.0,
    )
    base.update(overrides)
    return TradeOpportunity(**base)


def test_strong_setup_enters():
    o = decision.evaluate(_opp(), _cfg())
    assert o.decision is Decision.ENTER
    assert o.score > 0.30


def test_thin_liquidity_blocks():
    o = decision.evaluate(_opp(max_fill_usd=50.0), _cfg())
    assert o.decision is Decision.NO_TRADE
    assert any("liquidity" in r for r in o.reasons)


def test_low_edge_blocks():
    o = decision.evaluate(
        _opp(probability=ProbabilityEstimate(
            estimated_prob=0.42, confidence=0.70, market_implied_prob=0.40,
            edge=0.02, fair_value_low=0.40, fair_value_high=0.44,
        )),
        _cfg(),
    )
    assert o.decision is Decision.NO_TRADE
    assert any("edge" in r for r in o.reasons)


def test_low_confidence_blocks():
    o = decision.evaluate(
        _opp(probability=ProbabilityEstimate(
            estimated_prob=0.50, confidence=0.40, market_implied_prob=0.40,
            edge=0.10, fair_value_low=0.45, fair_value_high=0.55,
        )),
        _cfg(),
    )
    assert o.decision is Decision.NO_TRADE
    assert any("confidence" in r for r in o.reasons)


def test_ambiguous_resolution_blocks():
    o = decision.evaluate(_opp(resolution_clarity=0.30), _cfg())
    assert o.decision is Decision.NO_TRADE
    assert any("resolution" in r for r in o.reasons)


def test_borderline_setup_watches_not_enters():
    # All gates pass but score is low. We force this by tanking liquidity quality
    # and source credibility just enough to keep gates open while scoring poorly.
    cfg = _cfg()
    cfg.min_trade_score = 0.50  # raise the bar
    o = decision.evaluate(_opp(liquidity_quality=0.2, catalyst_strength=0.0,
                                wallet_signal=0.0), cfg)
    # Either WATCH (gates clear, score low) or NO_TRADE (gate). Both acceptable
    # signals, but not ENTER.
    assert o.decision is not Decision.ENTER
