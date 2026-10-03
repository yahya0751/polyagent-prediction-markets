# PolyAgent — Prediction Market Trading Agent

[![CI](https://github.com/yahya0751/polyagent-prediction-markets/actions/workflows/ci.yml/badge.svg)](https://github.com/yahya0751/polyagent-prediction-markets/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

An autonomous/semi-autonomous trading agent for Polymarket, Manifold, and other prediction markets, with strict risk controls, paper-trading by default, and pluggable connectors.

> **Disclaimer.** This is software, not financial advice. Prediction markets are restricted in many jurisdictions (incl. parts of the US for Polymarket). You are solely responsible for compliance with platform terms of service and local law. The default mode is `PAPER_TRADING`. Live trading requires explicit configuration and is gated behind multiple safety flags.

## Modes

- `PAPER_TRADING` — fully simulated. No keys required.
- `MANUAL_APPROVAL` — agent proposes trades, you approve each one.
- `AUTO_TRADING` — agent places real orders. Requires API keys, a non-restricted jurisdiction, and `LIVE_TRADING_CONFIRMED=I_UNDERSTAND_THE_RISKS`.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Fully offline demo — synthetic markets, wallets, news. No keys needed.
python -m agent.main scan-once --demo
python -m agent.main run --demo

# Real data, read-only, NO KEYS NEEDED — Manifold's free public API.
python -m agent.main scan-once --platform manifold

# Live (read-only — no orders placed) against Polymarket public APIs.
python -m agent.main scan-once --platform polymarket

# Run the doctor before trying any live mode
python -m agent.main doctor

# Trip / clear the kill switch
python -m agent.main kill --reason "panic"
python -m agent.main unkill
```

## Connectors (pluggable platforms)

Every platform is a `BaseConnector` — six methods, no engine code. Connectors
self-register via a decorator and are auto-discovered:

| Platform   | Keys needed | Status                    |
|------------|-------------|---------------------------|
| `polymarket` | none for reads; keys for live | read + live trading |
| `manifold`   | **none** (free public API)   | read-only           |
| `synthetic`  | none (offline fixtures)      | read-only (demo/CI) |

```python
from agent.connectors import registry
registry.available()          # ['manifold', 'polymarket', 'synthetic']
conn = registry.create("manifold")
```

Pick a platform with `--platform`, or add your own — see
**[docs/adding-a-connector.md](docs/adding-a-connector.md)**. Adding Kalshi,
PredictIt, or Metaculus is a great first contribution.

## Wallet pipeline (the 1M+ wallet intel)

The agent ships with a streaming wallet ingestion pipeline that scales to 1M+ rows on SQLite and is Postgres-ready (point `--db` at any URL).

```bash
# Bulk-load 1,000,000 synthetic actions for stress testing
python -m agent.wallets.ingestion --synthetic 1000000

# Or load real data exported from Dune/Goldsky as CSV
python -m agent.wallets.ingestion --csv ./data/polymarket_actions.csv

# Backfill resolution + PnL on synthetic data
python -m agent.wallets.resolve_synthetic

# Compute per-wallet skill scores
python -m agent.wallets.scoring
```

The agent's live `DBWalletProvider` (in `agent/connectors/wallets.py`) reads from `wallet_actions` joined with `wallet_scores.skill` so freshly-ingested data immediately influences trade decisions, weighted by track record.

## Backtesting

The backtester replays historical ticks through the live decision and risk engines. Same code path, no order placement.

```python
from agent.config import load_settings
from agent.core.backtest import Backtester, HistoricalTick

settings = load_settings("config.yaml")
bt = Backtester(settings, fee_per_share=0.0)
result = bt.run(ticks, signal_fn=my_signals)
print(f"PnL: ${result.realized_pnl_usd:.2f}, win rate: {result.win_rate*100:.1f}%, "
      f"max drawdown: ${result.max_drawdown_usd:.2f}")
```

`HistoricalTick` carries the market, all token order books at that timestamp, and an optional `resolved_winning_token` to settle positions when the market closes.

## Layout

```
agent/
  connectors/    # polymarket, manifold, synthetic, paper, news, wallets,
                 # social + registry (pluggable seam) + base (interface)
  core/          # scanner, orderbook, probability, decision, execution,
                 # risk, exits, compliance, backtest
  wallets/       # ingestion, scoring, resolve_synthetic
  llm/           # rule_reader (heuristic + LLM-pluggable)
  storage/       # SQLAlchemy models + async DB
  dashboard/     # rich-based terminal UI
  main.py        # CLI entry point
  runner.py      # the run loop
config.yaml      # all thresholds
.env.example     # secrets template
tests/           # 38 passing tests
```

## Safety

The agent will refuse to send live orders if any of:
- `MODE != AUTO_TRADING`
- `LIVE_TRADING_CONFIRMED` not set to the exact phrase
- API keys missing
- Kill switch file present (`data/KILL_SWITCH`)
- Daily loss limit hit
- Jurisdiction in blocklist

Touch `data/KILL_SWITCH` at any time to halt all live activity immediately.

## Tests

```bash
pip install -e ".[dev]"
pytest -q        # offline, deterministic
ruff check .     # lint
```

CI (GitHub Actions) runs ruff + the test suite on Python 3.11 and 3.12 and
builds the dashboard on every push and PR.

## Contributing

PRs welcome. The architecture is built around small, pluggable seams, so most
contributions touch one file:

- **Add a connector** (Kalshi, PredictIt, Metaculus, …) — the golden first PR.
  See [docs/adding-a-connector.md](docs/adding-a-connector.md).
- Browse the [**ROADMAP**](ROADMAP.md) for 🟢 good-first-issues.
- Read [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md) first
  (never commit keys; keep paper-trading the default).
