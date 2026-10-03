"""Offline tests for connector price-history support."""
import json

import httpx
import pytest

from agent.connectors.polymarket import PolymarketConnector
from agent.connectors.synthetic import SyntheticConnector
from agent.types import PricePoint


@pytest.mark.asyncio
async def test_polymarket_history_parses_and_sorts():
    payload = {"history": [
        {"t": 1790000000, "p": 0.21},
        {"t": 1790003600, "p": 0.23},
        {"t": 1789996400, "p": 0.19},  # out of order on purpose
    ]}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/prices-history"
        assert request.url.params.get("market") == "token-xyz"
        return httpx.Response(200, content=json.dumps(payload))

    conn = PolymarketConnector(transport=httpx.MockTransport(handler))
    try:
        pts = await conn.get_price_history("token-xyz", limit=150)
    finally:
        await conn.stop()

    assert all(isinstance(p, PricePoint) for p in pts)
    assert [p.t for p in pts] == sorted(p.t for p in pts)  # ascending
    assert pts[0].p == 0.19 and pts[-1].p == 0.23


@pytest.mark.asyncio
async def test_polymarket_history_survives_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"boom")

    conn = PolymarketConnector(transport=httpx.MockTransport(handler))
    try:
        assert await conn.get_price_history("t", limit=10) == []
    finally:
        await conn.stop()


@pytest.mark.asyncio
async def test_synthetic_history_anchored_to_current_price():
    conn = SyntheticConnector()
    markets = await conn.list_markets()
    m = markets[0]
    yes = next(o for o in m.outcomes if o.name == "Yes")
    pts = await conn.get_price_history(yes.token_id, limit=150)
    assert pts, "synthetic connector should produce a series"
    assert pts == sorted(pts, key=lambda p: p.t)
    # The most recent point is the real current price (anchored, not drifted).
    assert abs(pts[-1].p - yes.price) < 1e-6
    assert all(0.0 < p.p < 1.0 for p in pts)
