"""Domain types used across connectors, scanners, and engines.

Everything that crosses a module boundary is a pydantic model so that
mismatches between connector output and engine input get caught at
parse time, not at trade time.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class Mode(str, Enum):
    PAPER = "PAPER_TRADING"
    MANUAL = "MANUAL_APPROVAL"
    AUTO = "AUTO_TRADING"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class Decision(str, Enum):
    ENTER = "ENTER"
    WATCH = "WATCH"
    NO_TRADE = "NO_TRADE"


class Outcome(BaseModel):
    """A single tradable outcome of a market (e.g. YES, NO)."""
    token_id: str                # Polymarket CLOB token id
    name: str                    # "Yes" / "No" / candidate name
    price: float                 # last / mid, in [0, 1]


class Market(BaseModel):
    market_id: str               # condition_id on Polymarket
    slug: str
    question: str
    description: str = ""
    category: str = "uncategorized"
    close_time: Optional[datetime] = None
    resolution_source: str = ""
    rules_text: str = ""
    outcomes: list[Outcome]
    volume_usd: float = 0.0
    liquidity_usd: float = 0.0
    is_active: bool = True
    is_closed: bool = False

    @field_validator("outcomes")
    @classmethod
    def _at_least_one(cls, v: list[Outcome]) -> list[Outcome]:
        if not v:
            raise ValueError("market must have at least one outcome")
        return v


class OrderBookLevel(BaseModel):
    price: float
    size: float


class OrderBook(BaseModel):
    token_id: str
    bids: list[OrderBookLevel]   # sorted descending by price
    asks: list[OrderBookLevel]   # sorted ascending by price
    timestamp: datetime

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    @property
    def mid(self) -> Optional[float]:
        b, a = self.best_bid, self.best_ask
        if b is None or a is None:
            return None
        return (b + a) / 2

    @property
    def spread(self) -> Optional[float]:
        b, a = self.best_bid, self.best_ask
        if b is None or a is None:
            return None
        return a - b


class ProbabilityEstimate(BaseModel):
    estimated_prob: float        # agent's fair probability
    confidence: float            # [0, 1]
    market_implied_prob: float
    edge: float                  # estimated_prob - market_implied_prob (signed)
    fair_value_low: float
    fair_value_high: float
    rationale: str = ""
    components: dict = Field(default_factory=dict)


class TradeOpportunity(BaseModel):
    """Everything the decision engine needs and produces for one
    candidate trade. Persisted in full so we can audit every NO_TRADE."""
    market: Market
    outcome: Outcome
    side: Side
    book: OrderBook
    probability: ProbabilityEstimate

    # Liquidity / microstructure
    spread: float
    slippage_pct: float
    max_fill_usd: float
    liquidity_quality: float     # [0, 1]

    # Qualitative inputs
    resolution_clarity: float    # [0, 1]
    source_credibility: float    # [0, 1]
    wallet_signal: float         # [-1, 1]; positive = aligned with side
    catalyst_strength: float     # [0, 1]
    manipulation_risk: float     # [0, 1]
    correlation_risk: float      # [0, 1]

    # Outputs of decision engine
    score: float = 0.0
    decision: Decision = Decision.NO_TRADE
    suggested_entry_price: float = 0.0
    max_chase_price: float = 0.0
    stop_loss_price: float = 0.0
    take_profit_prices: list[float] = Field(default_factory=list)
    suggested_size_usd: float = 0.0
    reasons: list[str] = Field(default_factory=list)


class Order(BaseModel):
    order_id: str
    market_id: str
    token_id: str
    side: Side
    price: float
    size: float                  # in shares
    filled: float = 0.0
    status: str = "open"         # open | filled | cancelled | rejected
    placed_at: datetime
    is_paper: bool = True


class Position(BaseModel):
    market_id: str
    token_id: str
    side: Side
    avg_entry_price: float
    size: float                  # shares held
    realized_pnl_usd: float = 0.0
    opened_at: datetime
    last_update: datetime
    thesis: str = ""
    stop_loss_price: float = 0.0
    take_profit_prices: list[float] = Field(default_factory=list)
    trailing_stop_price: Optional[float] = None
    is_paper: bool = True
