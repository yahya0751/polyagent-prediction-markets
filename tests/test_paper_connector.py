from datetime import datetime, timezone

import pytest

from agent.connectors.base import BaseConnector
from agent.connectors.paper import PaperConnector
from agent.types import OrderBook, OrderBookLevel, Side


class FakeConnector(BaseConnector):
    name = "fake"

    def __init__(self, book: OrderBook):
        self.book = book

    async def list_markets(self, limit=100):
        return []

    async def get_market(self, market_id):
        return None

    async def get_order_book(self, token_id):
        return self.book

    async def place_limit_order(self, market_id, token_id, side, price, size):
        raise NotImplementedError

    async def cancel_order(self, order_id):
        return False

    async def list_open_orders(self):
        return []


def _book():
    return OrderBook(
        token_id="t",
        bids=[OrderBookLevel(price=0.39, size=100), OrderBookLevel(price=0.38, size=200)],
        asks=[OrderBookLevel(price=0.40, size=100), OrderBookLevel(price=0.41, size=200)],
        timestamp=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_buy_fills_when_limit_crosses():
    pc = PaperConnector(FakeConnector(_book()))
    o = await pc.place_limit_order("m", "t", Side.BUY, price=0.40, size=50)
    assert o.filled == 50
    assert o.status == "filled"


@pytest.mark.asyncio
async def test_buy_does_not_fill_below_best_ask():
    pc = PaperConnector(FakeConnector(_book()))
    o = await pc.place_limit_order("m", "t", Side.BUY, price=0.39, size=50)
    assert o.filled == 0
    assert o.status == "open"


@pytest.mark.asyncio
async def test_partial_fill_walks_book():
    pc = PaperConnector(FakeConnector(_book()))
    o = await pc.place_limit_order("m", "t", Side.BUY, price=0.41, size=250)
    # Walks 100 @ 0.40 + 150 @ 0.41 (depth allows)
    assert o.filled == 250
    assert o.status == "filled"


@pytest.mark.asyncio
async def test_cancel_open_order():
    pc = PaperConnector(FakeConnector(_book()))
    o = await pc.place_limit_order("m", "t", Side.BUY, price=0.30, size=10)
    assert o.status == "open"
    ok = await pc.cancel_order(o.order_id)
    assert ok
    open_orders = await pc.list_open_orders()
    assert all(x.order_id != o.order_id for x in open_orders)
