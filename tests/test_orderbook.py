from datetime import datetime, timezone

from agent.core.orderbook import analyze
from agent.types import OrderBook, OrderBookLevel, Side


def _book(bids, asks):
    return OrderBook(
        token_id="t",
        bids=[OrderBookLevel(price=p, size=s) for p, s in bids],
        asks=[OrderBookLevel(price=p, size=s) for p, s in asks],
        timestamp=datetime.now(timezone.utc),
    )


def test_tight_book_high_liquidity_quality():
    book = _book(
        bids=[(0.49, 1000), (0.48, 1500), (0.47, 2000)],
        asks=[(0.50, 1000), (0.51, 1500), (0.52, 2000)],
    )
    a = analyze(book, Side.BUY, target_size_usd=200, max_slippage_pct=0.02)
    assert a is not None
    assert a.spread == 0.01
    assert a.liquidity_quality > 0.6
    assert a.manipulation_risk < 0.5


def test_wide_spread_flags_manipulation_risk():
    book = _book(
        bids=[(0.30, 100)],
        asks=[(0.70, 100)],
    )
    a = analyze(book, Side.BUY, target_size_usd=100, max_slippage_pct=0.02)
    assert a is not None
    assert a.spread == 0.40
    assert a.manipulation_risk >= 0.5


def test_thin_book_returns_low_max_fill():
    book = _book(
        bids=[(0.49, 5), (0.48, 5)],
        asks=[(0.50, 5), (0.51, 5)],
    )
    a = analyze(book, Side.BUY, target_size_usd=1000, max_slippage_pct=0.02)
    assert a is not None
    # Only ~$5 sits within 2% of mid, so max fill is small
    assert a.max_fill_usd_at_target_slippage < 10


def test_returns_none_for_empty_book():
    book = _book(bids=[], asks=[])
    assert analyze(book, Side.BUY, target_size_usd=100) is None
