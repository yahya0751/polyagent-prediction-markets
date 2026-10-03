"""Abstract connector interface.

The whole point: Polymarket is *one* connector. Adding Kalshi, Manifold,
or anything else is implementing this interface — no engine code changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..types import Market, Order, OrderBook, Side


class BaseConnector(ABC):
    name: str = "base"

    # ---------- Market data ----------
    @abstractmethod
    async def list_markets(self, limit: int = 100) -> list[Market]: ...

    @abstractmethod
    async def get_market(self, market_id: str) -> Optional[Market]: ...

    @abstractmethod
    async def get_order_book(self, token_id: str) -> Optional[OrderBook]: ...

    # ---------- Trading ----------
    @abstractmethod
    async def place_limit_order(
        self,
        market_id: str,
        token_id: str,
        side: Side,
        price: float,
        size: float,
    ) -> Order: ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool: ...

    @abstractmethod
    async def list_open_orders(self) -> list[Order]: ...

    # ---------- Lifecycle ----------
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    @property
    def supports_live_trading(self) -> bool:
        return False
