"""Portfolio risk manager.

Owns:
  * bankroll, realized PnL, daily PnL, drawdown
  * exposure tallies (total, per-category, correlated)
  * position sizing (capped Kelly)
  * pre-trade gate: should this trade pass given current state?
  * kill switch checks
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from ..config import RiskCfg
from ..logging_setup import get_logger
from ..types import Position, TradeOpportunity

log = get_logger(__name__)


@dataclass
class RiskState:
    bankroll_usd: float
    realized_pnl_usd: float = 0.0
    unrealized_pnl_usd: float = 0.0
    daily_pnl_by_date: dict[date, float] = field(default_factory=dict)
    peak_equity: float = 0.0
    open_positions: list[Position] = field(default_factory=list)

    @property
    def equity(self) -> float:
        return self.bankroll_usd + self.realized_pnl_usd + self.unrealized_pnl_usd

    @property
    def drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, 1 - self.equity / self.peak_equity)

    def daily_pnl(self, d: Optional[date] = None) -> float:
        d = d or date.today()
        return self.daily_pnl_by_date.get(d, 0.0)

    def category_exposure(self, category: str) -> float:
        return sum(
            p.size * p.avg_entry_price
            for p in self.open_positions if getattr(p, "category", "") == category
        )


class RiskManager:
    def __init__(self, cfg: RiskCfg, state: Optional[RiskState] = None,
                 kill_switch_file: str = "./data/KILL_SWITCH"):
        self.cfg = cfg
        self.state = state or RiskState(bankroll_usd=cfg.bankroll_usd)
        self.state.peak_equity = max(self.state.peak_equity, self.state.equity)
        self._kill_switch_file = Path(kill_switch_file)

    # ---------- Kill switch ----------

    def kill_switch_active(self) -> bool:
        return self._kill_switch_file.exists()

    def trip_kill_switch(self, reason: str) -> None:
        self._kill_switch_file.parent.mkdir(parents=True, exist_ok=True)
        self._kill_switch_file.write_text(reason)
        log.error("risk.kill_switch_tripped", reason=reason)

    # ---------- Pre-trade gate ----------

    def pretrade_block_reasons(self, opp: TradeOpportunity) -> list[str]:
        out: list[str] = []
        if self.kill_switch_active():
            out.append("kill switch active")
        if len(self.state.open_positions) >= self.cfg.max_open_positions:
            out.append(f"max open positions reached ({self.cfg.max_open_positions})")

        # Daily loss
        dpnl = self.state.daily_pnl()
        max_daily_loss = -self.cfg.max_daily_loss_pct * self.cfg.bankroll_usd
        if dpnl <= max_daily_loss:
            out.append(f"daily loss limit hit ({dpnl:.2f} <= {max_daily_loss:.2f})")

        # Drawdown
        if self.state.drawdown_pct >= self.cfg.max_drawdown_pct:
            out.append(
                f"max drawdown breached ({self.state.drawdown_pct:.2%} "
                f">= {self.cfg.max_drawdown_pct:.2%})"
            )

        # Category exposure cap
        cat_cap = self.cfg.max_category_exposure_pct * self.cfg.bankroll_usd
        if self.state.category_exposure(opp.market.category) >= cat_cap:
            out.append(f"category {opp.market.category} exposure cap hit")

        return out

    # ---------- Sizing ----------

    def size_usd(self, opp: TradeOpportunity) -> float:
        """Capped Kelly fraction. Polymarket-style binary outcome:
        b = (1 - p_market) / p_market for buying YES at p_market. Use
        agent's edge to derive Kelly stake, scale by kelly_fraction,
        clamp to [min, max]."""
        p = opp.probability.estimated_prob
        m = opp.probability.market_implied_prob
        if m <= 0 or m >= 1:
            return 0.0
        # Decimal odds when entering at price m and outcome resolves YES = 1.
        b = (1 - m) / m
        # Full Kelly fraction of bankroll
        kelly = (b * p - (1 - p)) / b if b > 0 else 0.0
        kelly = max(0.0, kelly)
        scaled = kelly * self.cfg.kelly_fraction
        cap = self.cfg.max_position_pct_bankroll
        frac = min(scaled, cap)
        usd = frac * self.cfg.bankroll_usd
        if usd < self.cfg.min_position_usd:
            return 0.0
        return round(usd, 2)

    # ---------- PnL bookkeeping ----------

    def record_fill(self, side_buy: bool, price: float, size_shares: float) -> None:
        # Cash flow only; PnL is realized on exit.
        cash = price * size_shares
        if side_buy:
            self.state.bankroll_usd -= cash
        else:
            self.state.bankroll_usd += cash

    def realize_pnl(self, pnl_usd: float, d: Optional[date] = None) -> None:
        d = d or date.today()
        self.state.realized_pnl_usd += pnl_usd
        self.state.daily_pnl_by_date[d] = self.state.daily_pnl(d) + pnl_usd
        self.state.peak_equity = max(self.state.peak_equity, self.state.equity)
        log.info("risk.pnl_realized", pnl=pnl_usd, equity=self.state.equity)
