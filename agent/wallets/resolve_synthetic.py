"""Backfill `realized_pnl_usd`, `won`, `holding_seconds` on wallet actions.

In production this is fed by market-resolution events from the platform.
This helper does the same job for synthetic data: pick a winning side per
market deterministically, compute PnL per action against that outcome,
and update rows in batches.
"""
from __future__ import annotations

import argparse
import asyncio
import random

from sqlalchemy import select

from ..logging_setup import get_logger
from ..storage.database import Database
from ..storage.models import WalletActionRow

log = get_logger(__name__)


async def resolve_synthetic_markets(db: Database, *, seed: int = 99) -> int:
    """For each distinct market_id present in `wallet_actions`, randomly
    pick a winning token (-yes or -no) and update every action on that
    market with realized_pnl_usd / won.

    Returns the number of actions updated."""
    await db.init()
    rng = random.Random(seed)
    async with db.session() as s:  # type: AsyncSession
        market_ids = (await s.execute(
            select(WalletActionRow.market_id).distinct()
        )).scalars().all()

        total = 0
        for mid in market_ids:
            winning_token = f"{mid}-yes" if rng.random() < 0.5 else f"{mid}-no"
            # PnL model: BUY of winning token wins (1 - price) * size_in_shares,
            # SELL of winning token loses (1 - price) * size_in_shares.
            # For losing token, BUY loses -price * size, SELL wins +price * size.
            # We approximate "size in shares" as size_usd / price.
            actions = (await s.execute(
                select(WalletActionRow).where(WalletActionRow.market_id == mid)
            )).scalars().all()

            for a in actions:
                if a.price <= 0:
                    continue
                shares = a.size_usd / a.price
                bought_winner = (a.token_id == winning_token and a.side == "BUY")
                bought_loser = (a.token_id != winning_token and a.side == "BUY")
                sold_winner = (a.token_id == winning_token and a.side == "SELL")
                sold_loser = (a.token_id != winning_token and a.side == "SELL")

                if bought_winner:
                    pnl = (1.0 - a.price) * shares
                    won = True
                elif bought_loser:
                    pnl = -a.price * shares
                    won = False
                elif sold_winner:
                    # Sold the winning token short: lose (1 - price) per share
                    pnl = -(1.0 - a.price) * shares
                    won = False
                elif sold_loser:
                    pnl = a.price * shares
                    won = True
                else:
                    continue

                a.realized_pnl_usd = round(pnl, 4)
                a.won = won
                total += 1

            await s.commit()
            log.info("resolve.market_done", market_id=mid, winning_token=winning_token,
                     actions=len(actions))
        return total


async def _main(args: argparse.Namespace) -> int:
    db = Database(args.db)
    n = await resolve_synthetic_markets(db, seed=args.seed)
    print(f"Resolved {n:,} actions.")
    await db.close()
    return 0


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Backfill realized PnL on wallet actions (synthetic resolution)."
    )
    p.add_argument("--db", type=str, default="sqlite+aiosqlite:///./data/polyagent.db")
    p.add_argument("--seed", type=int, default=99)
    return p


if __name__ == "__main__":
    args = _build_argparser().parse_args()
    raise SystemExit(asyncio.run(_main(args)))
