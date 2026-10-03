"""Async DB session factory."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..types import TradeOpportunity
from .models import Base, DecisionRow


class Database:
    def __init__(self, url: str):
        self.url = url
        # Make sure the parent dir exists for sqlite URLs
        if url.startswith("sqlite"):
            db_path = url.split("///", 1)[-1]
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_async_engine(url, echo=False, future=True)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def init(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()

    def session(self) -> AsyncSession:
        return self.session_factory()

    async def log_decision(self, opp: TradeOpportunity) -> None:
        row = DecisionRow(
            ts=datetime.now(timezone.utc),
            market_id=opp.market.market_id,
            side=opp.side.value,
            decision=opp.decision.value,
            score=opp.score,
            estimated_prob=opp.probability.estimated_prob,
            market_implied=opp.probability.market_implied_prob,
            edge=opp.probability.edge,
            confidence=opp.probability.confidence,
            reasons=" | ".join(opp.reasons),
            payload_json=json.dumps({
                "question": opp.market.question,
                "outcome": opp.outcome.name,
                "spread": opp.spread,
                "slippage_pct": opp.slippage_pct,
                "max_fill_usd": opp.max_fill_usd,
                "liquidity_quality": opp.liquidity_quality,
                "resolution_clarity": opp.resolution_clarity,
                "source_credibility": opp.source_credibility,
                "wallet_signal": opp.wallet_signal,
                "catalyst_strength": opp.catalyst_strength,
                "manipulation_risk": opp.manipulation_risk,
                "correlation_risk": opp.correlation_risk,
            }, default=str),
        )
        async with self.session() as s:
            s.add(row)
            await s.commit()
