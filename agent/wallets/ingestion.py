"""Wallet interaction ingestion.

Pulls `WalletAction`-shaped records from one or more `WalletDataSource`
implementations and bulk-loads them into the database. Designed to scale
to >=1M rows by:

  - streaming sources (async generators, never load all rows into memory),
  - batched inserts (default 5000/batch),
  - per-batch commit so a crash mid-ingest leaves a consistent partial state.

Sources:
  - `CSVWalletSource`: read local CSV files. Used in tests and as a way
    to ingest historical Polymarket exports from Dune/Goldsky.
  - `SyntheticWalletSource`: generate plausible interactions on demand.
    Used in load testing — `python -m agent.wallets.ingestion --synthetic 1000000`.

Add `DuneWalletSource`, `SubgraphWalletSource`, etc. by implementing the
async-iterator protocol below.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator, Protocol

from ..connectors.wallets import WalletAction
from ..logging_setup import get_logger
from ..storage.database import Database
from ..storage.models import WalletActionRow

log = get_logger(__name__)


@dataclass
class IngestStats:
    rows_inserted: int = 0
    rows_skipped: int = 0
    batches: int = 0
    elapsed_s: float = 0.0


class WalletDataSource(Protocol):
    """Streaming source of WalletAction records."""
    def stream(self) -> AsyncIterator[WalletAction]: ...


# ---------------------------------------------------------------------------
# CSV source
# ---------------------------------------------------------------------------

class CSVWalletSource:
    """Read WalletAction rows from a CSV. Columns required:
       wallet,market_id,token_id,tx_hash,side,size_usd,price,ts

    `ts` is ISO-8601. Lines failing to parse are skipped with a warning.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    async def stream(self) -> AsyncIterator[WalletAction]:
        # CSV reading is sync and fast; we yield to the event loop
        # periodically to keep the rest of the app responsive.
        with self.path.open("r", newline="") as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                try:
                    # DictReader returns None for missing fields, not KeyError.
                    ts_raw = row.get("ts")
                    if not ts_raw:
                        log.warning("ingest.csv_row_skipped", error="missing ts")
                        continue
                    ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    yield WalletAction(
                        wallet=row["wallet"],
                        market_id=row["market_id"],
                        token_id=row["token_id"],
                        side=row["side"].upper(),
                        size_usd=float(row["size_usd"]),
                        price=float(row["price"]),
                        timestamp=ts,
                    )
                except (KeyError, ValueError, TypeError, AttributeError) as e:
                    log.warning("ingest.csv_row_skipped", error=str(e))
                count += 1
                if count % 1000 == 0:
                    await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Synthetic source — generates plausible volume for load tests
# ---------------------------------------------------------------------------

class SyntheticWalletSource:
    """Generate `n_actions` realistic-looking actions across `n_wallets`
    wallets and `n_markets` markets. Distribution is intentionally skewed:
    a small fraction of wallets get the bulk of volume, a few are very
    skilled. Useful to stress-test the ingestion + scoring pipeline."""

    def __init__(
        self,
        n_actions: int = 1_000_000,
        n_wallets: int = 5_000,
        n_markets: int = 200,
        seed: int = 42,
    ):
        self.n_actions = n_actions
        self.n_wallets = n_wallets
        self.n_markets = n_markets
        self._rng = random.Random(seed)

    async def stream(self) -> AsyncIterator[WalletAction]:
        # Pre-pick a small subset of "skilled" and "whale" wallets so the
        # downstream scorer has interesting structure to find.
        skilled = set(self._rng.sample(range(self.n_wallets), k=self.n_wallets // 50))
        whales = set(self._rng.sample(range(self.n_wallets), k=self.n_wallets // 100))

        now = datetime.now(timezone.utc)
        for i in range(self.n_actions):
            w_idx = self._rng.randrange(self.n_wallets)
            m_idx = self._rng.randrange(self.n_markets)
            side = "BUY" if self._rng.random() < 0.55 else "SELL"
            base_size = 5_000 if w_idx in whales else 50
            size = base_size * (0.5 + self._rng.random() * 1.5)
            price = round(0.05 + self._rng.random() * 0.9, 3)
            ts = now - timedelta(minutes=self._rng.randint(0, 60 * 24 * 60))
            yield WalletAction(
                wallet=f"0x{w_idx:08x}",
                market_id=f"m{m_idx:04d}",
                token_id=f"m{m_idx:04d}-yes" if self._rng.random() < 0.5 else f"m{m_idx:04d}-no",
                side=side,
                size_usd=round(size, 2),
                price=price,
                timestamp=ts,
                skill=0.85 if w_idx in skilled else 0.5,
            )
            if i % 5000 == 0:
                await asyncio.sleep(0)   # cooperative yield


# ---------------------------------------------------------------------------
# Ingestor — generic, takes any source
# ---------------------------------------------------------------------------

class WalletIngestor:
    def __init__(self, db: Database, batch_size: int = 5_000):
        self.db = db
        self.batch_size = batch_size

    async def ingest(self, source: WalletDataSource) -> IngestStats:
        await self.db.init()
        stats = IngestStats()
        start = datetime.now(timezone.utc)
        batch: list[WalletActionRow] = []

        async for action in source.stream():
            batch.append(self._to_row(action))
            if len(batch) >= self.batch_size:
                inserted = await self._flush(batch)
                stats.rows_inserted += inserted
                stats.rows_skipped += len(batch) - inserted
                stats.batches += 1
                batch = []

        if batch:
            inserted = await self._flush(batch)
            stats.rows_inserted += inserted
            stats.rows_skipped += len(batch) - inserted
            stats.batches += 1

        stats.elapsed_s = (datetime.now(timezone.utc) - start).total_seconds()
        log.info("ingest.done",
                 rows=stats.rows_inserted, skipped=stats.rows_skipped,
                 batches=stats.batches, elapsed_s=round(stats.elapsed_s, 2))
        return stats

    @staticmethod
    def _to_row(a: WalletAction) -> WalletActionRow:
        # Synthesize a deterministic tx hash if missing — real data sources
        # provide one; the synthetic source doesn't bother.
        tx_hash = f"{a.wallet}:{a.market_id}:{a.timestamp.timestamp():.0f}:{a.side}"
        return WalletActionRow(
            wallet=a.wallet,
            market_id=a.market_id,
            token_id=a.token_id,
            tx_hash=tx_hash[:80],
            side=a.side,
            size_usd=a.size_usd,
            price=a.price,
            ts=a.timestamp,
        )

    async def _flush(self, rows: list[WalletActionRow]) -> int:
        async with self.db.session() as s:  # type: AsyncSession
            s.add_all(rows)
            try:
                await s.commit()
            except Exception as e:
                log.error("ingest.flush_failed", error=str(e), batch_size=len(rows))
                await s.rollback()
                return 0
        return len(rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Bulk-load wallet interactions.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", type=str, help="Path to CSV file with wallet actions.")
    src.add_argument("--synthetic", type=int,
                     help="Generate N synthetic actions (e.g. 1000000).")
    p.add_argument("--db", type=str, default="sqlite+aiosqlite:///./data/polyagent.db")
    p.add_argument("--batch-size", type=int, default=5000)
    return p


async def _main(args: argparse.Namespace) -> int:
    db = Database(args.db)
    if args.csv:
        source: WalletDataSource = CSVWalletSource(args.csv)
    else:
        source = SyntheticWalletSource(n_actions=args.synthetic)
    ingestor = WalletIngestor(db, batch_size=args.batch_size)
    stats = await ingestor.ingest(source)
    print(f"Ingested {stats.rows_inserted:,} rows in {stats.elapsed_s:.1f}s "
          f"({stats.rows_inserted / max(0.001, stats.elapsed_s):,.0f} rows/sec)")
    await db.close()
    return 0


if __name__ == "__main__":
    args = _build_argparser().parse_args()
    raise SystemExit(asyncio.run(_main(args)))
