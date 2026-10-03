"""CLI entry point.

Subcommands:
  polyagent run          — main loop (paper unless configured)
  polyagent scan-once    — one scan, print top opportunities, exit
  polyagent doctor       — check config, env, compliance gates
  polyagent kill         — set the kill switch file
  polyagent unkill       — remove the kill switch file
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console

from .config import load_settings
from .connectors import registry
from .core import compliance
from .logging_setup import setup_logging
from .runner import AgentRunner
from .types import Mode

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


def _make_data_source(platform: str, settings, live: bool):
    """Build a read/trade connector by name via the pluggable registry.

    Returns None for the default (Polymarket), letting AgentRunner build it
    with full live-trading wiring. Any other platform (e.g. ``manifold``) is
    constructed here as a read-only data source.
    """
    if not platform or platform.lower() == "polymarket":
        return None
    if not registry.is_registered(platform):
        raise typer.BadParameter(
            f"unknown platform {platform!r}. Available: {registry.available()}"
        )
    return registry.create(
        platform,
        # Polymarket wants these; other connectors ignore what they don't accept.
        private_key=settings.secrets.polymarket_private_key,
        funder_address=settings.secrets.polymarket_funder_address,
        api_key=settings.secrets.polymarket_api_key,
        api_secret=settings.secrets.polymarket_api_secret,
        api_passphrase=settings.secrets.polymarket_api_passphrase,
        live=live,
    )


@app.command()
def run(
    config: str = typer.Option("config.yaml", "-c", "--config"),
    demo: bool = typer.Option(False, "--demo", help="Use synthetic markets (no network needed)."),
    platform: str = typer.Option(
        "polymarket", "--platform",
        help="Market data source: polymarket (default), manifold, synthetic, …",
    ),
):
    """Start the agent loop."""
    settings = load_settings(config)
    setup_logging(settings.secrets.log_level, settings.logging.jsonl_path)
    data_source = None
    wallets = None
    news_fixtures = None
    if demo:
        from .connectors.news_fixtures import build_demo_news_fixtures
        from .connectors.synthetic import SyntheticConnector
        from .connectors.wallets import SyntheticWalletProvider
        settings.secrets.mode = Mode.PAPER
        data_source = SyntheticConnector()
        wallets = SyntheticWalletProvider()
        news_fixtures = build_demo_news_fixtures()
    else:
        data_source = _make_data_source(
            platform, settings, live=(settings.secrets.mode is not Mode.PAPER)
        )
    runner = AgentRunner(settings, data_source=data_source, wallets=wallets,
                         news_fixtures=news_fixtures)
    try:
        asyncio.run(runner.start())
    except KeyboardInterrupt:
        runner.stop()


@app.command("scan-once")
def scan_once(
    config: str = typer.Option("config.yaml", "-c", "--config"),
    demo: bool = typer.Option(False, "--demo", help="Use synthetic markets (no network needed)."),
    platform: str = typer.Option(
        "polymarket", "--platform",
        help="Market data source: polymarket (default), manifold, synthetic, …",
    ),
):
    """Run one scan, print the top 10 opportunities, exit. Read-only:
    no orders are placed even if MODE=AUTO_TRADING."""
    settings = load_settings(config)
    setup_logging(settings.secrets.log_level, settings.logging.jsonl_path)
    # Force paper for one-shot scanning to be safe
    settings.secrets.mode = Mode.PAPER
    data_source = None
    wallets = None
    news_fixtures = None
    if demo:
        from .connectors.news_fixtures import build_demo_news_fixtures
        from .connectors.synthetic import SyntheticConnector
        from .connectors.wallets import SyntheticWalletProvider
        data_source = SyntheticConnector()
        wallets = SyntheticWalletProvider()
        news_fixtures = build_demo_news_fixtures()
    else:
        # Read-only scan: never request live trading regardless of platform.
        data_source = _make_data_source(platform, settings, live=False)
    runner = AgentRunner(settings, data_source=data_source, wallets=wallets,
                         news_fixtures=news_fixtures)

    async def _go():
        await runner.db.init()
        scanned = await runner.scanner.scan()
        from .dashboard.cli import render_opportunities
        all_opps = []
        sem = asyncio.Semaphore(settings.agent.max_concurrent_scans)
        results = await asyncio.gather(
            *[runner._evaluate_market(sem, sm.market) for sm in scanned],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, list):
                all_opps.extend(r)
        console.print(render_opportunities(all_opps, top=10))
        await runner.connector.stop()
        await runner.news.stop()
        await runner.db.close()

    asyncio.run(_go())


@app.command()
def doctor(
    config: str = typer.Option("config.yaml", "-c", "--config"),
):
    """Validate config and compliance state."""
    try:
        settings = load_settings(config)
    except Exception as e:
        console.print(f"[red]Failed to load config:[/] {e}")
        raise typer.Exit(code=2)

    console.print(f"[bold]Mode:[/] {settings.secrets.mode.value}")
    console.print(f"[bold]Database:[/] {settings.secrets.database_url}")
    console.print(f"[bold]Bankroll:[/] ${settings.risk.bankroll_usd:,.2f}")
    console.print(f"[bold]Kill switch file:[/] {settings.secrets.kill_switch_file} "
                  f"(exists={Path(settings.secrets.kill_switch_file).exists()})")
    console.print()

    blocks = compliance.block_reasons(settings)
    if blocks:
        console.print("[yellow]Compliance gate would block live trading:[/]")
        for r in blocks:
            console.print(f"  - {r}")
    else:
        console.print("[green]Compliance gate: OK[/]")
    if settings.secrets.mode is not Mode.PAPER and blocks:
        console.print("[red]Live mode requested but compliance blocks. Will fall back "
                      "to PAPER on `run`.[/]")
    raise typer.Exit(code=0 if not blocks or settings.secrets.mode is Mode.PAPER else 1)


@app.command()
def kill(
    config: str = typer.Option("config.yaml", "-c", "--config"),
    reason: str = typer.Option("manual kill", "--reason"),
):
    """Trip the kill switch."""
    settings = load_settings(config)
    p = Path(settings.secrets.kill_switch_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(reason)
    console.print(f"[red]Kill switch tripped:[/] {p} ({reason})")


@app.command()
def unkill(
    config: str = typer.Option("config.yaml", "-c", "--config"),
):
    """Remove the kill switch."""
    settings = load_settings(config)
    p = Path(settings.secrets.kill_switch_file)
    if p.exists():
        p.unlink()
        console.print(f"[green]Kill switch cleared:[/] {p}")
    else:
        console.print("Kill switch was not active.")


if __name__ == "__main__":
    app()
