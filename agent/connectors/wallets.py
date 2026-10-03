"""Wallet connector.

This is a *stub* with the right shape. Real on-chain wallet intelligence
requires one of:

  * A Polygon archive node + decoded CTF Exchange events
  * A Dune/Goldsky/Subsquid subscription and an indexer
  * Polymarket's data API (if your account has access)

Engine code reads `WalletSignal` objects from this module — drop in any
of the above without touching engines.

What's implemented here today:
  * The data shape (WalletAction, WalletSignal)
  * `aggregate_signal` that computes a -1..+1 alignment score from a
    list of WalletAction objects, weighted by per-wallet skill score
  * A neutral default that downstream treats as "no signal"
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class WalletAction:
    wallet: str
    market_id: str
    token_id: str
    side: str            # "BUY" / "SELL"
    size_usd: float
    price: float
    timestamp: datetime
    # Pre-computed wallet skill score in [0, 1]. 0.5 if unknown.
    skill: float = 0.5


@dataclass
class WalletSignal:
    """Aggregated wallet intelligence for a single (market, side) pair."""
    market_id: str
    side: str            # which side this signal supports
    alignment: float     # [-1, 1]; +1 = strong smart-money buying this side
    smart_count: int     # # of distinct skilled wallets aligned
    total_volume_usd: float
    rationale: str = ""


class WalletDataProvider(Protocol):
    async def recent_actions(
        self, market_id: str, hours: int = 24
    ) -> list[WalletAction]: ...


class NoopWalletProvider:
    """Returns empty action lists. Used when wallets.enabled = false."""
    async def recent_actions(self, market_id: str, hours: int = 24) -> list[WalletAction]:
        return []


class SyntheticWalletProvider:
    """Demo provider: emits plausible-looking smart-money flow on a few
    pre-chosen markets so the demo has something to react to. Use only
    in --demo mode."""

    # Per-market: list of (side, n_skilled_wallets, avg_size_usd, skill)
    _PROFILES: dict[str, list[tuple[str, int, float, float]]] = {
        "0xfed24": [("BUY", 6, 800, 0.85), ("SELL", 1, 200, 0.55)],   # smart money on YES
        "0xeth01": [("SELL", 4, 600, 0.80), ("BUY", 1, 150, 0.50)],   # smart money against YES
    }

    async def recent_actions(self, market_id: str, hours: int = 24) -> list[WalletAction]:
        from datetime import datetime, timedelta, timezone
        profile = self._PROFILES.get(market_id)
        if not profile:
            return []
        out: list[WalletAction] = []
        now = datetime.now(timezone.utc)
        for side, n, size, skill in profile:
            for i in range(n):
                out.append(WalletAction(
                    wallet=f"0xsynth_{market_id}_{side}_{i}",
                    market_id=market_id,
                    token_id=f"{market_id}-yes",
                    side=side,
                    size_usd=size,
                    price=0.0,
                    timestamp=now - timedelta(hours=i),
                    skill=skill,
                ))
        return out


class DBWalletProvider:
    """Reads recent actions for a market from `wallet_actions`, joined with
    `wallet_scores.skill`. This is the production provider — pair it with
    the ingestion pipeline (`agent.wallets.ingestion`) and a periodic
    scoring job (`agent.wallets.scoring`).

    Args:
        db_url: SQLAlchemy URL. Same as the main agent DB.
        min_skill: filter out actions from wallets with skill below this
            threshold. Defaults to 0.0 (include everyone, weighted by skill).
    """

    def __init__(self, db_url: str, min_skill: float = 0.0):
        from ..storage.database import Database
        self._db = Database(db_url)
        self.min_skill = min_skill

    async def recent_actions(self, market_id: str, hours: int = 24) -> list[WalletAction]:
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import select

        from ..storage.models import WalletActionRow, WalletScoreRow
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        async with self._db.session() as s:
            # LEFT JOIN so unscored wallets default skill=0.5
            rows = (await s.execute(
                select(
                    WalletActionRow.wallet,
                    WalletActionRow.market_id,
                    WalletActionRow.token_id,
                    WalletActionRow.side,
                    WalletActionRow.size_usd,
                    WalletActionRow.price,
                    WalletActionRow.ts,
                    WalletScoreRow.skill,
                )
                .join(
                    WalletScoreRow,
                    WalletScoreRow.wallet == WalletActionRow.wallet,
                    isouter=True,
                )
                .where(WalletActionRow.market_id == market_id)
                .where(WalletActionRow.ts >= cutoff)
            )).all()
        out: list[WalletAction] = []
        for r in rows:
            skill = r.skill if r.skill is not None else 0.5
            if skill < self.min_skill:
                continue
            out.append(WalletAction(
                wallet=r.wallet, market_id=r.market_id, token_id=r.token_id,
                side=r.side, size_usd=r.size_usd, price=r.price,
                timestamp=r.ts, skill=skill,
            ))
        return out


def aggregate_signal(
    actions: list[WalletAction],
    side: str,
    smart_threshold: float = 0.7,
) -> WalletSignal:
    """Aggregate per-wallet actions into a signed alignment for the
    given side. We don't double-count the same wallet's same side."""
    if not actions:
        return WalletSignal(
            market_id="",
            side=side,
            alignment=0.0,
            smart_count=0,
            total_volume_usd=0.0,
            rationale="no wallet data",
        )

    # Combine same-wallet/same-side flows (net by signed volume)
    net: dict[tuple[str, str], float] = {}
    total_vol = 0.0
    for a in actions:
        key = (a.wallet, a.side)
        signed = a.size_usd * a.skill
        net[key] = net.get(key, 0.0) + signed
        total_vol += a.size_usd

    pos, neg = 0.0, 0.0
    smart_aligned = set()
    for (wallet, action_side), v in net.items():
        if action_side == side:
            pos += v
            # Skill check: any wallet whose at-least-one action met threshold
            if any(a.wallet == wallet and a.skill >= smart_threshold for a in actions):
                smart_aligned.add(wallet)
        else:
            neg += v

    denom = pos + neg
    alignment = 0.0 if denom == 0 else (pos - neg) / denom
    return WalletSignal(
        market_id=actions[0].market_id,
        side=side,
        alignment=alignment,
        smart_count=len(smart_aligned),
        total_volume_usd=total_vol,
        rationale=f"{len(smart_aligned)} skilled wallets aligned, "
                  f"alignment={alignment:+.2f}",
    )
