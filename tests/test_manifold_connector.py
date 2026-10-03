"""Tests for the Manifold connector — all offline.

Parsing is a pure static method tested directly; the async fetch path is
exercised with httpx.MockTransport so CI never touches the network.
"""
import json

import httpx
import pytest

from agent.connectors.manifold import ManifoldConnector
from agent.types import Market, OrderBook

# A realistic LiteMarket record from GET /v0/markets.
BINARY_MARKET = {
    "id": "abc123",
    "question": "Will X happen by 2027?",
    "slug": "will-x-happen-by-2027",
    "url": "https://manifold.markets/u/will-x-happen-by-2027",
    "outcomeType": "BINARY",
    "mechanism": "cpmm-1",
    "probability": 0.37,
    "volume": 15234.5,
    "volume24Hours": 1200.0,
    "totalLiquidity": 2500.0,
    "closeTime": 1800000000000,  # ms epoch, ~2027
    "isResolved": False,
    "groupSlugs": ["technology", "ai"],
}

MULTI_MARKET = {**BINARY_MARKET, "id": "multi1", "outcomeType": "MULTIPLE_CHOICE"}
RESOLVED_MARKET = {**BINARY_MARKET, "id": "res1", "isResolved": True}
BAD_PROB_MARKET = {**BINARY_MARKET, "id": "bad1", "probability": None}


def test_parse_binary_market():
    m = ManifoldConnector._parse_market(BINARY_MARKET)
    assert isinstance(m, Market)
    assert m.market_id == "abc123"
    assert m.category == "technology"
    assert m.resolution_source == "Manifold Markets"
    assert m.volume_usd == pytest.approx(15234.5)
    assert m.liquidity_usd == pytest.approx(2500.0)
    assert len(m.outcomes) == 2
    yes = next(o for o in m.outcomes if o.name == "Yes")
    no = next(o for o in m.outcomes if o.name == "No")
    assert yes.price == pytest.approx(0.37)
    assert no.price == pytest.approx(0.63)
    assert yes.token_id == "abc123:YES"
    assert no.token_id == "abc123:NO"
    assert m.close_time is not None and m.close_time.year == 2027


def test_parse_skips_non_binary_resolved_and_malformed():
    assert ManifoldConnector._parse_market(MULTI_MARKET) is None
    assert ManifoldConnector._parse_market(RESOLVED_MARKET) is None
    assert ManifoldConnector._parse_market(BAD_PROB_MARKET) is None
    assert ManifoldConnector._parse_market({}) is None
    assert ManifoldConnector._parse_market("not a dict") is None


def test_extract_text_handles_string_and_richtext():
    from agent.connectors.manifold import _extract_text

    assert _extract_text("plain rule") == "plain rule"
    doc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Resolves YES if"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "the event occurs."}]},
        ],
    }
    assert _extract_text(doc) == "Resolves YES if the event occurs."
    assert _extract_text(None) == ""


def test_derive_book_is_well_formed():
    book = ManifoldConnector._derive_book(mid=0.37, liquidity=2500.0, token_id="abc123:YES")
    assert isinstance(book, OrderBook)
    assert book.best_bid is not None and book.best_ask is not None
    assert book.best_bid < book.best_ask  # non-crossed
    assert book.spread is not None and book.spread > 0
    # mid of the derived book should sit near the market probability
    assert abs(book.mid - 0.37) < 0.02
    # levels sorted correctly
    assert book.bids == sorted(book.bids, key=lambda lv: -lv.price)
    assert book.asks == sorted(book.asks, key=lambda lv: lv.price)
    assert all(lv.size > 0 for lv in book.bids + book.asks)


def test_derive_book_clamps_extremes():
    # Very low liquidity → wide spread, still valid and non-crossing.
    book = ManifoldConnector._derive_book(mid=0.99, liquidity=10.0, token_id="x:YES")
    assert book.best_bid < book.best_ask
    assert all(0.0 < lv.price < 1.0 for lv in book.bids + book.asks)


@pytest.mark.asyncio
async def test_list_markets_end_to_end_offline():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v0/markets"
        payload = [BINARY_MARKET, MULTI_MARKET, RESOLVED_MARKET]
        return httpx.Response(200, content=json.dumps(payload))

    conn = ManifoldConnector(transport=httpx.MockTransport(handler))
    try:
        markets = await conn.list_markets(limit=50)
    finally:
        await conn.stop()

    # Only the single BINARY, unresolved market survives parsing.
    assert len(markets) == 1
    assert markets[0].market_id == "abc123"


def test_bets_to_series_orders_and_orients():
    # Manifold returns bets newest-first; probAfter is the YES probability.
    bets = [
        {"probAfter": 0.60, "createdTime": 3000},
        {"probAfter": 0.50, "createdTime": 2000},
        {"probAfter": 0.40, "createdTime": 1000},
    ]
    yes = ManifoldConnector._bets_to_series(bets, is_no=False, limit=150)
    assert [p.t for p in yes] == [1, 2, 3]  # oldest-first, ms→s
    assert [p.p for p in yes] == [0.4, 0.5, 0.6]

    no = ManifoldConnector._bets_to_series(bets, is_no=True, limit=150)
    assert [p.p for p in no] == [0.6, 0.5, 0.4]  # 1 - YES

    # Malformed bets are skipped, not fatal.
    assert ManifoldConnector._bets_to_series(
        [{"probAfter": None, "createdTime": 1}, {"createdTime": 2}], is_no=False, limit=150
    ) == []


@pytest.mark.asyncio
async def test_list_markets_survives_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"boom")

    conn = ManifoldConnector(transport=httpx.MockTransport(handler))
    try:
        markets = await conn.list_markets()
    finally:
        await conn.stop()
    assert markets == []
