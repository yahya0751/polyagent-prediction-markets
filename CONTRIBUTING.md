# Contributing to PolyAgent

Thanks for your interest! PolyAgent is designed to be easy to extend — the
whole architecture is built around small, pluggable seams, so most
contributions touch one file and no engine code.

> **Before anything else:** read [`SECURITY.md`](SECURITY.md). Never commit a
> private key, API secret, or a real `.env`. The default mode is paper trading
> and contributions must keep it that way.

## Quick start

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate       Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"

# Offline demo — no keys, no network:
python -m agent.main scan-once --demo

# Real data, read-only, no keys needed (Manifold's public API):
python -m agent.main scan-once --platform manifold

pytest -q          # run the tests
ruff check .       # lint (and `ruff check . --fix` to auto-fix)
```

## The golden path for a first PR: add a connector

PolyAgent treats every prediction-market platform as a `BaseConnector`
(`agent/connectors/base.py`) — six methods, no engine changes. Adding one is
the most valuable and self-contained contribution you can make.

See the step-by-step guide: [`docs/adding-a-connector.md`](docs/adding-a-connector.md).
The Manifold connector (`agent/connectors/manifold.py`) is a complete,
tested worked example you can copy.

Platforms people have asked for: **Kalshi, PredictIt, Metaculus, Insight,
Limitless**. Pick one, open a "New connector" issue, and go.

## What makes a good PR

- **Tests.** New connectors/parsers must have offline unit tests
  (use `httpx.MockTransport` and recorded JSON fixtures — see
  `tests/test_manifold_connector.py`). No test should hit the network.
- **Lint clean.** `ruff check .` must pass. Our enforced rule set is
  intentionally focused (`E`, `F`, `I`); see `pyproject.toml`.
- **Safety preserved.** Read paths may call public APIs. Write/trade paths
  must stay gated behind the existing compliance + mode + kill-switch checks.
- **Small and focused.** One connector, one model, or one fix per PR.

## Project layout

```
agent/
  connectors/   polymarket, manifold, synthetic, paper, news, wallets, social
                + registry.py (the pluggable seam) + base.py (the interface)
  core/         scanner, orderbook, probability, decision, execution, risk,
                exits, compliance, backtest
  llm/          rule_reader (heuristic + LLM-pluggable)
  storage/      SQLAlchemy models + async DB
  web/          FastAPI backend for the dashboard
web/            React + Vite + Tailwind dashboard
tests/          pytest suite (offline, deterministic)
```

## Development notes

- Everything crossing a module boundary is a pydantic model (`agent/types.py`)
  so mismatches fail at parse time, not trade time.
- Connectors must never raise out of a scan loop; parse failures return
  `None` and are logged. Follow the pattern in the existing connectors.
- Async tests use `@pytest.mark.asyncio`.

## Code of Conduct

By participating you agree to abide by our
[Code of Conduct](CODE_OF_CONDUCT.md).
