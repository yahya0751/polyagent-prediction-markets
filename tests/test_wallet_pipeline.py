"""Tests for wallet ingestion and scoring pipelines."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from agent.storage.database import Database
from agent.storage.models import WalletActionRow, WalletScoreRow
from agent.wallets.ingestion import CSVWalletSource, SyntheticWalletSource, WalletIngestor
from agent.wallets.scoring import score_all


@pytest.fixture
def tmp_db_url(tmp_path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path}/test.db"


@pytest.mark.asyncio
async def test_synthetic_ingestion_writes_rows(tmp_db_url):
    db = Database(tmp_db_url)
    src = SyntheticWalletSource(n_actions=500, n_wallets=20, n_markets=5, seed=1)
    ingestor = WalletIngestor(db, batch_size=100)
    stats = await ingestor.ingest(src)
    assert stats.rows_inserted == 500
    assert stats.batches == 5

    async with db.session() as s:
        n = (await s.execute(select(WalletActionRow))).scalars().all()
        assert len(n) == 500
    await db.close()


@pytest.mark.asyncio
async def test_csv_source_reads_well_formed_rows(tmp_path, tmp_db_url):
    csv_path = tmp_path / "wallets.csv"
    csv_path.write_text(
        "wallet,market_id,token_id,tx_hash,side,size_usd,price,ts\n"
        "0xabc,m1,m1-yes,h1,BUY,100,0.42,2026-01-01T00:00:00+00:00\n"
        "0xdef,m1,m1-no,h2,SELL,50,0.58,2026-01-01T01:00:00+00:00\n"
        "BAD-ROW-MISSING-FIELDS\n"
    )
    db = Database(tmp_db_url)
    stats = await WalletIngestor(db, batch_size=10).ingest(CSVWalletSource(csv_path))
    # The malformed row is silently skipped by DictReader (no fields set)
    assert stats.rows_inserted >= 2
    await db.close()


@pytest.mark.asyncio
async def test_scoring_assigns_higher_skill_to_winners(tmp_db_url):
    """Direct SQL writes: one always-winning wallet, one always-losing.
    Winner should score above losers after `score_all`."""
    db = Database(tmp_db_url)
    await db.init()
    now = datetime.now(timezone.utc)
    rows: list[WalletActionRow] = []
    # 30 winning trades for 0xWIN
    for i in range(30):
        rows.append(WalletActionRow(
            wallet="0xWIN", market_id=f"m{i:02d}", token_id=f"m{i:02d}-yes",
            tx_hash=f"hwin{i}", side="BUY", size_usd=100, price=0.4,
            ts=now - timedelta(hours=i),
            realized_pnl_usd=150.0, won=True,
        ))
    # 30 losing trades for 0xLOSE
    for i in range(30):
        rows.append(WalletActionRow(
            wallet="0xLOSE", market_id=f"m{i:02d}", token_id=f"m{i:02d}-no",
            tx_hash=f"hlose{i}", side="BUY", size_usd=100, price=0.6,
            ts=now - timedelta(hours=i),
            realized_pnl_usd=-60.0, won=False,
        ))
    async with db.session() as s:
        s.add_all(rows)
        await s.commit()

    n = await score_all(db)
    assert n == 2

    async with db.session() as s:
        win = (await s.execute(
            select(WalletScoreRow).where(WalletScoreRow.wallet == "0xWIN")
        )).scalar_one()
        lose = (await s.execute(
            select(WalletScoreRow).where(WalletScoreRow.wallet == "0xLOSE")
        )).scalar_one()
    assert win.skill > 0.7, f"Winner skill should be high; got {win.skill}"
    assert lose.skill < 0.3, f"Loser skill should be low; got {lose.skill}"
    assert win.win_rate == 1.0
    assert lose.win_rate == 0.0
    await db.close()
