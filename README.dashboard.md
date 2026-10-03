# PolyAgent Terminal — Web Dashboard

A dark-cyber prediction-market trading dashboard layered on top of the existing
PolyAgent CLI. The CLI is **untouched** — the web app is purely additive.

> **Default mode is PAPER_TRADING / DEMO.** No real orders are submitted from
> the web layer. Live trading must be initiated explicitly through the CLI.

---

## Quick start

```bash
# 1. Copy the env template (optional — the dashboard runs without a real .env)
cp .env.example .env

# 2. Build and start backend + frontend
docker compose up --build

# 3. Open the dashboard
#    Frontend: http://localhost:3000
#    Backend:  http://localhost:8000/api/health
```

Stop with `Ctrl+C` and `docker compose down`.

---

## Files added / changed

```
agent/web/__init__.py             # NEW — web subpackage marker
agent/web/api.py                  # NEW — FastAPI app, demo-safe endpoints

web/                              # NEW — React + Vite + Tailwind frontend
├── index.html
├── package.json
├── postcss.config.js
├── tailwind.config.js
├── vite.config.js
├── public/favicon.svg
└── src/
    ├── main.jsx
    ├── App.jsx
    ├── index.css
    ├── lib/
    │   ├── api.js
    │   └── fmt.js
    └── components/
        ├── Header.jsx
        ├── AgentCard.jsx
        ├── Chart.jsx
        ├── OrderBook.jsx
        ├── SignalPanel.jsx
        ├── WalletGraph.jsx
        ├── TradesTable.jsx
        ├── RiskPanel.jsx
        └── AIPanel.jsx

Dockerfile.backend                # NEW — FastAPI container
Dockerfile.frontend               # NEW — Vite dev container
docker-compose.yml                # NEW — orchestrates both
requirements-web.txt              # NEW — fastapi, uvicorn, anthropic, openai
.env.example                      # UPDATED — documents AI keys
.dockerignore                     # NEW
```

The original `Dockerfile`, `requirements.txt`, `agent/main.py`, `agent/runner.py`,
and the rest of the CLI are **not modified**.

---

## New dependencies

**Python (backend, in `requirements-web.txt`):**
- `fastapi` — REST API
- `uvicorn[standard]` — ASGI server
- `pydantic` — request schemas
- `python-dotenv` — load `.env`
- `anthropic`, `openai` — optional, only invoked when a key is present

**JavaScript (frontend, in `web/package.json`):**
- `react`, `react-dom`
- `vite`, `@vitejs/plugin-react`
- `tailwindcss`, `postcss`, `autoprefixer`
- `recharts` — for the price chart (the wallet graph is hand-rolled SVG, no extra dep)

---

## Running

### With Docker (recommended)

```bash
docker compose up --build
```

- Frontend → http://localhost:3000
- Backend  → http://localhost:8000

The CLI still works inside the backend container:

```bash
docker compose run --rm backend python -m agent.main scan-once --demo
docker compose run --rm backend python -m agent.main run --demo
docker compose run --rm backend python -m agent.main doctor
```

### Without Docker (local dev)

```bash
# Backend
pip install -r requirements.txt          # if you have one
pip install -r requirements-web.txt
uvicorn agent.web.api:app --reload --port 8000

# Frontend (separate terminal)
cd web
npm install
npm run dev
```

---

## How to test the dashboard

1. **Visit** http://localhost:3000.
2. **Header** — confirm `MODE: PAPER_TRADING · DEMO`, the UTC clock ticks each
   second, AI status and Kill Switch are visible.
3. **Chart** — click between market tabs at the top of the chart card; the
   selected market drives the agent card, order book, and AI panel.
4. **Run scan** — click `RESCAN` in the Best Signal panel (top-left, below the
   agent card). The Recent Trades table updates from the new opportunities.
5. **Order book** — bids glow green on the right, asks glow red on top, with
   the spread/mid bar in the middle. It refreshes every 4s.
6. **Wallet intelligence** — hover any node; the bottom panel shows that
   wallet's win rate, ROI, volume, and skill score. Edges between related
   wallets brighten on hover.
7. **Risk panel** — verify the daily-loss usage and exposure bars render. Hit
   `ENGAGE KILL SWITCH`; the header chip flips to `KILL ENGAGED` (red,
   pulsing). Hit `RESET` to clear it.
8. **API smoke test:**
   ```bash
   curl http://localhost:8000/api/health
   curl http://localhost:8000/api/status
   curl http://localhost:8000/api/markets | head -c 400
   curl -X POST http://localhost:8000/api/kill
   curl -X POST http://localhost:8000/api/unkill
   ```

---

## How to confirm AI is disabled safely

When **no** `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` is set:

- `GET /api/ai/status` returns:
  ```json
  { "enabled": false, "provider": null,
    "message": "AI disabled. Add ANTHROPIC_API_KEY or OPENAI_API_KEY to .env to enable." }
  ```
- `POST /api/ai/analyze` returns a clean message — **never** an error or 500.
- The dashboard header shows `AI: DISABLED`.
- The AI panel (right column, bottom) renders the dashed "AI Analysis Disabled"
  card with instructions for adding a key. No input field is shown.
- All other endpoints (`/markets`, `/scan`, `/wallets`, `/risk`, `/orderbook`)
  return demo data and the rest of the dashboard remains fully functional.

To verify with no keys at all:
```bash
rm -f .env
touch .env
docker compose up --build
# Header shows AI: DISABLED, AI panel shows the disabled card.
```

To enable, add **one** key to `.env` and restart the backend container:
```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' >> .env
docker compose restart backend
```

---

## How to confirm no live trading is enabled

- `GET /api/status` always returns `"paper_trading": true` and
  `"mode": "PAPER_TRADING"`, **even if** `POLYAGENT_MODE=LIVE` is set in
  `.env`. The backend explicitly clamps the mode in `agent/web/api.py::_mode()`.
- `docker-compose.yml` hard-codes `POLYAGENT_MODE: "PAPER_TRADING"` for the
  backend service.
- There is **no** `/api/order`, `/api/buy`, `/api/sell`, or any execution
  endpoint. The "Execute (paper)" button in the Signal panel is intentionally
  disabled (`<button disabled>`).
- The footer on every page reads `paper-trading only · not financial advice`.

If you want to verify in code: search for `_mode` in `agent/web/api.py` — it
unconditionally returns `"PAPER_TRADING"` regardless of the env value.

---

## Endpoint reference

| Method | Path                | Purpose                                              |
|-------:|---------------------|------------------------------------------------------|
|   GET  | `/api/health`       | Liveness probe                                       |
|   GET  | `/api/status`       | Mode, paper-trading, AI enabled, kill switch, etc.   |
|   GET  | `/api/markets`      | Demo markets with price series                       |
|   GET  | `/api/orderbook`    | Order book for a market (`?market_id=...`)           |
|   GET  | `/api/scan`         | Web equivalent of `scan-once --demo`                 |
|   GET  | `/api/wallets`      | Wallet intelligence (nodes + edges)                  |
|   GET  | `/api/risk`         | Risk dashboard data                                  |
|  POST  | `/api/kill`         | Engage kill switch                                   |
|  POST  | `/api/unkill`       | Clear kill switch                                    |
|   GET  | `/api/ai/status`    | Whether an AI key is configured                      |
|  POST  | `/api/ai/analyze`   | AI analysis (graceful no-op if key missing)          |

---

## Notes for OT/ICS-style review

- **Layered defense:** the web layer is read-only with respect to trading. Any
  future "live" path must be added to a separate, explicit code path with its
  own access control — mirroring an IT/OT zone boundary.
- **Fail-safe defaults:** missing env, missing keys, and unreachable
  upstreams all degrade to demo data rather than throwing.
- **Kill switch:** server-side state, exposed via two distinct endpoints,
  surfaced visibly in the header at all times.
