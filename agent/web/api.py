"""
PolyAgent Web API — FastAPI backend.

Design contract:
  * Demo / paper-trading is the default. No live trading is ever initiated
    from this layer.
  * Missing API keys are NEVER fatal. Endpoints fall back to mocked data.
  * Existing CLI in agent/main.py is untouched; we only *try* to import
    optional helpers from agent.core, agent.connectors, etc., and fall back
    to deterministic demo data if anything is unavailable.
"""

from __future__ import annotations

import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Optional .env loading. Never fail if dotenv isn't installed.
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except Exception:
    pass


# ---------------------------------------------------------------------------
# Optional integrations. Anything that fails to import → degrade to demo.
# ---------------------------------------------------------------------------
_HAS_CORE = False
try:
    # Best-effort import; CLI runs fine without these on the web side.
    from agent.core import scanner as _core_scanner  # type: ignore  # noqa: F401

    _HAS_CORE = True
except Exception:
    _HAS_CORE = False


# ---------------------------------------------------------------------------
# App + CORS
# ---------------------------------------------------------------------------
app = FastAPI(
    title="PolyAgent Terminal API",
    version="0.1.0",
    description="Backend for the PolyAgent dark-cyber trading dashboard.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev-only default; tighten in prod
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# In-memory state (kill switch, last scan time)
# ---------------------------------------------------------------------------
class _State:
    kill_switch: bool = False
    last_scan_ts: float | None = None


STATE = _State()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ai_enabled() -> bool:
    """AI is enabled iff at least one supported key is present and non-empty."""
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        val = os.getenv(key, "").strip()
        if val:
            return True
    return False


def _mode() -> str:
    """Current trading mode. Defaults to PAPER_TRADING."""
    mode = os.getenv("POLYAGENT_MODE", "").strip().upper()
    if mode in {"LIVE", "REAL"}:
        # We deliberately *do not* honor LIVE from the web layer.
        # Live trading must be enabled through the CLI / explicit code path.
        return "PAPER_TRADING"
    return "PAPER_TRADING"


# ---------------------------------------------------------------------------
# Mock data generators (deterministic-ish, but with movement)
# ---------------------------------------------------------------------------
DEMO_MARKETS = [
    {
        "id": "mkt_001",
        "slug": "us-recession-2026",
        "title": "US recession declared in 2026?",
        "category": "Macro",
        "yes_price": 0.34,
        "no_price": 0.66,
        "volume_24h": 1_842_300,
        "liquidity": 612_000,
        "ends_at": "2026-12-31T23:59:00Z",
    },
    {
        "id": "mkt_002",
        "slug": "btc-150k-eoy",
        "title": "BTC closes above $150k by year-end?",
        "category": "Crypto",
        "yes_price": 0.28,
        "no_price": 0.72,
        "volume_24h": 3_120_700,
        "liquidity": 980_400,
        "ends_at": "2026-12-31T23:59:00Z",
    },
    {
        "id": "mkt_003",
        "slug": "fed-cut-june",
        "title": "Fed cuts rates at June FOMC?",
        "category": "Macro",
        "yes_price": 0.61,
        "no_price": 0.39,
        "volume_24h": 2_044_100,
        "liquidity": 740_900,
        "ends_at": "2026-06-12T18:00:00Z",
    },
    {
        "id": "mkt_004",
        "slug": "openai-gpt6-2026",
        "title": "OpenAI ships GPT-6 in 2026?",
        "category": "Tech",
        "yes_price": 0.47,
        "no_price": 0.53,
        "volume_24h": 812_400,
        "liquidity": 305_200,
        "ends_at": "2026-12-31T23:59:00Z",
    },
    {
        "id": "mkt_005",
        "slug": "champions-league-rm",
        "title": "Real Madrid wins UCL 2025/26?",
        "category": "Sports",
        "yes_price": 0.22,
        "no_price": 0.78,
        "volume_24h": 433_900,
        "liquidity": 154_000,
        "ends_at": "2026-05-30T20:00:00Z",
    },
]


def _price_series(seed: int, n: int = 96, base: float = 0.34) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    series = []
    p = base
    now = int(time.time())
    for i in range(n):
        # Random-walk with mean reversion toward base.
        drift = (base - p) * 0.04
        p = max(0.01, min(0.99, p + drift + rng.uniform(-0.012, 0.012)))
        series.append(
            {
                "t": now - (n - i) * 900,  # 15-min candles
                "p": round(p, 4),
            }
        )
    return series


def _orderbook(mid: float) -> dict[str, list[dict[str, float]]]:
    rng = random.Random(int(mid * 10_000))
    bids = []
    asks = []
    for i in range(1, 9):
        bid_p = round(max(0.01, mid - i * 0.005 - rng.uniform(0, 0.002)), 4)
        ask_p = round(min(0.99, mid + i * 0.005 + rng.uniform(0, 0.002)), 4)
        bids.append({"price": bid_p, "size": round(rng.uniform(200, 4500), 1)})
        asks.append({"price": ask_p, "size": round(rng.uniform(200, 4500), 1)})
    return {"bids": bids, "asks": asks}


def _demo_wallets() -> list[dict[str, Any]]:
    rng = random.Random(7)
    labels = [
        ("Whale-01", "whale"),
        ("AlphaQuant", "smart"),
        ("Sniper-Δ", "smart"),
        ("MacroDesk", "fund"),
        ("DegenRetail", "retail"),
        ("Market-Maker-A", "mm"),
        ("CT-Influencer", "influencer"),
        ("Insider?", "suspicious"),
    ]
    out = []
    for i, (name, cluster) in enumerate(labels):
        addr = "0x" + "".join(rng.choices("0123456789abcdef", k=40))
        out.append(
            {
                "address": addr,
                "label": name,
                "cluster": cluster,
                "win_rate": round(rng.uniform(0.41, 0.83), 3),
                "roi_30d": round(rng.uniform(-0.18, 0.92), 3),
                "volume_30d": int(rng.uniform(50_000, 4_500_000)),
                "skill_score": round(rng.uniform(35, 98), 1),
                "recent_trades": [
                    {
                        "market": rng.choice(DEMO_MARKETS)["title"],
                        "side": rng.choice(["YES", "NO"]),
                        "price": round(rng.uniform(0.1, 0.9), 3),
                        "size": int(rng.uniform(500, 25_000)),
                        "ts": int(time.time()) - rng.randint(60, 3 * 86400),
                    }
                    for _ in range(3)
                ],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class AnalyzeRequest(BaseModel):
    market_id: str | None = None
    question: str | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "polyagent-api",
        "version": app.version,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/status")
def status() -> dict[str, Any]:
    return {
        "mode": _mode(),
        "paper_trading": True,  # web layer never enables live
        "ai_enabled": _ai_enabled(),
        "kill_switch": STATE.kill_switch,
        "core_loaded": _HAS_CORE,
        "last_scan_ts": STATE.last_scan_ts,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/markets")
def markets() -> dict[str, Any]:
    # Slight per-call jitter so the UI feels alive.
    enriched = []
    for m in DEMO_MARKETS:
        jitter = random.uniform(-0.01, 0.01)
        yes = max(0.01, min(0.99, m["yes_price"] + jitter))
        enriched.append(
            {
                **m,
                "yes_price": round(yes, 4),
                "no_price": round(1 - yes, 4),
                "series": _price_series(seed=hash(m["id"]) & 0xFFFF, base=yes),
            }
        )
    return {"markets": enriched, "source": "demo"}


@app.get("/api/orderbook")
def orderbook(market_id: str = "mkt_001") -> dict[str, Any]:
    m = next((x for x in DEMO_MARKETS if x["id"] == market_id), DEMO_MARKETS[0])
    return {"market_id": m["id"], **_orderbook(m["yes_price"])}


@app.get("/api/scan")
def scan() -> dict[str, Any]:
    """Web equivalent of `python -m agent.main scan-once --demo`."""
    STATE.last_scan_ts = time.time()
    rng = random.Random(int(STATE.last_scan_ts))
    opportunities = []
    for m in DEMO_MARKETS:
        edge = round(rng.uniform(-0.07, 0.18), 4)
        if edge < 0.02:
            continue
        opportunities.append(
            {
                "market_id": m["id"],
                "market": m["title"],
                "side": "YES" if edge > 0 else "NO",
                "model_price": round(m["yes_price"] + edge, 4),
                "market_price": m["yes_price"],
                "edge": edge,
                "confidence": round(rng.uniform(0.45, 0.92), 3),
                "expected_value": round(edge * rng.uniform(0.6, 1.4), 4),
                "size_suggested": int(rng.uniform(50, 500)),
                "catalyst": rng.choice(
                    [
                        "CPI print Thu",
                        "Sentiment shift on CT",
                        "Whale accumulation",
                        "Liquidity imbalance",
                        "Cross-market arb vs Kalshi",
                    ]
                ),
                "risk": rng.choice(["LOW", "MED", "HIGH"]),
            }
        )
    opportunities.sort(key=lambda o: o["expected_value"], reverse=True)
    best = opportunities[0] if opportunities else None
    return {
        "ts": STATE.last_scan_ts,
        "mode": _mode(),
        "best": best,
        "opportunities": opportunities,
        "source": "demo",
    }


@app.get("/api/wallets")
def wallets() -> dict[str, Any]:
    ws = _demo_wallets()
    # Edges between wallets — fake clusters
    edges = []
    for i in range(len(ws)):
        for j in range(i + 1, len(ws)):
            if (i + j) % 3 == 0:
                edges.append({"from": ws[i]["address"], "to": ws[j]["address"], "weight": round(random.uniform(0.1, 1.0), 2)})
    return {"wallets": ws, "edges": edges, "source": "demo"}


@app.get("/api/risk")
def risk() -> dict[str, Any]:
    # Deterministic-ish snapshot
    return {
        "daily_loss_limit_usd": 250.0,
        "daily_pnl_usd": round(random.uniform(-80, 140), 2),
        "exposure_usd": round(random.uniform(400, 2200), 2),
        "max_trade_size_usd": 200.0,
        "active_positions": random.randint(2, 7),
        "kill_switch": STATE.kill_switch,
        "paper_trading": True,
        "warnings": [
            "This is a paper-trading demo. Not financial advice.",
            "Live trading is disabled from the web layer.",
        ],
    }


@app.post("/api/kill")
def kill() -> dict[str, Any]:
    STATE.kill_switch = True
    return {"kill_switch": True, "ts": datetime.now(timezone.utc).isoformat()}


@app.post("/api/unkill")
def unkill() -> dict[str, Any]:
    STATE.kill_switch = False
    return {"kill_switch": False, "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/api/ai/status")
def ai_status() -> dict[str, Any]:
    enabled = _ai_enabled()
    return {
        "enabled": enabled,
        "provider": "anthropic" if os.getenv("ANTHROPIC_API_KEY") else ("openai" if os.getenv("OPENAI_API_KEY") else None),
        "message": (
            "AI analysis available."
            if enabled
            else "AI disabled. Add ANTHROPIC_API_KEY or OPENAI_API_KEY to .env to enable."
        ),
    }


@app.post("/api/ai/analyze")
def ai_analyze(req: AnalyzeRequest) -> dict[str, Any]:
    if not _ai_enabled():
        return {
            "enabled": False,
            "analysis": None,
            "message": (
                "AI is disabled. The dashboard is running in demo mode. "
                "Add ANTHROPIC_API_KEY or OPENAI_API_KEY to your .env to enable AI analysis."
            ),
        }

    # Real AI call attempted; any failure → graceful fallback message.
    try:
        market = next((m for m in DEMO_MARKETS if m["id"] == req.market_id), None)
        prompt = req.question or (
            f"Give a brief trading-desk style analysis of this prediction market: "
            f"{market['title'] if market else 'unspecified market'}. "
            f"Mention catalysts, edge, and confidence. Keep under 120 words."
        )

        if os.getenv("ANTHROPIC_API_KEY"):
            import anthropic  # type: ignore

            client = anthropic.Anthropic()
            msg = client.messages.create(
                model=os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(getattr(b, "text", "") for b in msg.content)
        else:
            from openai import OpenAI  # type: ignore

            client = OpenAI()
            resp = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
            )
            text = resp.choices[0].message.content or ""

        return {"enabled": True, "analysis": text.strip(), "message": "ok"}
    except Exception as e:  # never crash the dashboard
        return {
            "enabled": True,
            "analysis": None,
            "message": f"AI call failed gracefully: {type(e).__name__}. Dashboard continues in demo mode.",
        }


# ---------------------------------------------------------------------------
# Entrypoint for `python -m agent.web.api`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "agent.web.api:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=bool(os.getenv("API_RELOAD", "")),
    )
