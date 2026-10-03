"""End-to-end smoke test for the demo configuration.

Locks in the contract: with the synthetic connector, synthetic wallet
provider, and news fixtures all wired in, at least one market produces
an ENTER decision and at least one no-news market correctly produces
NO_TRADE. This catches regressions in the probability engine, decision
gates, and orientation logic in one pass.
"""
from __future__ import annotations

import asyncio

import pytest

from agent.config import load_settings
from agent.connectors.news_fixtures import build_demo_news_fixtures
from agent.connectors.synthetic import SyntheticConnector
from agent.connectors.wallets import SyntheticWalletProvider
from agent.runner import AgentRunner
from agent.types import Decision, Mode


@pytest.mark.asyncio
async def test_demo_pipeline_yields_at_least_one_enter():
    settings = load_settings("config.yaml")
    settings.secrets.mode = Mode.PAPER
    runner = AgentRunner(
        settings,
        data_source=SyntheticConnector(),
        wallets=SyntheticWalletProvider(),
        news_fixtures=build_demo_news_fixtures(),
    )
    await runner.db.init()
    try:
        scanned = await runner.scanner.scan()
        sem = asyncio.Semaphore(8)
        results = await asyncio.gather(
            *[runner._evaluate_market(sem, sm.market) for sm in scanned]
        )
        all_opps = [o for batch in results for o in batch]

        # Demo must produce at least one ENTER from market+signal alignment.
        enters = [o for o in all_opps if o.decision is Decision.ENTER]
        assert enters, (
            "Demo configuration produced no ENTER decisions. "
            f"Decisions: {[(o.market.market_id, o.outcome.name, o.decision.value) for o in all_opps]}"
        )

        # The Fed market is the strongest demo signal; lock in that it enters.
        fed_enters = [o for o in enters if o.market.market_id == "0xfed24"]
        assert fed_enters, "Fed market should ENTER given dovish news + smart-money flow"

        # Ambiguous and no-news markets must be NO_TRADE.
        ambig = [o for o in all_opps if o.market.market_id == "0xambig01"]
        assert ambig and all(o.decision is Decision.NO_TRADE for o in ambig)
    finally:
        await runner.connector.stop()
        await runner.news.stop()
        await runner.db.close()
