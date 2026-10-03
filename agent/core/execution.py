"""Execution engine.

Wraps a connector with: limit-only by default, max chase ticks,
stale-order cancellation, and partial-fill tracking.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ..config import ExecutionCfg
from ..connectors.base import BaseConnector
from ..logging_setup import get_logger
from ..types import Order, Side

log = get_logger(__name__)


class ExecutionEngine:
    def __init__(self, connector: BaseConnector, cfg: ExecutionCfg):
        self.connector = connector
        self.cfg = cfg

    async def enter_limit(
        self,
        market_id: str,
        token_id: str,
        side: Side,
        price: float,
        size_shares: float,
        max_chase_price: float,
    ) -> Order:
        """Place a single limit order. Caller is responsible for any
        chase logic across multiple attempts."""
        # Sanity: never above max_chase_price
        if side is Side.BUY and price > max_chase_price:
            price = max_chase_price
        if side is Side.SELL and price < max_chase_price:
            price = max_chase_price
        # Round to tick
        tick = self.cfg.min_tick
        price = round(round(price / tick) * tick, 4)

        order = await self.connector.place_limit_order(
            market_id=market_id,
            token_id=token_id,
            side=side,
            price=price,
            size=size_shares,
        )
        log.info("exec.placed",
                 order_id=order.order_id, side=side.value,
                 price=price, size=size_shares, status=order.status)
        return order

    async def cancel_stale(self) -> int:
        """Cancel resting orders older than stale_order_seconds."""
        now = datetime.now(timezone.utc)
        cancelled = 0
        for o in await self.connector.list_open_orders():
            if o.status not in ("open", "partial"):
                continue
            age = (now - o.placed_at).total_seconds()
            if age >= self.cfg.stale_order_seconds:
                ok = await self.connector.cancel_order(o.order_id)
                if ok:
                    cancelled += 1
        if cancelled:
            log.info("exec.cancelled_stale", count=cancelled)
        return cancelled

    async def safe_chase(
        self,
        market_id: str,
        token_id: str,
        side: Side,
        current_book_top: float,
        max_chase_price: float,
        size_shares: float,
        existing_order: Optional[Order],
    ) -> Optional[Order]:
        """Reprice an existing order one tick more aggressively, but
        never beyond max_chase_price. Returns the new order if it
        repriced, None otherwise."""
        tick = self.cfg.min_tick
        if existing_order is None:
            return None
        if existing_order.status not in ("open", "partial"):
            return None

        if side is Side.BUY:
            new_price = min(existing_order.price + tick, max_chase_price)
            if new_price <= existing_order.price:
                return None
        else:
            new_price = max(existing_order.price - tick, max_chase_price)
            if new_price >= existing_order.price:
                return None

        # Cancel + replace
        await self.connector.cancel_order(existing_order.order_id)
        remaining = max(0.0, size_shares - existing_order.filled)
        if remaining <= 0:
            return None
        return await self.enter_limit(
            market_id=market_id,
            token_id=token_id,
            side=side,
            price=new_price,
            size_shares=remaining,
            max_chase_price=max_chase_price,
        )
