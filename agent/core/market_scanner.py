"""Market scanner.

Pulls active markets from the connector, filters out junk, and tags
markets with simple flags (thin, stale-reaction-suspect, fresh-mover).
The decision engine consumes this list one market at a time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from ..connectors.base import BaseConnector
from ..logging_setup import get_logger
from ..types import Market

log = get_logger(__name__)


@dataclass
class ScannedMarket:
    market: Market
    flags: set[str]
    notes: list[str]


def _passes_filters(m: Market) -> tuple[bool, Optional[str]]:
    if m.is_closed or not m.is_active:
        return False, "inactive"
    if not m.outcomes or len(m.outcomes) < 2:
        return False, "insufficient outcomes"
    if m.liquidity_usd < 50:
        return False, "trivially thin"
    if m.close_time is not None:
        # Skip markets resolving in < 10 minutes — execution risk too high
        delta = (m.close_time - datetime.now(timezone.utc)).total_seconds()
        if delta < 600:
            return False, "closing too soon"
    return True, None


class MarketScanner:
    def __init__(self, connector: BaseConnector, top_n: int = 50):
        self.connector = connector
        self.top_n = top_n

    async def scan(self) -> list[ScannedMarket]:
        raw = await self.connector.list_markets(limit=self.top_n)
        out: list[ScannedMarket] = []
        for m in raw:
            ok, why = _passes_filters(m)
            if not ok:
                log.debug("scanner.dropped", market_id=m.market_id, why=why)
                continue
            flags: set[str] = set()
            notes: list[str] = []
            if m.liquidity_usd < 200:
                flags.add("thin")
                notes.append(f"liquidity ${m.liquidity_usd:.0f}")
            if m.volume_usd > 0 and m.liquidity_usd / max(1.0, m.volume_usd) < 0.05:
                flags.add("high_turnover")
                notes.append("high turnover vs liquidity")
            out.append(ScannedMarket(market=m, flags=flags, notes=notes))
        log.info("scanner.scan_complete", kept=len(out), raw=len(raw))
        return out
