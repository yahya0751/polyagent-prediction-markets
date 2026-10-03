"""Offline smoke test — uses the SyntheticConnector, no network or keys.

Runs one full scan/decision cycle end-to-end so you can verify the install
without needing API access. Equivalent to:

    polyagent scan-once --demo

Usage:
    python scripts/smoke_paper.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rich.console import Console  # noqa: E402

from agent.config import load_settings  # noqa: E402
from agent.connectors.synthetic import SyntheticConnector  # noqa: E402
from agent.dashboard.cli import render_opportunities  # noqa: E402
from agent.logging_setup import setup_logging  # noqa: E402
from agent.runner import AgentRunner  # noqa: E402
from agent.types import Mode  # noqa: E402


async def main() -> None:
    settings = load_settings(str(ROOT / "config.yaml"))
    settings.secrets.mode = Mode.PAPER
    setup_logging(settings.secrets.log_level, settings.logging.jsonl_path)

    runner = AgentRunner(settings, data_source=SyntheticConnector())
    await runner.db.init()
    scanned = await runner.scanner.scan()

    sem = asyncio.Semaphore(settings.agent.max_concurrent_scans)
    results = await asyncio.gather(
        *[runner._evaluate_market(sem, sm.market) for sm in scanned],
        return_exceptions=True,
    )
    all_opps = [o for r in results if isinstance(r, list) for o in r]

    Console().print(render_opportunities(all_opps, top=10))

    await runner.connector.stop()
    await runner.news.stop()
    await runner.db.close()


if __name__ == "__main__":
    asyncio.run(main())
