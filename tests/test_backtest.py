"""Tests for the backtester."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent.config import load_settings
from agent.core.backtest import Backtester, HistoricalTick
from agent.types import Market, OrderBook, OrderBookLevel, Outcome


def _book(yes_price: float, depth: float = 200) -> OrderBook:
    half = 0.005
    return OrderBook(
        token_id="t",
        bids=[
            OrderBookLevel(price=round(yes_price - half, 4), size=depth),
            OrderBookLevel(price=round(yes_price - half - 0.01, 4), size=depth * 1.5),
        ],
        asks=[
            OrderBookLevel(price=round(yes_price + half, 4), size=depth),
            OrderBookLevel(price=round(yes_price + half + 0.01, 4), size=depth * 1.5),
        ],
        timestamp=datetime.now(timezone.utc),
    )


def _make_market(mid: float) -> Market:
    return Market(
        market_id="m1",
        slug="m1",
        question="Will it happen?",
        description="Test market with clear resolution per official source.",
        category="test",
        close_time=datetime.now(timezone.utc) + timedelta(days=30),
        resolution_source="official",
        rules_text="Test market with clear resolution per official source.",
        outcomes=[
            Outcome(token_id="m1-yes", name="Yes", price=mid),
            Outcome(token_id="m1-no", name="No", price=round(1 - mid, 2)),
        ],
        volume_usd=1_000_000,
        liquidity_usd=50_000,
        is_active=True,
        is_closed=False,
    )


def test_backtester_enters_on_strong_signal_and_settles_on_resolution():
    settings = load_settings("config.yaml")

    # Force a strong YES signal so the engine wants to enter
    def _signals(ts, market):
        return {
            "news_signal": +0.9,
            "wallet_signal": +0.8,
            "sentiment": +0.5,
            "resolution_clarity": 0.95,
            "source_credibility": 0.9,
            "catalyst_strength": 0.9,
        }

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    market = _make_market(mid=0.40)
    ticks = [
        HistoricalTick(
            ts=base + timedelta(hours=i),
            market=market,
            book_per_token={
                "m1-yes": _book(yes_price=0.40, depth=400),
                "m1-no": _book(yes_price=0.60, depth=400),
            },
        )
        for i in range(3)
    ]
    # Resolution tick: YES wins
    ticks.append(HistoricalTick(
        ts=base + timedelta(days=30),
        market=market,
        book_per_token={
            "m1-yes": _book(yes_price=0.99, depth=400),
            "m1-no": _book(yes_price=0.01, depth=400),
        },
        resolved_winning_token="m1-yes",
    ))

    bt = Backtester(settings)
    result = bt.run(ticks, signal_fn=_signals)

    assert result.n_decisions > 0
    assert result.n_enters >= 1, "Strong signal should trigger ENTER"
    assert result.n_exits >= 1, "Resolution tick should close all positions"
    # Bought YES at 0.40-ish, settled at 1.0 → strong positive PnL
    assert result.realized_pnl_usd > 0, f"Expected positive PnL, got {result.realized_pnl_usd}"
    # Win rate should be 100% since YES resolved winner
    assert result.win_rate == 1.0


def test_backtester_holds_off_on_weak_signal():
    settings = load_settings("config.yaml")

    # No signals → edge ≈ 0 → NO_TRADE
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    market = _make_market(mid=0.50)
    ticks = [HistoricalTick(
        ts=base, market=market,
        book_per_token={
            "m1-yes": _book(yes_price=0.50),
            "m1-no": _book(yes_price=0.50),
        },
    )]

    bt = Backtester(settings)
    result = bt.run(ticks, signal_fn=lambda ts, m: {})

    assert result.n_enters == 0, "No-signal market should never enter"
    assert result.realized_pnl_usd == 0.0
