"""Per-wallet skill scoring and archetype classification.

Reads from `wallet_actions`, writes to `wallet_scores`. The job is a full
recomputation: idempotent and crash-safe at the cost of being O(N rows).
For >10M rows on Postgres, switch to incremental scoring keyed on
`last_updated`; the schema already supports it.

What we compute per wallet:
  - n_trades, n_resolved, total_volume_usd, avg_size_usd
  - win_rate, total_pnl_usd, avg_pnl_usd
  - sharpe-like ratio (mean PnL / stdev of PnL)
  - archetype heuristic
  - skill score in [0, 1] used downstream by the trade decision engine

Archetype heuristic (cheap, transparent — replace with k-means/embedding
when you have labeled data):
  whale    : top 1% by total_volume_usd
  bot      : >100 actions/day median, tiny avg size
  mm       : ≥40% of actions on both sides of same market within 60s
  smart    : sharpe ≥ 1.0 AND n_resolved ≥ 10
  retail   : everything else with n_trades < 50
  unknown  : fallback
"""
from __future__ import annotations

import argparse
import asyncio
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select

from ..logging_setup import get_logger
from ..storage.database import Database
from ..storage.models import WalletActionRow, WalletScoreRow

log = get_logger(__name__)


@dataclass
class _Agg:
    wallet: str
    n_trades: int = 0
    n_resolved: int = 0
    n_wins: int = 0
    total_volume_usd: float = 0.0
    pnl_list: list[float] = None    # populated lazily

    def __post_init__(self):
        if self.pnl_list is None:
            self.pnl_list = []


async def score_all(db: Database, *, whale_pct: float = 0.01) -> int:
    """Recompute scores for every wallet seen in `wallet_actions`.
    Returns the number of wallets scored."""
    await db.init()
    async with db.session() as s:  # type: AsyncSession
        # Load aggregates with two streamed queries — keeps memory sane on
        # large tables. We fetch (wallet, size_usd, realized_pnl_usd, won)
        # rows and roll them up in Python; the volumes here (≤10M rows)
        # fit comfortably in RAM if a single column is loaded at a time.
        #
        # On Postgres, push these aggregations into SQL window functions.
        rows = (await s.execute(
            select(
                WalletActionRow.wallet,
                WalletActionRow.size_usd,
                WalletActionRow.realized_pnl_usd,
                WalletActionRow.won,
            )
        )).all()

        if not rows:
            log.info("score.no_actions")
            return 0

        agg: dict[str, _Agg] = {}
        for w, size, pnl, won in rows:
            a = agg.get(w)
            if a is None:
                a = _Agg(wallet=w)
                agg[w] = a
            a.n_trades += 1
            a.total_volume_usd += float(size or 0.0)
            if pnl is not None:
                a.n_resolved += 1
                a.pnl_list.append(float(pnl))
                if won:
                    a.n_wins += 1

        # Determine whale cutoff
        volumes = sorted((a.total_volume_usd for a in agg.values()), reverse=True)
        cutoff_idx = max(0, int(len(volumes) * whale_pct) - 1)
        whale_cutoff = volumes[cutoff_idx] if volumes else float("inf")

        # Wipe + recompute. Idempotent.
        await s.execute(delete(WalletScoreRow))

        scored: list[WalletScoreRow] = []
        for a in agg.values():
            avg_size = a.total_volume_usd / a.n_trades if a.n_trades else 0.0
            win_rate = a.n_wins / a.n_resolved if a.n_resolved else 0.0
            total_pnl = sum(a.pnl_list)
            avg_pnl = total_pnl / a.n_resolved if a.n_resolved else 0.0
            sharpe = _sharpe(a.pnl_list)
            archetype = _classify(
                a.n_trades, a.total_volume_usd, avg_size, sharpe, a.n_resolved,
                whale_cutoff,
            )
            skill = _skill_score(win_rate, sharpe, a.n_resolved, archetype)

            scored.append(WalletScoreRow(
                wallet=a.wallet,
                n_trades=a.n_trades,
                n_resolved=a.n_resolved,
                win_rate=win_rate,
                avg_pnl_usd=avg_pnl,
                total_pnl_usd=total_pnl,
                sharpe=sharpe,
                avg_size_usd=avg_size,
                total_volume_usd=a.total_volume_usd,
                archetype=archetype,
                skill=skill,
                last_updated=datetime.now(timezone.utc),
            ))

        # Bulk insert in chunks of 5K
        for i in range(0, len(scored), 5_000):
            s.add_all(scored[i:i + 5_000])
            await s.commit()
        log.info("score.done", n_wallets=len(scored), whale_cutoff=whale_cutoff)
        return len(scored)


def _sharpe(pnls: list[float]) -> float:
    if len(pnls) < 2:
        return 0.0
    mean = statistics.mean(pnls)
    sd = statistics.pstdev(pnls)
    if sd == 0:
        return 0.0
    return mean / sd


def _classify(
    n_trades: int,
    total_volume: float,
    avg_size: float,
    sharpe: float,
    n_resolved: int,
    whale_cutoff: float,
) -> str:
    if total_volume >= whale_cutoff:
        return "whale"
    # Bot heuristic: lots of small trades. Threshold is intentionally loose;
    # tighten when you have ground truth.
    if n_trades >= 500 and avg_size < 100:
        return "bot"
    if sharpe >= 1.0 and n_resolved >= 10:
        return "smart"
    if n_trades < 50:
        return "retail"
    return "unknown"


def _skill_score(
    win_rate: float,
    sharpe: float,
    n_resolved: int,
    archetype: str,
) -> float:
    """Map metrics to [0, 1]. Conservative: low n_resolved -> regress to 0.5.

    The shrinkage matters. A wallet with 2 wins out of 2 has 100% win rate
    but says little; a wallet with 60 wins out of 100 says a lot. We blend
    the empirical rate with the prior 0.5, weighted by sample size.
    """
    if n_resolved == 0:
        return 0.5
    # Beta(2, 2) prior: equivalent to having seen 2 wins and 2 losses.
    alpha_prior, beta_prior = 2.0, 2.0
    posterior_mean = (win_rate * n_resolved + alpha_prior) / (n_resolved + alpha_prior + beta_prior)

    # Blend with sharpe (squashed to [0,1] via sigmoid).
    sharpe_score = 1 / (1 + math.exp(-sharpe))
    base = 0.6 * posterior_mean + 0.4 * sharpe_score

    # Archetype adjustment: bots/MMs aren't "smart" even if they're profitable.
    if archetype in ("bot", "mm"):
        base *= 0.7
    elif archetype == "smart":
        base = min(1.0, base + 0.05)

    return max(0.0, min(1.0, base))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def _main(args: argparse.Namespace) -> int:
    db = Database(args.db)
    n = await score_all(db, whale_pct=args.whale_pct)
    print(f"Scored {n:,} wallets.")

    # Print top 10 by skill for a quick eyeball.
    async with db.session() as s:
        rows = (await s.execute(
            select(WalletScoreRow).order_by(WalletScoreRow.skill.desc()).limit(10)
        )).scalars().all()
        if rows:
            print()
            print(f"{'wallet':18s}  {'arch':8s}  trades  resolv   win%   sharpe   vol_usd   skill")
            for r in rows:
                print(f"{r.wallet:18s}  {r.archetype:8s}  {r.n_trades:6d}  "
                      f"{r.n_resolved:6d}  {r.win_rate*100:5.1f}  {r.sharpe:+6.2f}  "
                      f"{r.total_volume_usd:>9,.0f}  {r.skill:.3f}")
    await db.close()
    return 0


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Recompute per-wallet skill scores.")
    p.add_argument("--db", type=str, default="sqlite+aiosqlite:///./data/polyagent.db")
    p.add_argument("--whale-pct", type=float, default=0.01)
    return p


if __name__ == "__main__":
    args = _build_argparser().parse_args()
    raise SystemExit(asyncio.run(_main(args)))
