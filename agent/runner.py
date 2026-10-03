"""Runtime loop.

Glues everything together. Implements the loop from the spec:
  scan markets -> update books -> wallet/news signals -> read rules
  -> estimate probability -> score -> decide -> place / monitor / exit.

Designed to be safe by default: paper mode unless every compliance gate
clears AND the user has explicitly opted into a non-paper mode.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from .config import Settings
from .connectors.base import BaseConnector
from .connectors.news import NewsConnector
from .connectors.paper import PaperConnector
from .connectors.polymarket import PolymarketConnector
from .connectors.social import SocialConnector
from .connectors.wallets import NoopWalletProvider, WalletDataProvider, aggregate_signal
from .core import compliance, decision, exits, orderbook, probability
from .core.execution import ExecutionEngine
from .core.market_scanner import MarketScanner
from .core.risk import RiskManager
from .dashboard.cli import Dashboard
from .llm.rule_reader import RuleReader
from .logging_setup import get_audit_logger, get_logger
from .storage.database import Database
from .types import Decision, Mode, Position, Side, TradeOpportunity

log = get_logger(__name__)
audit = get_audit_logger()


class AgentRunner:
    def __init__(
        self,
        settings: Settings,
        data_source: Optional[BaseConnector] = None,
        wallets: Optional[WalletDataProvider] = None,
        news_fixtures: Optional[dict] = None,
    ):
        self.settings = settings
        self.mode = settings.secrets.mode

        # Compliance check up front; but paper mode is always OK
        if self.mode is not Mode.PAPER:
            blocks = compliance.block_reasons(settings)
            if blocks:
                log.error("compliance.failed_at_startup", blocks=blocks)
                log.warning("falling back to PAPER_TRADING")
                self.mode = Mode.PAPER

        # Build connector chain.
        # `data_source` lets callers (e.g. --demo, tests) swap in a synthetic
        # source. Otherwise we use the real Polymarket connector.
        if data_source is not None:
            self._real = data_source
        else:
            self._real = PolymarketConnector(
                private_key=settings.secrets.polymarket_private_key,
                funder_address=settings.secrets.polymarket_funder_address,
                api_key=settings.secrets.polymarket_api_key,
                api_secret=settings.secrets.polymarket_api_secret,
                api_passphrase=settings.secrets.polymarket_api_passphrase,
                live=(self.mode is not Mode.PAPER),
            )
        # Read endpoints always go to the underlying connector. Order endpoints
        # go through paper in PAPER mode, real otherwise. Synthetic data sources
        # are always wrapped in paper since they don't trade.
        if self.mode is Mode.PAPER or not getattr(self._real, "supports_live_trading", False):
            self.connector: BaseConnector = PaperConnector(self._real)
        else:
            self.connector = self._real

        self.scanner = MarketScanner(self.connector, top_n=settings.scanners.market_scan_top_n)
        self.execution = ExecutionEngine(self.connector, settings.execution)
        self.risk = RiskManager(
            settings.risk,
            kill_switch_file=settings.secrets.kill_switch_file,
        )
        self.rule_reader = RuleReader()
        self.news = NewsConnector(
            api_key=settings.secrets.newsapi_key,
            fixtures=news_fixtures,
        )
        self.social = SocialConnector()
        self.wallets: WalletDataProvider = wallets or NoopWalletProvider()

        self.db = Database(settings.secrets.database_url)
        self.dashboard = Dashboard()

        self._latest_opps: list[TradeOpportunity] = []
        self._stop = asyncio.Event()
        # Map (market_id, token_id) -> Position
        self._positions: dict[tuple[str, str], Position] = {}
        # Track which TP levels have been hit per position so we don't repeat
        self._tp_hit: dict[tuple[str, str], set[float]] = {}

    # -------------------- Public lifecycle --------------------

    async def start(self) -> None:
        await self.db.init()
        self.dashboard.start()
        log.info("runner.started", mode=self.mode.value)
        try:
            await asyncio.gather(self._scan_loop(), self._monitor_loop())
        finally:
            self.dashboard.stop()
            await self.connector.stop()
            await self.news.stop()
            await self.db.close()

    def stop(self) -> None:
        self._stop.set()

    # -------------------- Scan loop --------------------

    async def _scan_loop(self) -> None:
        sem = asyncio.Semaphore(self.settings.agent.max_concurrent_scans)
        while not self._stop.is_set():
            try:
                scanned = await self.scanner.scan()
                tasks = [self._evaluate_market(sem, sm.market) for sm in scanned]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                opps: list[TradeOpportunity] = []
                for r in results:
                    if isinstance(r, list):
                        opps.extend(r)
                    elif isinstance(r, Exception):
                        log.warning("scan.eval_failed", error=str(r))
                self._latest_opps = opps
                self.dashboard.update(
                    mode=self.mode,
                    opps=self._latest_opps,
                    positions=list(self._positions.values()),
                    risk=self.risk,
                )
                # Decide and act on best ENTER candidates
                await self._act_on_opportunities(opps)
            except Exception as e:
                log.exception("scan.loop_error", error=str(e))

            await asyncio.wait(
                [asyncio.create_task(self._stop.wait())],
                timeout=self.settings.agent.loop_interval_seconds,
            )

    async def _evaluate_market(
        self,
        sem: asyncio.Semaphore,
        m,
    ) -> list[TradeOpportunity]:
        """Build a TradeOpportunity for each (outcome, side) on this market
        and run the decision engine."""
        async with sem:
            results: list[TradeOpportunity] = []
            rules = await self.rule_reader.read(m)
            news_items = await self.news.search(m.question, hours=48, limit=10)
            catalyst, src_cred = NewsConnector.aggregate_signal(news_items)
            sentiment_snap = await self.social.snapshot(m.question)

            for outcome in m.outcomes:
                book = await self.connector.get_order_book(outcome.token_id)
                if book is None or book.best_bid is None or book.best_ask is None:
                    continue

                # Consider BUY only by default in MVP. SELL of YES is
                # equivalent to BUY of NO on a binary market via the
                # complementary token; the engine evaluates each token
                # separately so we always hit both sides naturally.
                side = Side.BUY
                target_size_usd = max(
                    self.settings.risk.min_position_usd,
                    self.settings.risk.max_position_pct_bankroll
                    * self.settings.risk.bankroll_usd,
                )
                ba = orderbook.analyze(
                    book, side, target_size_usd,
                    self.settings.decision.max_slippage_pct,
                )
                if ba is None:
                    continue

                # Wallet signal (returns neutral with NoopWalletProvider).
                # Convention: aggregate_signal with side="BUY" returns alignment
                # in [-1,+1] where positive = smart money buying the YES token
                # (bullish for YES). The probability engine is YES-centered and
                # will orient the output toward the requested side.
                actions = await self.wallets.recent_actions(m.market_id, hours=24)
                wsig = aggregate_signal(actions, side="BUY")

                # Side bias: which outcome does aggregated news/wallet support?
                # Heuristic: compare to YES outcome in YES/NO markets. For
                # categorical markets, treat the outcome under evaluation as
                # the "this outcome" side and let the news/wallets inputs
                # speak via probability.estimate.
                side_is_yes = outcome.name.strip().lower() in ("yes", "true")
                # The engine is YES-centered: it expects the YES-side implied
                # probability and then orients output by side_is_yes. For a
                # NO outcome priced at p, YES implied = 1-p.
                yes_implied = outcome.price if side_is_yes else (1 - outcome.price)

                prob = probability.estimate(
                    market_implied=yes_implied,
                    side_is_yes=side_is_yes,
                    news_signal=(catalyst - 0.5) * 2 if news_items else 0.0,
                    wallet_signal=wsig.alignment,
                    sentiment=sentiment_snap.score,
                    resolution_clarity=rules.resolution_clarity,
                    time_to_close_hours=_hours_until(m.close_time),
                )

                opp = TradeOpportunity(
                    market=m,
                    outcome=outcome,
                    side=side,
                    book=book,
                    probability=prob,
                    spread=ba.spread,
                    slippage_pct=ba.slippage_pct,
                    max_fill_usd=ba.max_fill_usd_at_target_slippage,
                    liquidity_quality=ba.liquidity_quality,
                    resolution_clarity=rules.resolution_clarity,
                    source_credibility=src_cred,
                    wallet_signal=wsig.alignment,
                    catalyst_strength=catalyst,
                    manipulation_risk=ba.manipulation_risk,
                    correlation_risk=0.0,  # TODO: compute vs open positions
                )

                # Suggested entry/stops/sizing
                opp.suggested_entry_price = round(min(ba.best_ask, outcome.price + 0.005), 4)
                opp.max_chase_price = round(
                    min(opp.suggested_entry_price + self.settings.execution.max_chase_ticks
                        * self.settings.execution.min_tick, 0.99),
                    4,
                )
                opp.stop_loss_price = round(
                    max(0.01, opp.suggested_entry_price *
                        (1 - self.settings.risk.hard_stop_loss_pct)),
                    4,
                )
                opp.take_profit_prices = [
                    round(min(0.99, opp.suggested_entry_price + lvl["price_delta"]), 4)
                    for lvl in self.settings.risk.partial_take_profit_levels
                ]
                opp.suggested_size_usd = self.risk.size_usd(opp)

                decision.evaluate(opp, self.settings.decision)

                # Persist every decision (ENTER, WATCH, NO_TRADE)
                try:
                    await self.db.log_decision(opp)
                except Exception as e:
                    log.warning("db.log_decision_failed", error=str(e))
                audit.info(
                    "decision",
                    decision=opp.decision.value,
                    market_id=m.market_id,
                    outcome=outcome.name,
                    score=opp.score,
                    edge=prob.edge,
                    confidence=prob.confidence,
                    reasons=opp.reasons,
                )

                results.append(opp)
            return results

    async def _act_on_opportunities(self, opps: list[TradeOpportunity]) -> None:
        enters = [o for o in opps if o.decision is Decision.ENTER and o.suggested_size_usd > 0]
        # Best score first
        enters.sort(key=lambda o: o.score, reverse=True)
        for opp in enters:
            block = self.risk.pretrade_block_reasons(opp)
            if block:
                opp.decision = Decision.NO_TRADE
                opp.reasons.extend(block)
                audit.info("decision_blocked_by_risk", reasons=block,
                           market_id=opp.market.market_id)
                continue

            if self.mode is Mode.MANUAL:
                # Don't auto-place. Surface in dashboard and audit log;
                # operator approves out-of-band (e.g. a future approve CLI cmd).
                audit.info("manual_pending", market_id=opp.market.market_id,
                           outcome=opp.outcome.name, score=opp.score,
                           suggested_size_usd=opp.suggested_size_usd)
                continue

            # Compliance re-check before any non-paper order
            if self.mode is not Mode.PAPER:
                blocks = compliance.block_reasons(self.settings)
                if blocks:
                    log.error("compliance.blocked_pre_order", reasons=blocks)
                    self.risk.trip_kill_switch("compliance check failed at order time")
                    return

            await self._place_entry(opp)

    async def _place_entry(self, opp: TradeOpportunity) -> None:
        size_shares = round(opp.suggested_size_usd / max(0.01, opp.suggested_entry_price), 2)
        if size_shares <= 0:
            return
        try:
            order = await self.execution.enter_limit(
                market_id=opp.market.market_id,
                token_id=opp.outcome.token_id,
                side=opp.side,
                price=opp.suggested_entry_price,
                size_shares=size_shares,
                max_chase_price=opp.max_chase_price,
            )
        except Exception as e:
            log.error("entry.place_failed", error=str(e),
                      market_id=opp.market.market_id)
            return

        if order.filled > 0:
            key = (opp.market.market_id, opp.outcome.token_id)
            existing = self._positions.get(key)
            if existing is None:
                pos = Position(
                    market_id=opp.market.market_id,
                    token_id=opp.outcome.token_id,
                    side=opp.side,
                    avg_entry_price=order.price,
                    size=order.filled,
                    opened_at=datetime.now(timezone.utc),
                    last_update=datetime.now(timezone.utc),
                    thesis=f"edge={opp.probability.edge:+.3f} "
                           f"conf={opp.probability.confidence:.2f}",
                    stop_loss_price=opp.stop_loss_price,
                    take_profit_prices=list(opp.take_profit_prices),
                    is_paper=order.is_paper,
                )
                self._positions[key] = pos
                self.risk.state.open_positions.append(pos)
                self._tp_hit[key] = set()
            else:
                new_size = existing.size + order.filled
                existing.avg_entry_price = (
                    existing.avg_entry_price * existing.size + order.price * order.filled
                ) / new_size
                existing.size = new_size
                existing.last_update = datetime.now(timezone.utc)
            self.risk.record_fill(opp.side is Side.BUY, order.price, order.filled)
            audit.info("entry_filled",
                       market_id=opp.market.market_id, price=order.price,
                       size=order.filled, paper=order.is_paper)

    # -------------------- Monitor loop --------------------

    async def _monitor_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.execution.cancel_stale()
                await self._tick_positions()
            except Exception as e:
                log.exception("monitor.error", error=str(e))
            await asyncio.wait(
                [asyncio.create_task(self._stop.wait())],
                timeout=max(5, self.settings.agent.loop_interval_seconds // 2),
            )

    async def _tick_positions(self) -> None:
        unrealized = 0.0
        for key, pos in list(self._positions.items()):
            book = await self.connector.get_order_book(pos.token_id)
            if book is None or book.mid is None:
                continue
            current = book.mid
            # Mark-to-market
            mtm = (current - pos.avg_entry_price) * pos.size if pos.side is Side.BUY \
                  else (pos.avg_entry_price - current) * pos.size
            unrealized += mtm

            # Update trailing stop
            exits.update_trailing(pos, current, self.settings.risk)

            # TP de-dup: skip TPs we've already cleared
            already_hit = self._tp_hit.setdefault(key, set())
            remaining_tps = [tp for tp in pos.take_profit_prices if tp not in already_hit]
            scoped_pos = pos.model_copy(update={"take_profit_prices": remaining_tps})

            ed = exits.evaluate(
                scoped_pos,
                current_price=current,
                cfg=self.settings.risk,
            )
            if ed.action.value == "HOLD":
                continue

            # Determine size to close
            close_size = pos.size if ed.fraction >= 1.0 else round(pos.size * ed.fraction, 2)
            if close_size <= 0:
                continue

            close_side = Side.SELL if pos.side is Side.BUY else Side.BUY
            close_price = book.best_bid if pos.side is Side.BUY else book.best_ask
            if close_price is None:
                continue
            try:
                order = await self.execution.enter_limit(
                    market_id=pos.market_id,
                    token_id=pos.token_id,
                    side=close_side,
                    price=close_price,
                    size_shares=close_size,
                    max_chase_price=close_price,  # don't chase exits in MVP
                )
            except Exception as e:
                log.error("exit.place_failed", error=str(e),
                          market_id=pos.market_id)
                continue

            if order.filled > 0:
                pnl = (order.price - pos.avg_entry_price) * order.filled if pos.side is Side.BUY \
                      else (pos.avg_entry_price - order.price) * order.filled
                self.risk.realize_pnl(pnl)
                self.risk.record_fill(close_side is Side.BUY, order.price, order.filled)
                pos.size = max(0.0, pos.size - order.filled)
                pos.last_update = datetime.now(timezone.utc)
                audit.info("exit_filled", market_id=pos.market_id,
                           reason=ed.reason, price=order.price,
                           size=order.filled, pnl_usd=pnl,
                           paper=order.is_paper)

                # Mark hit TP so we don't repeat the same level
                if ed.action.value == "REDUCE":
                    # Heuristic: mark the closest TP as hit
                    for tp in pos.take_profit_prices:
                        if tp not in already_hit and (
                            (pos.side is Side.BUY and current >= tp) or
                            (pos.side is Side.SELL and current <= tp)
                        ):
                            already_hit.add(tp)
                            break

                if pos.size <= 0.0001:
                    del self._positions[key]
                    if pos in self.risk.state.open_positions:
                        self.risk.state.open_positions.remove(pos)
                    self._tp_hit.pop(key, None)

        self.risk.state.unrealized_pnl_usd = unrealized
        self.risk.state.peak_equity = max(
            self.risk.state.peak_equity, self.risk.state.equity
        )


def _hours_until(ts: Optional[datetime]) -> Optional[float]:
    if ts is None:
        return None
    return max(0.0, (ts - datetime.now(timezone.utc)).total_seconds() / 3600.0)
