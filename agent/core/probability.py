"""Probability engine.

Inputs (all optional except market price):
  * market implied probability (from book mid or last)
  * news/catalyst signal in [-1, +1] for the chosen side
  * wallet alignment in [-1, +1] for the chosen side
  * sentiment in [-1, +1]
  * resolution_clarity in [0, 1]
  * time_to_close_hours

Output: ProbabilityEstimate with edge = estimated - implied (signed
toward the side under consideration).

The default model here is intentionally simple and transparent. It's a
linear blend on the logit scale, with confidence falling when inputs
disagree. Replace with a category-specific model when you have one —
the interface is what matters.
"""
from __future__ import annotations

import math
from typing import Optional

from ..types import ProbabilityEstimate


def _logit(p: float) -> float:
    p = max(1e-6, min(1 - 1e-6, p))
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1 / (1 + z)
    z = math.exp(x)
    return z / (1 + z)


def estimate(
    market_implied: float,
    side_is_yes: bool = True,
    news_signal: float = 0.0,        # -1..+1, oriented to YES
    wallet_signal: float = 0.0,      # -1..+1, oriented to YES
    sentiment: float = 0.0,          # -1..+1, oriented to YES
    resolution_clarity: float = 1.0, # 0..1; lowers confidence
    time_to_close_hours: Optional[float] = None,
) -> ProbabilityEstimate:
    """Estimate fair probability for the YES side, then orient toward
    the requested side at the end. Keeping the math YES-centered avoids
    sign bugs."""
    base_logit = _logit(market_implied)

    # Each signal nudges the logit. Caps keep any one input from
    # producing a runaway estimate.
    nudges = {
        "news": 0.6 * max(-1.0, min(1.0, news_signal)),
        "wallets": 0.5 * max(-1.0, min(1.0, wallet_signal)),
        "sentiment": 0.15 * max(-1.0, min(1.0, sentiment)),  # weak by design
    }
    adjusted = base_logit + sum(nudges.values())
    p_yes = _sigmoid(adjusted)

    # Confidence: starts from resolution clarity, drops when signals
    # disagree, drops again very near close where revisions hurt.
    signal_vec = [news_signal, wallet_signal, sentiment]
    nonzero = [s for s in signal_vec if abs(s) > 0.05]
    if len(nonzero) >= 2:
        # If signs disagree, penalize.
        signs = [1 if s > 0 else -1 for s in nonzero]
        agreement = abs(sum(signs)) / len(signs)  # 1 if all same sign
    else:
        agreement = 1.0
    confidence = resolution_clarity * (0.5 + 0.5 * agreement)
    if time_to_close_hours is not None and time_to_close_hours < 1.0:
        confidence *= 0.7
    confidence = max(0.0, min(1.0, confidence))

    # Fair value range: ± up to 8 logit-units of uncertainty scaled by (1-confidence).
    band = 0.6 * (1 - confidence)  # logit space
    low_yes = _sigmoid(adjusted - band)
    high_yes = _sigmoid(adjusted + band)

    if side_is_yes:
        est, low, high, implied = p_yes, low_yes, high_yes, market_implied
    else:
        est = 1 - p_yes
        low = 1 - high_yes
        high = 1 - low_yes
        implied = 1 - market_implied

    edge = est - implied  # signed toward chosen side

    return ProbabilityEstimate(
        estimated_prob=est,
        confidence=confidence,
        market_implied_prob=implied,
        edge=edge,
        fair_value_low=low,
        fair_value_high=high,
        rationale=(
            f"base p_yes(implied)={market_implied:.3f}; "
            f"nudges={nudges}; adjusted_logit={adjusted:.3f}; "
            f"resolution_clarity={resolution_clarity:.2f}; "
            f"agreement={agreement:.2f}"
        ),
        components={
            "market_implied": market_implied,
            "p_yes_after_nudges": p_yes,
            "nudges": nudges,
            "agreement": agreement,
        },
    )
