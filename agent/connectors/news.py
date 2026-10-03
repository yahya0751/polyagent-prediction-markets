"""News connector.

If NEWSAPI_KEY is set, uses NewsAPI.org's /v2/everything endpoint to find
recent articles relevant to a market query. Otherwise returns an empty
list, which downstream is treated as a neutral catalyst signal.

For production, replace or augment with:
  - RSS pulls from official sources by category (gov.uk, SEC EDGAR, ESPN,
    AP, Reuters, central-bank press pages)
  - Per-category source credibility scores in config
  - LLM-based "is this news already priced in?" classifier

This file is the seam where you plug those in.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from ..logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class NewsItem:
    title: str
    description: str
    source: str
    url: str
    published_at: datetime
    # 0..1; how recent (1.0 = within last hour, 0.0 = older than 7 days)
    freshness: float
    # 0..1; how reliable the source is (configurable; default 0.5)
    credibility: float


class NewsConnector:
    def __init__(
        self,
        api_key: str = "",
        timeout_s: float = 10.0,
        source_credibility: Optional[dict[str, float]] = None,
        fixtures: Optional[dict[str, list["NewsItem"]]] = None,
    ):
        self._api_key = api_key
        self._client = httpx.AsyncClient(timeout=timeout_s)
        # Keyword -> list of fixture items, used in --demo / tests when no
        # NewsAPI key is available. Matched against the query substring.
        self._fixtures = fixtures or {}
        # Hand-curated baseline. Extend in config.
        self._cred = source_credibility or {
            "reuters": 0.95, "associated press": 0.95, "ap": 0.95,
            "bloomberg": 0.90, "ft": 0.90, "wsj": 0.85,
            "bbc": 0.85, "the guardian": 0.80,
            "the new york times": 0.85, "nytimes": 0.85,
            "espn": 0.85,  # for sports markets
            "coindesk": 0.65, "cointelegraph": 0.55,
        }

    async def stop(self) -> None:
        await self._client.aclose()

    async def search(self, query: str, hours: int = 48, limit: int = 20) -> list[NewsItem]:
        # Fixture path: used for offline demos and CI. Match by substring on
        # the query against keywords in the fixture map.
        if self._fixtures:
            q_lower = query.lower()
            for keyword, items in self._fixtures.items():
                if keyword.lower() in q_lower:
                    return items[:limit]
            # No match → fall through to live (which will return [] without a key)

        if not self._api_key:
            log.debug("news.disabled_no_key")
            return []
        params = {
            "q": query,
            "from": (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(),
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": min(limit, 100),
            "apiKey": self._api_key,
        }
        try:
            r = await self._client.get("https://newsapi.org/v2/everything", params=params)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.warning("news.fetch_failed", query=query, error=str(e))
            return []

        out: list[NewsItem] = []
        now = datetime.now(timezone.utc)
        for art in data.get("articles", [])[:limit]:
            try:
                pub = datetime.fromisoformat(art["publishedAt"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            age_h = max(0.0, (now - pub).total_seconds() / 3600.0)
            freshness = max(0.0, 1.0 - age_h / (7 * 24))
            source_name = (art.get("source") or {}).get("name", "").lower()
            credibility = self._cred.get(source_name, 0.5)
            out.append(NewsItem(
                title=art.get("title") or "",
                description=art.get("description") or "",
                source=source_name,
                url=art.get("url") or "",
                published_at=pub,
                freshness=freshness,
                credibility=credibility,
            ))
        return out

    @staticmethod
    def aggregate_signal(items: list[NewsItem]) -> tuple[float, float]:
        """Collapse items into (catalyst_strength, source_credibility)
        in [0, 1]. Both default to neutral 0.5 when no items."""
        if not items:
            return 0.5, 0.5
        # Weighted by freshness * credibility
        weights = [i.freshness * i.credibility for i in items]
        total_w = sum(weights)
        if total_w == 0:
            return 0.0, 0.5
        avg_cred = sum(i.credibility * w for i, w in zip(items, weights)) / total_w
        # Catalyst strength: cap at 1.0; many fresh credible items > one stale rumor.
        catalyst = min(1.0, total_w / 3.0)
        return catalyst, avg_cred
