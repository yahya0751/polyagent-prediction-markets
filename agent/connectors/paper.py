"""Paper-trading connector.

Reads live market data from a wrapped real connector. All order placement
goes into an in-memory book that simulates fills against the real order
book at the time of placement. PnL marked-to-market against latest book.

This is the only connector used in MODE=PAPER_TRADING.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from ..logging_setup import get_logger
from ..types import Market, Order, OrderBook, Side
from .base import BaseConnector

log = get_logger(__name__)


class PaperConnector(BaseConnector):
    name = "paper"

    def __init__(self, data_source: BaseConnector):
        """data_source: a real connector used only for read endpoints."""
        self._src = data_source
        self._orders: dict[str, Order] = {}

    async def stop(self) -> None:
        await self._src.stop()

    async def list_markets(self, limit: int = 100) -> list[Market]:
        return await self._src.list_markets(limit=limit)

    async def get_market(self, market_id: str) -> Optional[Market]:
        return await self._src.get_market(market_id)

    async def get_order_book(self, token_id: str) -> Optional[OrderBook]:
        return await self._src.get_order_book(token_id)

    async def place_limit_order(
        self,
        market_id: str,
        token_id: str,
        side: Side,
        price: float,
        size: float,
    ) -> Order:
        # Simulate immediate partial fill against the live book if our limit
        # would cross. Anything not filled stays as a resting order.
        book = await self._src.get_order_book(token_id)
        filled = 0.0
        if book is not None:
            if side is Side.BUY:
                # Walk asks: any ask <= our limit fills.
                remaining = size
                for level in book.asks:
                    if level.price > price:
                        break
                    take = min(remaining, level.size)
                    filled += take
                    remaining -= take
                    if remaining <= 0:
                        break
            else:
                remaining = size
                for level in book.bids:
                    if level.price < price:
                        break
                    take = min(remaining, level.size)
                    filled += take
                    remaining -= take
                    if remaining <= 0:
                        break

        order_id = f"paper-{uuid.uuid4().hex[:12]}"
        status = "filled" if filled >= size else ("open" if filled == 0 else "partial")
        order = Order(
            order_id=order_id,
            market_id=market_id,
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            filled=filled,
            status=status,
            placed_at=datetime.now(timezone.utc),
            is_paper=True,
        )
        self._orders[order_id] = order
        log.info("paper.order_placed",
                 order_id=order_id, side=side.value, price=price,
                 size=size, filled=filled, status=status)
        return order

    async def cancel_order(self, order_id: str) -> bool:
        o = self._orders.get(order_id)
        if not o:
            return False
        if o.status in ("filled", "cancelled"):
            return False
        o.status = "cancelled"
        log.info("paper.order_cancelled", order_id=order_id)
        return True

    async def list_open_orders(self) -> list[Order]:
        return [o for o in self._orders.values() if o.status in ("open", "partial")]
