"""Load .env + config.yaml into a single typed Settings object.

We split runtime tuning (config.yaml, committed) from secrets (.env,
not committed). One typed entry point so nothing in the codebase
reads os.environ directly.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from .types import Mode


class ComplianceCfg(BaseModel):
    allowed_jurisdictions: list[str]
    allowed_platforms: list[str]
    require_manual_approval: bool


class RiskCfg(BaseModel):
    bankroll_usd: float
    max_position_pct_bankroll: float
    max_category_exposure_pct: float
    max_correlated_exposure_pct: float
    max_daily_loss_pct: float
    max_drawdown_pct: float
    max_open_positions: int
    kelly_fraction: float
    min_position_usd: float
    hard_stop_loss_pct: float
    trailing_stop_activation_profit: float
    trailing_stop_distance: float
    partial_take_profit_levels: list[dict]


class DecisionCfg(BaseModel):
    min_edge: float
    min_confidence: float
    min_liquidity_usd: float
    max_spread: float
    max_slippage_pct: float
    min_resolution_clarity: float
    min_source_credibility: float
    min_trade_score: float
    weights: dict[str, float]


class ExecutionCfg(BaseModel):
    default_order_type: str
    max_chase_ticks: int
    stale_order_seconds: int
    min_tick: float


class ScannersCfg(BaseModel):
    market_scan_top_n: int
    unusual_volume_zscore: float
    stale_reaction_minutes: int


class WalletsCfg(BaseModel):
    enabled: bool
    min_trades_for_ranking: int
    smart_wallet_min_sharpe: float


class AgentCfg(BaseModel):
    loop_interval_seconds: int
    max_concurrent_scans: int


class LoggingCfg(BaseModel):
    jsonl_path: str


class Secrets(BaseModel):
    """Secrets and per-deployment env. Empty strings = unset."""
    mode: Mode = Mode.PAPER
    compliance_jurisdiction: str = ""
    compliance_tos_ack: str = ""
    polymarket_private_key: str = ""
    polymarket_funder_address: str = ""
    polymarket_api_key: str = ""
    polymarket_api_secret: str = ""
    polymarket_api_passphrase: str = ""
    newsapi_key: str = ""
    dune_api_key: str = ""
    database_url: str = "sqlite+aiosqlite:///./data/polyagent.db"
    clickhouse_url: str = ""
    kill_switch_file: str = "./data/KILL_SWITCH"
    log_level: str = "INFO"


class Settings(BaseModel):
    agent: AgentCfg
    compliance: ComplianceCfg
    risk: RiskCfg
    decision: DecisionCfg
    execution: ExecutionCfg
    scanners: ScannersCfg
    wallets: WalletsCfg
    logging: LoggingCfg
    secrets: Secrets = Field(default_factory=Secrets)


def _coerce_mode(raw: str) -> Mode:
    try:
        return Mode(raw)
    except ValueError:
        return Mode.PAPER


def load_settings(config_path: str | Path = "config.yaml") -> Settings:
    load_dotenv(override=False)

    with open(config_path, "r", encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)

    secrets = Secrets(
        mode=_coerce_mode(os.getenv("MODE", "PAPER_TRADING")),
        compliance_jurisdiction=os.getenv("COMPLIANCE_JURISDICTION", "").strip(),
        compliance_tos_ack=os.getenv("COMPLIANCE_TOS_ACK", "").strip(),
        polymarket_private_key=os.getenv("POLYMARKET_PRIVATE_KEY", ""),
        polymarket_funder_address=os.getenv("POLYMARKET_FUNDER_ADDRESS", ""),
        polymarket_api_key=os.getenv("POLYMARKET_API_KEY", ""),
        polymarket_api_secret=os.getenv("POLYMARKET_API_SECRET", ""),
        polymarket_api_passphrase=os.getenv("POLYMARKET_API_PASSPHRASE", ""),
        newsapi_key=os.getenv("NEWSAPI_KEY", ""),
        dune_api_key=os.getenv("DUNE_API_KEY", ""),
        database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/polyagent.db"),
        clickhouse_url=os.getenv("CLICKHOUSE_URL", ""),
        kill_switch_file=os.getenv("KILL_SWITCH_FILE", "./data/KILL_SWITCH"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )

    return Settings(
        agent=AgentCfg(**data["agent"]),
        compliance=ComplianceCfg(**data["compliance"]),
        risk=RiskCfg(**data["risk"]),
        decision=DecisionCfg(**data["decision"]),
        execution=ExecutionCfg(**data["execution"]),
        scanners=ScannersCfg(**data["scanners"]),
        wallets=WalletsCfg(**data["wallets"]),
        logging=LoggingCfg(**data["logging"]),
        secrets=secrets,
    )
