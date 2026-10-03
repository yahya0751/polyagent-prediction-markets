"""Fixture news items for --demo mode.

Mirrors what the agent would see if NewsAPI returned recent Reuters/AP
coverage of the same events the SyntheticConnector exposes. Used only
when no live news API key is configured AND we're in demo mode.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .news import NewsItem


def _fresh(hours_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours_ago)


def _freshness(hours_ago: int) -> float:
    return max(0.0, 1.0 - hours_ago / (7 * 24))


def build_demo_news_fixtures() -> dict[str, list[NewsItem]]:
    """Keyword → list of NewsItem. The runner calls news.search(market.question);
    keywords here are substrings expected to appear in a fixture market question."""
    return {
        "Fed cut rates": [
            NewsItem(
                title="Fed officials signal tilt toward December rate cut",
                description="Two voting members said data supports a 25bp move.",
                source="reuters",
                url="https://example.com/reuters/fed-tilt",
                published_at=_fresh(6),
                freshness=_freshness(6),
                credibility=0.95,
            ),
            NewsItem(
                title="Inflation print comes in below consensus, futures price in cut",
                description="Core PCE softer than expected; CME FedWatch shifts.",
                source="bloomberg",
                url="https://example.com/bloomberg/cpi",
                published_at=_fresh(20),
                freshness=_freshness(20),
                credibility=0.90,
            ),
            NewsItem(
                title="Treasuries rally on dovish Fedspeak",
                description="2Y yields drop 8bp.",
                source="ft",
                url="https://example.com/ft/treasuries",
                published_at=_fresh(30),
                freshness=_freshness(30),
                credibility=0.90,
            ),
        ],
        "ETH close above": [
            NewsItem(
                title="ETH selloff accelerates as ETF flows turn negative",
                description="Net outflows for the third straight week.",
                source="reuters",
                url="https://example.com/reuters/eth-outflows",
                published_at=_fresh(5),
                freshness=_freshness(5),
                credibility=0.95,
            ),
            NewsItem(
                title="Major holder moves 50K ETH to exchange",
                description="On-chain trackers flag a likely sell-side flow.",
                source="coindesk",
                url="https://example.com/coindesk/whale",
                published_at=_fresh(12),
                freshness=_freshness(12),
                credibility=0.65,
            ),
            NewsItem(
                title="Risk assets retreat as macro tightens",
                description="Crypto follows equities lower.",
                source="bloomberg",
                url="https://example.com/bloomberg/risk-off",
                published_at=_fresh(28),
                freshness=_freshness(28),
                credibility=0.90,
            ),
        ],
        "incumbent party": [
            NewsItem(
                title="Generic-ballot polling tightens further this week",
                description="Aggregator shows R+1.2 from R+0.5.",
                source="the new york times",
                url="https://example.com/nyt/poll",
                published_at=_fresh(40),
                freshness=_freshness(40),
                credibility=0.85,
            ),
        ],
    }
