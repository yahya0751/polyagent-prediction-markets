"""Social sentiment connector — stub.

Real implementation should:
  * Pull from authorized APIs (X/Twitter Enterprise, Reddit OAuth, etc.)
  * Use a lightweight classifier to label each post as informational /
    hype / panic / bot / coordinated
  * Down-weight bot- and coordination-suspect content heavily

Until configured, returns neutral. Sentiment is an *input*, not a
trigger; engine treats absence of signal as 0.0 contribution.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SentimentSnapshot:
    score: float          # [-1, 1]
    confidence: float     # [0, 1]
    informational: float  # share of posts judged informational, 0..1
    hype: float
    panic: float
    bot_suspect: float


def neutral() -> SentimentSnapshot:
    return SentimentSnapshot(
        score=0.0, confidence=0.0,
        informational=0.0, hype=0.0, panic=0.0, bot_suspect=0.0,
    )


class SocialConnector:
    """Placeholder. Wire to the API of your choice."""
    async def snapshot(self, query: str) -> SentimentSnapshot:
        return neutral()

    async def stop(self) -> None:
        return None
