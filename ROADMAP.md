# Roadmap

PolyAgent is built around small, pluggable seams, so the roadmap is mostly a
list of **self-contained, parallelizable** pieces. Many are great first
contributions — grab one, open an issue to claim it, and go.

Legend: 🟢 good first issue · 🟡 intermediate · 🔴 larger / design needed

## Connectors (the pluggable seam)

Each is one new file implementing `BaseConnector`. Copy
`agent/connectors/manifold.py` and follow [`docs/adding-a-connector.md`](docs/adding-a-connector.md).

- 🟢 **Kalshi** connector (regulated US exchange; public market data API)
- 🟢 **PredictIt** connector (public `/api/marketdata/all` feed)
- 🟢 **Metaculus** connector (forecasting questions; public API)
- 🟡 **Limitless / Insight** and other onchain books
- 🟡 **Manifold: multiple-choice markets** — today only BINARY is mapped
- 🟡 **Manifold: live betting** — implement `place_limit_order` against
  `POST /v0/bet` (needs a Manifold API key)
- 🟡 **Manifold: exact cpmm-1 book** — replace the approximate `_derive_book`
  with the real constant-product price curve from the pool

## Models & signals

- 🟢 Add a **Brier score / calibration** metric to the backtester
- 🟡 Category-specific probability models (sports, macro, crypto) behind the
  existing `probability.estimate` interface
- 🟡 Wire the **LLM rule-reader** end-to-end (the seam exists in
  `agent/llm/rule_reader.py`; pass an `llm_caller`)
- 🔴 Cross-market arbitrage signal (same event on Polymarket vs Kalshi vs
  Manifold) — now unlocked because multiple connectors share one `Market` type

## Dashboard & ops

- 🟡 **Wire the web API to real connectors** — `agent/web/api.py` currently
  serves demo data; make `/api/markets`, `/api/orderbook`, `/api/scan` call the
  real connector (read-only) with the demo fallback, selectable by `?platform=`
- 🟢 **Alerting** — Telegram/Discord webhook when an `ENTER` opportunity fires
- 🟢 Add a **screenshot/GIF** of the dashboard to the README
- 🟡 Persist scan history + a PnL-over-time chart
- 🟡 One-command `docker compose up` verified end-to-end

## Housekeeping

- 🟢 Modernize type hints to PEP 604 (`X | None`) and enable ruff `UP` rules
- 🟢 Expand test coverage for the `core/` engines
- 🟡 Reconcile `requirements*.txt` with `pyproject.toml` as the single source
  of truth

Have an idea that isn't here? Open a feature request.
