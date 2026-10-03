"""Terminal dashboard.

Renders a single-screen view: top opportunities, open positions,
recent decisions, risk state, kill-switch status. Uses rich.live for
in-place refresh.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..core.risk import RiskManager
from ..types import Decision, Mode, Position, TradeOpportunity


def _decision_color(d: Decision) -> str:
    return {
        Decision.ENTER: "bold green",
        Decision.WATCH: "yellow",
        Decision.NO_TRADE: "dim",
    }[d]


def render_opportunities(opps: Iterable[TradeOpportunity], top: int = 8) -> Table:
    t = Table(title="Top Opportunities", expand=True)
    t.add_column("Market", overflow="fold", max_width=44)
    t.add_column("Side")
    t.add_column("Mid", justify="right")
    t.add_column("Fair", justify="right")
    t.add_column("Edge", justify="right")
    t.add_column("Conf", justify="right")
    t.add_column("Liq", justify="right")
    t.add_column("Score", justify="right")
    t.add_column("Decision")

    sorted_opps = sorted(opps, key=lambda o: o.score, reverse=True)[:top]
    for o in sorted_opps:
        t.add_row(
            o.market.question[:44],
            o.side.value,
            f"{o.probability.market_implied_prob:.3f}",
            f"{o.probability.estimated_prob:.3f}",
            f"{o.probability.edge:+.3f}",
            f"{o.probability.confidence:.2f}",
            f"${o.max_fill_usd:.0f}",
            f"{o.score:+.3f}",
            Text(o.decision.value, style=_decision_color(o.decision)),
        )
    return t


def render_positions(positions: list[Position]) -> Table:
    t = Table(title="Open Positions", expand=True)
    t.add_column("Market", overflow="fold", max_width=44)
    t.add_column("Side")
    t.add_column("Entry", justify="right")
    t.add_column("Size", justify="right")
    t.add_column("Stop", justify="right")
    t.add_column("Trail", justify="right")
    t.add_column("Paper")
    for p in positions:
        t.add_row(
            p.market_id[:44],
            p.side.value,
            f"{p.avg_entry_price:.3f}",
            f"{p.size:.0f}",
            f"{p.stop_loss_price:.3f}" if p.stop_loss_price else "-",
            f"{p.trailing_stop_price:.3f}" if p.trailing_stop_price else "-",
            "yes" if p.is_paper else "LIVE",
        )
    if not positions:
        t.add_row("(none)", "", "", "", "", "", "")
    return t


def render_risk(risk: RiskManager, mode: Mode) -> Panel:
    s = risk.state
    cfg = risk.cfg
    lines = [
        f"[bold]Mode[/]: {mode.value}",
        f"Bankroll:        ${s.bankroll_usd:,.2f}",
        f"Realized PnL:    ${s.realized_pnl_usd:+,.2f}",
        f"Unrealized PnL:  ${s.unrealized_pnl_usd:+,.2f}",
        f"Equity:          ${s.equity:,.2f}",
        f"Drawdown:        {s.drawdown_pct:.2%}  (max {cfg.max_drawdown_pct:.0%})",
        f"Daily PnL:       ${s.daily_pnl():+,.2f}  "
        f"(stop ${-cfg.max_daily_loss_pct * cfg.bankroll_usd:,.2f})",
        f"Open positions:  {len(s.open_positions)} / {cfg.max_open_positions}",
        "Kill switch:     " + ("[red]ACTIVE[/]" if risk.kill_switch_active() else "ok"),
    ]
    return Panel("\n".join(lines), title="Risk State", border_style="cyan")


def render_dashboard(
    *,
    mode: Mode,
    opps: list[TradeOpportunity],
    positions: list[Position],
    risk: RiskManager,
    last_update: datetime,
) -> Group:
    header = Panel(
        f"polyagent — {last_update.strftime('%Y-%m-%d %H:%M:%S')} UTC",
        border_style="bold blue",
    )
    return Group(
        header,
        render_risk(risk, mode),
        render_opportunities(opps),
        render_positions(positions),
    )


class Dashboard:
    def __init__(self, console: Console | None = None):
        self.console = console or Console()
        self._live: Live | None = None

    def start(self) -> None:
        self._live = Live(console=self.console, refresh_per_second=2)
        self._live.start()

    def stop(self) -> None:
        if self._live:
            self._live.stop()
            self._live = None

    def update(
        self, *, mode: Mode, opps: list[TradeOpportunity],
        positions: list[Position], risk: RiskManager,
    ) -> None:
        if not self._live:
            return
        self._live.update(render_dashboard(
            mode=mode, opps=opps, positions=positions,
            risk=risk, last_update=datetime.utcnow(),
        ))
