"""Backtest engine.

Replays historical market data through the live decision engine and risk
manager, simulating fills against historical order books. The result is
a PnL report and per-market diagnostics that you can use to:

  * Tune decision thresholds (min_edge, min_confidence, score weights)
  * Compare strategies (different probability models, signal weights)
  * Catch regressions in the engine before they touch real money

What it does NOT do (yet):
  * Replay news timestamps (assumes news available at decision time;
    add `news_replay` parameter when you have timestamped news fixtures)
  * Replay wallet flow timestamps (same — pass a `WalletDataSource` that
    only emits actions before the decision tick)

The backtester uses the same `decision.evaluate` and `risk` modules as
the live runner, so any improvement to either lifts both.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Optional

from ..config import Settings
from ..core import decision, exits, orderbook, probability
from ..core.exits import ExitAction
from ..core.risk import RiskManager
from ..logging_setup import get_logger
from ..types import Decision, Market, OrderBook, Position, Side, TradeOpportunity

log = get_logger(__name__)


@dataclass
class HistoricalTick:
    """One observation in the backtest stream."""
    ts: datetime
    market: Market
    book_per_token: dict[str, OrderBook]   # token_id -> book
    # Optional ground truth at this tick (e.g. resolution outcome). When
    # provided after market close, the backtester uses it to compute
    # realized PnL on still-open positions.
    resolved_winning_token: Optional[str] = None


@dataclass
class BacktestPosition:
    market_id: str
    token_id: str
    side: Side
    avg_entry_price: float
    size_shares: float
    opened_ts: datetime
    stop_loss_price: float
    take_profit_prices: list[float]
    trailing_stop_price: Optional[float] = None
    realized_pnl_usd: float = 0.0


@dataclass
class BacktestResult:
    n_ticks: int = 0
    n_decisions: int = 0
    n_enters: int = 0
    n_exits: int = 0
    realized_pnl_usd: float = 0.0
    fees_paid_usd: float = 0.0
    closed_trades: list["ClosedTrade"] = field(default_factory=list)
    max_drawdown_usd: float = 0.0
    peak_equity_usd: float = 0.0

    @property
    def n_winning_trades(self) -> int:
        return sum(1 for t in self.closed_trades if t.realized_pnl_usd > 0)

    @property
    def win_rate(self) -> float:
        return self.n_winning_trades / len(self.closed_trades) if self.closed_trades else 0.0

    @property
    def avg_pnl(self) -> float:
        if not self.closed_trades:
            return 0.0
        return sum(t.realized_pnl_usd for t in self.closed_trades) / len(self.closed_trades)


@dataclass
class ClosedTrade:
    market_id: str
    token_id: str
    side: Side
    entry_price: float
    exit_price: float
    size_shares: float
    realized_pnl_usd: float
    holding_seconds: int
    reason: str


class Backtester:
    """Plug-and-play backtester. Build a list (or generator) of
    HistoricalTick and call .run(...).

    For wallet/news signals, pass `signal_fn(ts, market) -> dict` that
    returns the kwargs for `probability.estimate` for each tick.
    """

    def __init__(self, settings: Settings, *, fee_per_share: float = 0.0):
        self.settings = settings
        self.fee_per_share = fee_per_share
        self.risk = RiskManager(settings.risk, kill_switch_file="/tmp/_backtest_kill")
        self.positions: dict[tuple[str, str], BacktestPosition] = {}

    def run(
        self,
        ticks: Iterable[HistoricalTick],
        signal_fn=None,
    ) -> BacktestResult:
        result = BacktestResult()
        for tick in ticks:
            result.n_ticks += 1
            self._process_tick(tick, result, signal_fn)
            equity = self.risk.state.realized_pnl_usd + self.risk.state.unrealized_pnl_usd
            result.peak_equity_usd = max(result.peak_equity_usd, equity)
            dd = result.peak_equity_usd - equity
            result.max_drawdown_usd = max(result.max_drawdown_usd, dd)

            # If this tick reports market resolution, force-close anything still open
            if tick.resolved_winning_token is not None:
                self._resolve_market(tick, result)
        return result

    # ---------------- Internals ----------------

    def _process_tick(
        self,
        tick: HistoricalTick,
        result: BacktestResult,
        signal_fn,
    ) -> None:
        m = tick.market
        # First: monitor existing positions for exits
        for outcome in m.outcomes:
            book = tick.book_per_token.get(outcome.token_id)
            if book is None or book.mid is None:
                continue
            key = (m.market_id, outcome.token_id)
            pos = self.positions.get(key)
            if pos is None:
                continue
            current = book.mid
            self._update_trailing(pos, current)
            decision_obj = self._evaluate_exit(pos, current, book)
            if decision_obj.action is ExitAction.EXIT:
                self._close_position(pos, current, decision_obj.reason, tick.ts, result)
            elif decision_obj.action is ExitAction.REDUCE:
                self._reduce_position(pos, current, decision_obj.fraction,
                                      decision_obj.reason, tick.ts, result)

        # Second: look for new entries
        for outcome in m.outcomes:
            book = tick.book_per_token.get(outcome.token_id)
            if book is None or book.best_ask is None:
                continue
            key = (m.market_id, outcome.token_id)
            if key in self.positions:
                continue   # already in this market+side
            opp = self._build_opp(tick, outcome, book, signal_fn)
            if opp is None:
                continue
            decision.evaluate(opp, self.settings.decision)
            result.n_decisions += 1
            if opp.decision is Decision.ENTER:
                self._enter_position(opp, tick.ts, result)

    def _build_opp(self, tick, outcome, book, signal_fn) -> Optional[TradeOpportunity]:
        side = Side.BUY
        target_size_usd = max(
            self.settings.risk.min_position_usd,
            self.settings.risk.max_position_pct_bankroll * self.settings.risk.bankroll_usd,
        )
        ba = orderbook.analyze(
            book, side, target_size_usd, self.settings.decision.max_slippage_pct
        )
        if ba is None:
            return None

        # Default: no signals — caller passes signal_fn for richer backtests.
        signals = {}
        if signal_fn is not None:
            try:
                signals = signal_fn(tick.ts, tick.market) or {}
            except Exception as e:
                log.warning("backtest.signal_fn_failed", error=str(e))
                signals = {}

        side_is_yes = outcome.name.strip().lower() in ("yes", "true")
        yes_implied = outcome.price if side_is_yes else (1 - outcome.price)
        prob = probability.estimate(
            market_implied=yes_implied,
            side_is_yes=side_is_yes,
            news_signal=signals.get("news_signal", 0.0),
            wallet_signal=signals.get("wallet_signal", 0.0),
            sentiment=signals.get("sentiment", 0.0),
            resolution_clarity=signals.get("resolution_clarity", 0.8),
        )

        opp = TradeOpportunity(
            market=tick.market, outcome=outcome, side=side, book=book,
            probability=prob, spread=ba.spread, slippage_pct=ba.slippage_pct,
            max_fill_usd=ba.max_fill_usd_at_target_slippage,
            liquidity_quality=ba.liquidity_quality,
            resolution_clarity=signals.get("resolution_clarity", 0.8),
            source_credibility=signals.get("source_credibility", 0.7),
            wallet_signal=signals.get("wallet_signal", 0.0),
            catalyst_strength=signals.get("catalyst_strength", 0.5),
            manipulation_risk=ba.manipulation_risk,
            correlation_risk=0.0,
        )
        opp.suggested_entry_price = round(min(ba.best_ask, outcome.price + 0.005), 4)
        opp.max_chase_price = round(min(opp.suggested_entry_price + 0.02, 0.99), 4)
        opp.stop_loss_price = round(
            max(0.01, opp.suggested_entry_price * (1 - self.settings.risk.hard_stop_loss_pct)), 4)
        opp.take_profit_prices = [
            round(min(0.99, opp.suggested_entry_price + lvl["price_delta"]), 4)
            for lvl in self.settings.risk.partial_take_profit_levels
        ]
        opp.suggested_size_usd = self.risk.size_usd(opp)
        return opp

    def _enter_position(self, opp: TradeOpportunity, ts: datetime, result: BacktestResult) -> None:
        # Simulate fill at best_ask within max_fill capacity, paying spread.
        size_usd = min(opp.suggested_size_usd, opp.max_fill_usd or 0.0)
        if size_usd <= 0:
            return
        fill_price = opp.book.best_ask or opp.suggested_entry_price
        size_shares = size_usd / fill_price
        result.fees_paid_usd += size_shares * self.fee_per_share

        pos = BacktestPosition(
            market_id=opp.market.market_id,
            token_id=opp.outcome.token_id,
            side=opp.side,
            avg_entry_price=fill_price,
            size_shares=size_shares,
            opened_ts=ts,
            stop_loss_price=opp.stop_loss_price,
            take_profit_prices=list(opp.take_profit_prices),
        )
        self.positions[(pos.market_id, pos.token_id)] = pos
        result.n_enters += 1

    def _evaluate_exit(self, pos: BacktestPosition, current: float, book: OrderBook):
        # Convert BacktestPosition -> Position for the engine
        from datetime import datetime as _dt
        from datetime import timezone
        engine_pos = Position(
            market_id=pos.market_id, token_id=pos.token_id, side=pos.side,
            avg_entry_price=pos.avg_entry_price, size=pos.size_shares,
            opened_at=pos.opened_ts, last_update=_dt.now(timezone.utc),
            stop_loss_price=pos.stop_loss_price,
            take_profit_prices=pos.take_profit_prices,
            trailing_stop_price=pos.trailing_stop_price,
        )
        return exits.evaluate(engine_pos, current_price=current, cfg=self.settings.risk)

    def _update_trailing(self, pos: BacktestPosition, current: float) -> None:
        from datetime import datetime as _dt
        from datetime import timezone
        cfg = self.settings.risk
        engine_pos = Position(
            market_id=pos.market_id, token_id=pos.token_id, side=pos.side,
            avg_entry_price=pos.avg_entry_price, size=pos.size_shares,
            opened_at=pos.opened_ts, last_update=_dt.now(timezone.utc),
            stop_loss_price=pos.stop_loss_price,
            take_profit_prices=pos.take_profit_prices,
            trailing_stop_price=pos.trailing_stop_price,
        )
        exits.update_trailing(engine_pos, current_price=current, cfg=cfg)
        pos.trailing_stop_price = engine_pos.trailing_stop_price

    def _close_position(self, pos: BacktestPosition, exit_price: float,
                        reason: str, ts: datetime, result: BacktestResult) -> None:
        pnl = (exit_price - pos.avg_entry_price) * pos.size_shares if pos.side is Side.BUY \
              else (pos.avg_entry_price - exit_price) * pos.size_shares
        pnl -= pos.size_shares * self.fee_per_share
        result.realized_pnl_usd += pnl
        result.fees_paid_usd += pos.size_shares * self.fee_per_share
        result.n_exits += 1
        result.closed_trades.append(ClosedTrade(
            market_id=pos.market_id, token_id=pos.token_id, side=pos.side,
            entry_price=pos.avg_entry_price, exit_price=exit_price,
            size_shares=pos.size_shares, realized_pnl_usd=pnl,
            holding_seconds=int((ts - pos.opened_ts).total_seconds()),
            reason=reason,
        ))
        del self.positions[(pos.market_id, pos.token_id)]

    def _reduce_position(self, pos: BacktestPosition, current: float, fraction: float,
                         reason: str, ts: datetime, result: BacktestResult) -> None:
        sell_size = pos.size_shares * fraction
        pnl = (current - pos.avg_entry_price) * sell_size if pos.side is Side.BUY \
              else (pos.avg_entry_price - current) * sell_size
        result.realized_pnl_usd += pnl
        pos.size_shares -= sell_size
        result.closed_trades.append(ClosedTrade(
            market_id=pos.market_id, token_id=pos.token_id, side=pos.side,
            entry_price=pos.avg_entry_price, exit_price=current,
            size_shares=sell_size, realized_pnl_usd=pnl,
            holding_seconds=int((ts - pos.opened_ts).total_seconds()),
            reason=f"partial: {reason}",
        ))

    def _resolve_market(self, tick: HistoricalTick, result: BacktestResult) -> None:
        """At resolution, every YES token pays out 1.0 if winning else 0.0."""
        winning = tick.resolved_winning_token
        for key, pos in list(self.positions.items()):
            if pos.market_id != tick.market.market_id:
                continue
            settle = 1.0 if pos.token_id == winning else 0.0
            self._close_position(pos, settle, f"resolved winner={winning}", tick.ts, result)
