"""Exit / stop engine.

Given a Position and current market context, decide whether to exit
(and how much). Returns ExitDecision objects; the runner is responsible
for actually placing exit orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ..config import RiskCfg
from ..types import Position, Side


class ExitAction(str, Enum):
    HOLD = "HOLD"
    REDUCE = "REDUCE"   # sell partial
    EXIT = "EXIT"       # close fully


@dataclass
class ExitDecision:
    action: ExitAction
    fraction: float = 0.0   # fraction of remaining size to close (0..1)
    reason: str = ""


def evaluate(
    pos: Position,
    current_price: float,
    cfg: RiskCfg,
    *,
    thesis_invalidated: bool = False,
    smart_wallet_dropoff: float = 0.0,   # 0..1; how much smart-money exposure dropped
    liquidity_quality_now: float = 1.0,  # 0..1 from current book
    max_correlation_now: float = 0.0,    # 0..1
    confidence_now: Optional[float] = None,
) -> ExitDecision:
    """Apply the spec's exit triggers in priority order. First match wins."""
    # 1. Thesis invalidation — full exit immediately
    if thesis_invalidated:
        return ExitDecision(ExitAction.EXIT, 1.0, "thesis invalidated by official source/news")

    # 2. Smart-wallet exodus
    if smart_wallet_dropoff >= 0.40:
        return ExitDecision(ExitAction.EXIT, 1.0,
                            f"smart-wallet exposure dropped {smart_wallet_dropoff:.0%}")

    # 3. Hard stop-loss (price-based)
    if pos.side is Side.BUY:
        # For BUY: stop if price falls below stop_loss_price
        if pos.stop_loss_price > 0 and current_price <= pos.stop_loss_price:
            return ExitDecision(ExitAction.EXIT, 1.0,
                                f"hard stop hit: {current_price:.3f} <= {pos.stop_loss_price:.3f}")
    else:
        if pos.stop_loss_price > 0 and current_price >= pos.stop_loss_price:
            return ExitDecision(ExitAction.EXIT, 1.0,
                                f"hard stop hit: {current_price:.3f} >= {pos.stop_loss_price:.3f}")

    # 4. Liquidity collapse
    if liquidity_quality_now < 0.20:
        return ExitDecision(ExitAction.EXIT, 1.0,
                            f"liquidity collapsed (quality={liquidity_quality_now:.2f})")

    # 5. Confidence drop below survival threshold (treat 0.40 as floor)
    if confidence_now is not None and confidence_now < 0.40:
        return ExitDecision(ExitAction.REDUCE, 0.5,
                            f"confidence dropped to {confidence_now:.2f}")

    # 6. Correlation risk
    if max_correlation_now >= 0.85:
        return ExitDecision(ExitAction.REDUCE, 0.5,
                            f"correlation rose to {max_correlation_now:.2f}")

    # 7. Trailing stop (priority over TP once activated — locks in profit)
    if pos.trailing_stop_price is not None:
        if (pos.side is Side.BUY and current_price <= pos.trailing_stop_price) or \
           (pos.side is Side.SELL and current_price >= pos.trailing_stop_price):
            return ExitDecision(ExitAction.EXIT, 1.0,
                                f"trailing stop hit at {pos.trailing_stop_price:.3f}")

    # 8. Take-profit ladders (partial)
    pnl_per_share = (current_price - pos.avg_entry_price) if pos.side is Side.BUY \
                    else (pos.avg_entry_price - current_price)
    for tp_price in pos.take_profit_prices:
        hit = (pos.side is Side.BUY and current_price >= tp_price) or \
              (pos.side is Side.SELL and current_price <= tp_price)
        if hit:
            # Default partial fraction comes from cfg ladder positions; the
            # runner is responsible for clearing each TP after hit so we
            # don't repeat them. We just signal a reduce.
            return ExitDecision(ExitAction.REDUCE, 0.30,
                                f"take-profit hit at {tp_price:.3f}")

    # 9. Activate trailing stop once profit threshold reached
    activation = cfg.trailing_stop_activation_profit
    if pnl_per_share >= activation and pos.trailing_stop_price is None:
        # Side note: caller should mutate pos.trailing_stop_price; we just
        # tell them to via a HOLD with reason. The runtime updates the
        # trailing price each tick after activation.
        return ExitDecision(ExitAction.HOLD, 0.0,
                            f"activate trailing stop (profit={pnl_per_share:+.3f})")

    return ExitDecision(ExitAction.HOLD, 0.0, "no exit trigger")


def update_trailing(
    pos: Position,
    current_price: float,
    cfg: RiskCfg,
) -> None:
    """Mutate pos.trailing_stop_price if active. Trailing follows price
    by `trailing_stop_distance` and never moves unfavorably."""
    pnl_per_share = (current_price - pos.avg_entry_price) if pos.side is Side.BUY \
                    else (pos.avg_entry_price - current_price)
    if pnl_per_share < cfg.trailing_stop_activation_profit:
        return

    distance = cfg.trailing_stop_distance
    if pos.side is Side.BUY:
        candidate = current_price - distance
        if pos.trailing_stop_price is None or candidate > pos.trailing_stop_price:
            pos.trailing_stop_price = candidate
    else:
        candidate = current_price + distance
        if pos.trailing_stop_price is None or candidate < pos.trailing_stop_price:
            pos.trailing_stop_price = candidate
