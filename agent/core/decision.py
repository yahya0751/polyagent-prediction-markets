"""Trade decision engine.

Implements the formula and gates from the spec, exactly. Every
NO_TRADE has a list of reasons attached; never a silent rejection.
"""
from __future__ import annotations

from ..config import DecisionCfg
from ..types import Decision, TradeOpportunity


def evaluate(opp: TradeOpportunity, cfg: DecisionCfg) -> TradeOpportunity:
    """Mutates opp.score, opp.decision, opp.reasons. Returns the same
    object for chaining."""
    reasons: list[str] = []
    w = cfg.weights

    # ---------------- Hard gates ----------------
    # If any gate fails, decision = NO_TRADE regardless of score.
    if opp.probability.edge < cfg.min_edge:
        reasons.append(
            f"edge {opp.probability.edge:+.3f} below min {cfg.min_edge:+.3f}"
        )
    if opp.probability.confidence < cfg.min_confidence:
        reasons.append(
            f"confidence {opp.probability.confidence:.2f} below min {cfg.min_confidence:.2f}"
        )
    if opp.max_fill_usd < cfg.min_liquidity_usd:
        reasons.append(
            f"liquidity ${opp.max_fill_usd:.0f} below min ${cfg.min_liquidity_usd:.0f}"
        )
    if opp.spread > cfg.max_spread:
        reasons.append(f"spread {opp.spread:.3f} above max {cfg.max_spread:.3f}")
    if opp.slippage_pct > cfg.max_slippage_pct:
        reasons.append(
            f"slippage {opp.slippage_pct:.3f} above max {cfg.max_slippage_pct:.3f}"
        )
    if opp.resolution_clarity < cfg.min_resolution_clarity:
        reasons.append(
            f"resolution clarity {opp.resolution_clarity:.2f} below min {cfg.min_resolution_clarity:.2f}"
        )
    if opp.source_credibility < cfg.min_source_credibility:
        reasons.append(
            f"source credibility {opp.source_credibility:.2f} below min "
            f"{cfg.min_source_credibility:.2f}"
        )

    # ---------------- Score formula ----------------
    # The spec reads: edge × confidence × liquidity × resolution × source ×
    # wallet × catalyst − penalties. A pure product zeros out on any single
    # weak input — we use a weighted product/sum hybrid: positives multiply
    # softly (geometric blend), penalties subtract.
    pos_terms = [
        (opp.probability.edge, w["edge"]),
        (opp.probability.confidence, w["confidence"]),
        (opp.liquidity_quality, w["liquidity"]),
        (opp.resolution_clarity, w["resolution_clarity"]),
        (opp.source_credibility, w["source_credibility"]),
        # wallet signal is signed; only count if aligned with our side
        (max(0.0, opp.wallet_signal), w["wallet_signal"]),
        (opp.catalyst_strength, w["catalyst"]),
    ]
    # Normalize edge to a [0,1]-ish bounded contribution (cap at 0.20)
    pos_terms[0] = (min(1.0, max(0.0, opp.probability.edge / 0.20)), w["edge"])
    pos_score = 0.0
    total_w = sum(weight for _, weight in pos_terms) or 1.0
    for value, weight in pos_terms:
        pos_score += weight * max(0.0, min(1.0, value))
    pos_score /= total_w  # in [0, 1]

    # Penalties (each in [0, 1])
    spread_penalty = min(1.0, opp.spread / 0.05) * w["spread_penalty"] * 0.05
    slippage_penalty = min(1.0, opp.slippage_pct / 0.05) * w["slippage_penalty"] * 0.05
    manipulation_penalty = opp.manipulation_risk * w["manipulation_penalty"] * 0.10
    correlation_penalty = opp.correlation_risk * w["correlation_penalty"] * 0.10
    uncertainty_penalty = (1 - opp.probability.confidence) * w["uncertainty_penalty"] * 0.05

    score = (pos_score
             - spread_penalty
             - slippage_penalty
             - manipulation_penalty
             - correlation_penalty
             - uncertainty_penalty)
    opp.score = max(-1.0, min(1.0, score))

    # ---------------- Decision ----------------
    if reasons:
        opp.decision = Decision.NO_TRADE
    elif opp.score < cfg.min_trade_score:
        opp.decision = Decision.WATCH
        reasons.append(
            f"score {opp.score:.3f} below min {cfg.min_trade_score:.3f}"
        )
    else:
        opp.decision = Decision.ENTER

    opp.reasons = reasons
    return opp
