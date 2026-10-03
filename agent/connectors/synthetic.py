"""Synthetic connector — generates plausible markets and order books locally.

Use this when you want to demo the full agent loop without external network
access, or as a deterministic data source in CI. It implements only the
read paths (list_markets, get_market, get_order_book); trading methods
delegate to PaperConnector wrapping behavior.

Markets are a fixed roster with parameterized noise so the same agent
config produces the same decisions across runs (seedable).
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..types import Market, Order, OrderBook, OrderBookLevel, Outcome, PricePoint
from .base import BaseConnector
from .registry import register

# A small, hand-curated roster spanning categories. Designed so that at
# least one market is mispriced enough to pass the decision gate, so the
# demo actually shows an opportunity instead of a silent NO_TRADE.
_FIXTURES = [
    # (market_id, slug, question, category, yes_price, volume, liquidity, rules_clarity)
    ("0xelec24", "us-pres-2028-incumbent-party",
     "Will the incumbent party win the 2028 US Presidential election?",
     "politics", 0.42, 1_500_000, 80_000, "high"),
    ("0xfed24", "fed-rate-cut-dec",
     "Will the Fed cut rates by 25bp at the December meeting?",
     "macro", 0.62, 800_000, 40_000, "high"),
    ("0xnba01", "nba-finals-mvp",
     "Will Player X win NBA Finals MVP?",
     "sports", 0.18, 350_000, 12_000, "high"),
    ("0xeth01", "eth-above-5k-eoy",
     "Will ETH close above $5,000 on Dec 31?",
     "crypto", 0.27, 600_000, 25_000, "high"),
    ("0xthin01", "obscure-court-ruling",
     "Will a specific obscure court rule in favor by Q3?",
     "legal", 0.55, 8_000, 400, "medium"),
    ("0xambig01", "ambiguously-worded-event",
     "Will something maybe happen if conditions kind of align?",
     "other", 0.50, 50_000, 2_000, "low"),
]


# Hand-written resolution rules per clarity tier. The heuristic rule-reader
# scores on length, weasel-word density, and presence of named sources; these
# strings are written to the same standards a real well-specified Polymarket
# rule would meet.
_RULES_HIGH = (
    "This market resolves YES if and only if {q_clean}, as confirmed by the "
    "official statement from the {src_short}. Resolution data will be taken "
    "from the official website of the issuing body and cross-checked against "
    "results published by Reuters and the Associated Press. The deadline for "
    "resolution is the close timestamp specified above; any event occurring "
    "after the deadline does not count. The market resolves NO if the event "
    "does not occur by the deadline, or if the official source explicitly "
    "states the event did not occur. In the case of a delayed announcement, "
    "the published date in the official record governs, not the date the news "
    "is reported. There is no fallback to admin discretion: if the official "
    "source is silent past the deadline plus 14 days, the market resolves NO."
)
_RULES_MEDIUM = (
    "This market resolves YES if {q_clean} per the relevant court filing or "
    "press release, where possible cross-referenced against secondary "
    "reporting. The deadline is the market close time. If the official record "
    "is unclear, the resolver will consult the most authoritative public source."
)
_RULES_LOW = (
    "This market resolves YES if conditions are reasonably met, at the "
    "discretion of the resolver. Various sources may be considered. If not "
    "resolved by close, fallback to admin discretion."
)

_SOURCES = {
    "politics": "Federal Election Commission",
    "macro": "Federal Reserve Board",
    "sports": "the league office",
    "crypto": "Coinbase Pro spot index",
    "legal": "the issuing court",
    "other": "the resolver",
}


@register("synthetic")
class SyntheticConnector(BaseConnector):
    name = "synthetic"

    def __init__(self, seed: int = 7):
        self._rng = random.Random(seed)
        self._orders: dict[str, Order] = {}

    async def list_markets(self, limit: int = 100) -> list[Market]:
        out: list[Market] = []
        close = datetime.now(timezone.utc) + timedelta(days=60)
        for mid, slug, q, cat, yes, vol, liq, clarity in _FIXTURES[:limit]:
            yes_token = f"{mid}-yes"
            no_token = f"{mid}-no"
            src_short = _SOURCES.get(cat, "the official source")
            q_clean = q.rstrip("?").lower().replace("will ", "")
            template = (_RULES_HIGH if clarity == "high"
                        else _RULES_MEDIUM if clarity == "medium"
                        else _RULES_LOW)
            rules = template.format(q_clean=q_clean, src_short=src_short)
            out.append(Market(
                market_id=mid,
                slug=slug,
                question=q,
                description=rules,
                category=cat,
                close_time=close,
                resolution_source=src_short if clarity != "low" else "",
                rules_text=rules,
                outcomes=[
                    Outcome(token_id=yes_token, name="Yes", price=yes),
                    Outcome(token_id=no_token, name="No", price=round(1 - yes, 2)),
                ],
                volume_usd=float(vol),
                liquidity_usd=float(liq),
                is_active=True,
                is_closed=False,
            ))
        return out

    async def get_market(self, market_id: str) -> Optional[Market]:
        for m in await self.list_markets():
            if m.market_id == market_id:
                return m
        return None

    async def get_order_book(self, token_id: str) -> Optional[OrderBook]:
        # Look up the parent market to anchor mid price.
        market_id = token_id.rsplit("-", 1)[0]
        outcome_name = token_id.rsplit("-", 1)[1]   # 'yes' | 'no'
        m = await self.get_market(market_id)
        if m is None:
            return None
        outcome = next((o for o in m.outcomes if o.name.lower() == outcome_name), None)
        if outcome is None:
            return None
        mid = outcome.price

        # Build a 5-level book around mid, with depth scaled to liquidity.
        # Tight markets (high liq) get tight spreads + chunky levels.
        liq_scale = max(50.0, min(5000.0, m.liquidity_usd / 50.0))
        spread = 0.01 if m.liquidity_usd > 5_000 else 0.04
        # Random per-level depth, deterministic via seed.
        local_rng = random.Random(hash(token_id) & 0xFFFFFFFF)

        def _shares(base: float) -> float:
            return round(base * (0.6 + local_rng.random() * 0.8), 1)

        bids: list[OrderBookLevel] = []
        asks: list[OrderBookLevel] = []
        for i in range(5):
            bid_p = round(max(0.01, mid - spread / 2 - i * 0.01), 2)
            ask_p = round(min(0.99, mid + spread / 2 + i * 0.01), 2)
            bids.append(OrderBookLevel(price=bid_p, size=_shares(liq_scale / max(0.05, bid_p))))
            asks.append(OrderBookLevel(price=ask_p, size=_shares(liq_scale / max(0.05, ask_p))))

        return OrderBook(
            token_id=token_id,
            bids=bids,
            asks=asks,
            timestamp=datetime.now(timezone.utc),
        )

    async def get_price_history(self, token_id: str, *, limit: int = 150) -> list[PricePoint]:
        """Deterministic synthetic history anchored to the current price.

        The synthetic connector is explicitly a fabricated demo source, so a
        generated series is honest here (unlike live platforms, which must
        return real history).
        """
        market_id = token_id.rsplit("-", 1)[0]
        m = await self.get_market(market_id)
        if m is None:
            return []
        outcome = next(
            (o for o in m.outcomes if token_id.endswith(o.name.lower())), m.outcomes[0]
        )
        rng = random.Random(hash(token_id) & 0xFFFFFFFF)
        n = min(limit, 96)
        now = int(datetime.now(timezone.utc).timestamp())
        p = outcome.price
        pts: list[PricePoint] = []
        # Walk backwards from the real current price with mean reversion.
        for i in range(n):
            pts.append(PricePoint(t=now - (n - i) * 900, p=round(max(0.01, min(0.99, p)), 4)))
            p += (outcome.price - p) * 0.05 + rng.uniform(-0.01, 0.01)
        pts[-1] = PricePoint(t=now, p=round(outcome.price, 4))
        return pts

    # Trading methods are not used directly: PaperConnector wraps this and
    # provides simulated fills. We provide stubs to satisfy the interface.

    async def place_limit_order(self, *args, **kwargs) -> Order:  # pragma: no cover
        raise RuntimeError("SyntheticConnector is read-only. Wrap in PaperConnector.")

    async def cancel_order(self, order_id: str) -> bool:  # pragma: no cover
        return False

    async def list_open_orders(self) -> list[Order]:
        return []
