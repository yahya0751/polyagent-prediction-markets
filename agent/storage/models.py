"""SQLAlchemy models.

SQLite by default for the MVP. Schema is plain enough to run on
Postgres without changes; add a migration story when you do.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class OrderRow(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(64), index=True)
    market_id: Mapped[str] = mapped_column(String(96), index=True)
    token_id: Mapped[str] = mapped_column(String(96), index=True)
    side: Mapped[str] = mapped_column(String(8))
    price: Mapped[float] = mapped_column(Float)
    size: Mapped[float] = mapped_column(Float)
    filled: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16))
    placed_at: Mapped[datetime] = mapped_column(DateTime)
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True)


class PositionRow(Base):
    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String(96), index=True)
    token_id: Mapped[str] = mapped_column(String(96), index=True)
    side: Mapped[str] = mapped_column(String(8))
    avg_entry_price: Mapped[float] = mapped_column(Float)
    size: Mapped[float] = mapped_column(Float)
    realized_pnl_usd: Mapped[float] = mapped_column(Float, default=0.0)
    opened_at: Mapped[datetime] = mapped_column(DateTime)
    last_update: Mapped[datetime] = mapped_column(DateTime)
    thesis: Mapped[str] = mapped_column(Text, default="")
    stop_loss_price: Mapped[float] = mapped_column(Float, default=0.0)
    trailing_stop_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class DecisionRow(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    market_id: Mapped[str] = mapped_column(String(96), index=True)
    side: Mapped[str] = mapped_column(String(8))
    decision: Mapped[str] = mapped_column(String(16))
    score: Mapped[float] = mapped_column(Float)
    estimated_prob: Mapped[float] = mapped_column(Float)
    market_implied: Mapped[float] = mapped_column(Float)
    edge: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    reasons: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[str] = mapped_column(Text, default="")


class WalletActionRow(Base):
    """One row per observed wallet interaction. Designed to scale: indexes
    are on (wallet) and (market_id, ts) since most queries filter on either.
    For >1M rows on Postgres, partition by month on `ts`. Schema is
    intentionally flat to keep ingestion cheap and analytical queries simple.
    """
    __tablename__ = "wallet_actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet: Mapped[str] = mapped_column(String(64), index=True)
    market_id: Mapped[str] = mapped_column(String(96), index=True)
    token_id: Mapped[str] = mapped_column(String(96), index=True)
    tx_hash: Mapped[str] = mapped_column(String(80), index=True)
    side: Mapped[str] = mapped_column(String(8))   # BUY / SELL
    size_usd: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    # Resolved-market enrichment (filled by scoring job after market closes)
    realized_pnl_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    holding_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    won: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)


class WalletScoreRow(Base):
    """Per-wallet aggregated skill metrics. Recomputed by the scoring job
    rather than maintained transactionally — rebuilds are idempotent and
    cheap for ≤10M rows on a single SQLite file."""
    __tablename__ = "wallet_scores"
    wallet: Mapped[str] = mapped_column(String(64), primary_key=True)
    n_trades: Mapped[int] = mapped_column(Integer, default=0)
    n_resolved: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0)
    avg_pnl_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_pnl_usd: Mapped[float] = mapped_column(Float, default=0.0)
    sharpe: Mapped[float] = mapped_column(Float, default=0.0)
    avg_size_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_volume_usd: Mapped[float] = mapped_column(Float, default=0.0)
    # Heuristic classification: smart | whale | bot | mm | retail | unknown
    archetype: Mapped[str] = mapped_column(String(16), default="unknown")
    # 0..1 normalized skill score used by the trade decision engine
    skill: Mapped[float] = mapped_column(Float, default=0.5, index=True)
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
