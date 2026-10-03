"""Order book analysis.

All functions take an OrderBook and return scalars. No I/O, no state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..types import OrderBook, Side


@dataclass
class BookAnalysis:
    spread: float
    mid: float
    best_bid: float
    best_ask: float
    bid_depth_usd: float
    ask_depth_usd: float
    # Estimated avg fill price for given trade size, on the relevant side
    estimated_fill_price: float
    slippage_pct: float          # (fill - mid) / mid in absolute terms
    max_fill_usd_at_target_slippage: float
    liquidity_quality: float     # [0, 1]
    manipulation_risk: float     # [0, 1]; "fake-looking" liquidity heuristic


def analyze(
    book: OrderBook,
    side: Side,
    target_size_usd: float,
    max_slippage_pct: float = 0.02,
) -> Optional[BookAnalysis]:
    if book.best_bid is None or book.best_ask is None:
        return None
    mid = book.mid or 0.5
    # Round to 4dp: prediction-market prices live on a 1c grid, so any
    # finer fluctuation is float noise, not real spread.
    spread = round(book.best_ask - book.best_bid, 4)

    # Cumulative depth in USD (price * size on each level)
    bid_depth_usd = sum(b.price * b.size for b in book.bids)
    ask_depth_usd = sum(a.price * a.size for a in book.asks)

    levels = book.asks if side is Side.BUY else book.bids
    cumulative_usd = 0.0
    cumulative_shares = 0.0
    avg_price = mid
    remaining_usd = target_size_usd
    for lvl in levels:
        level_usd = lvl.price * lvl.size
        if remaining_usd <= 0:
            break
        if level_usd >= remaining_usd:
            shares = remaining_usd / lvl.price
            cumulative_shares += shares
            cumulative_usd += remaining_usd
            remaining_usd = 0
        else:
            cumulative_shares += lvl.size
            cumulative_usd += level_usd
            remaining_usd -= level_usd
    if cumulative_shares > 0:
        avg_price = cumulative_usd / cumulative_shares

    # Slippage in price terms relative to mid (absolute)
    slip_abs = abs(avg_price - mid)
    slippage_pct = slip_abs / mid if mid > 0 else 1.0

    # Max size we could fill within the slippage budget. Walk levels
    # until the running average crosses (mid +/- mid * max_slippage_pct).
    target_price = mid + (mid * max_slippage_pct if side is Side.BUY else -mid * max_slippage_pct)
    running_usd = 0.0
    running_shares = 0.0
    max_fill_usd = 0.0
    for lvl in levels:
        if (side is Side.BUY and lvl.price > target_price) or \
           (side is Side.SELL and lvl.price < target_price):
            break
        running_shares += lvl.size
        running_usd += lvl.price * lvl.size
        if running_shares > 0:
            running_avg = running_usd / running_shares
            within_budget = (
                (side is Side.BUY and running_avg <= target_price) or
                (side is Side.SELL and running_avg >= target_price)
            )
            if within_budget:
                max_fill_usd = running_usd

    # Liquidity quality: combines spread tightness, depth, level count.
    # All three are bounded so the score stays in [0, 1].
    spread_score = max(0.0, 1.0 - spread / 0.05)         # tight if < 5c
    depth_score = min(1.0, (bid_depth_usd + ask_depth_usd) / 5000.0)
    level_score = min(1.0, (len(book.bids) + len(book.asks)) / 20.0)
    liquidity_quality = 0.5 * spread_score + 0.35 * depth_score + 0.15 * level_score

    # Manipulation risk: heuristic only. Flags books where almost all of
    # the depth sits at one level, or where the top-level size dwarfs
    # everything else by 10x. Cheap to compute, useful as a sanity check.
    manipulation_risk = 0.0
    same_side_levels = book.asks if side is Side.BUY else book.bids
    if same_side_levels:
        sizes = [lvl.size for lvl in same_side_levels]
        top = sizes[0]
        rest = sum(sizes[1:]) or 1e-9
        if top / rest > 10:
            manipulation_risk = max(manipulation_risk, 0.7)
        if len(same_side_levels) <= 2:
            manipulation_risk = max(manipulation_risk, 0.5)
    if spread > 0.10:
        manipulation_risk = max(manipulation_risk, 0.6)

    return BookAnalysis(
        spread=spread,
        mid=mid,
        best_bid=book.best_bid,
        best_ask=book.best_ask,
        bid_depth_usd=bid_depth_usd,
        ask_depth_usd=ask_depth_usd,
        estimated_fill_price=avg_price,
        slippage_pct=slippage_pct,
        max_fill_usd_at_target_slippage=max_fill_usd,
        liquidity_quality=max(0.0, min(1.0, liquidity_quality)),
        manipulation_risk=max(0.0, min(1.0, manipulation_risk)),
    )
