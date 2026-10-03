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
# Real engine, imported WITHOUT the DB/runner layer so the web app stays light
# and never needs SQLAlchemy. Anything that fails to import → degrade to demo.
# ---------------------------------------------------------------------------
import asyncio

_HAS_CORE = False
try:
    from ..config import load_settings
    from ..connectors import registry
    from ..connectors.base import BaseConnector
    from ..core import decision as _decision
    from ..core import orderbook as _ob
    from ..core import probability as _probability
    from ..core.market_scanner import MarketScanner
    from ..llm.rule_reader import RuleReader
    from ..types import Side, TradeOpportunity

    _HAS_CORE = True
except Exception:  # pragma: no cover - degrade gracefully if engine unavailable
    _HAS_CORE = False


# Default platform for the dashboard. Manifold needs no API keys, so it works
# for anyone (including a public hosted demo). Override via env.
DEFAULT_PLATFORM = os.getenv("POLYAGENT_WEB_PLATFORM", "manifold").strip().lower()

# How many markets to surface in the dashboard list.
WEB_MARKET_LIMIT = int(os.getenv("POLYAGENT_WEB_MARKET_LIMIT", "8"))

# Cached settings + one connector instance per platform (reuses HTTP pools).
_SETTINGS = None
_CONNECTORS: dict[str, "BaseConnector"] = {}
# Tiny TTL cache so dashboard polling doesn't hammer upstream APIs.
_TTL_CACHE: dict[str, tuple[float, Any]] = {}


def _settings():
    global _SETTINGS
    if _SETTINGS is None and _HAS_CORE:
        try:
            _SETTINGS = load_settings("config.yaml")
        except Exception:
            _SETTINGS = None
    return _SETTINGS


def _get_connector(platform: str):
    """Return a cached, keyless, read-only connector for the platform."""
    platform = (platform or DEFAULT_PLATFORM).strip().lower()
    if not _HAS_CORE or not registry.is_registered(platform):
        return None
    if platform not in _CONNECTORS:
        _CONNECTORS[platform] = registry.create(
            platform,
            # Polymarket accepts these; others ignore what they don't take.
            private_key="", funder_address="", api_key="", api_secret="",
            api_passphrase="", live=False,
        )
    return _CONNECTORS[platform]


async def _cached(key: str, ttl: float, factory):
    now = time.time()
    hit = _TTL_CACHE.get(key)
    if hit is not None and now - hit[0] < ttl:
        return hit[1]
    value = await factory()
    _TTL_CACHE[key] = (now, value)
    return value


def _hours_until(ts) -> float | None:
    if ts is None:
        return None
    return max(0.0, (ts - datetime.now(timezone.utc)).total_seconds() / 3600.0)


def _target_size_usd() -> float:
    s = _settings()
    if s is None:
        return 100.0
    return max(s.risk.min_position_usd, s.risk.max_position_pct_bankroll * s.risk.bankroll_usd)


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
# Live data — real connectors + real decision engine (read-only)
# ---------------------------------------------------------------------------
def _yes_outcome(market):
    return next(
        (o for o in market.outcomes if o.name.strip().lower() in ("yes", "true")),
        market.outcomes[0],
    )


async def _live_markets(platform: str, limit: int) -> list[dict[str, Any]]:
    conn = _get_connector(platform)
    if conn is None:
        return []
    markets = await conn.list_markets(limit=max(limit, 50))
    # Surface the meatiest markets first.
    markets.sort(key=lambda m: (m.liquidity_usd, m.volume_usd), reverse=True)
    markets = markets[:limit]

    async def _enrich(m) -> dict[str, Any]:
        yes = _yes_outcome(m)
        try:
            hist = await conn.get_price_history(yes.token_id, limit=150)
        except Exception:
            hist = []
        series = [{"t": pt.t, "p": pt.p} for pt in hist]
        if not series:
            # No fabricated history — show the one real point we have.
            series = [{"t": int(time.time()), "p": round(yes.price, 4)}]
        return {
            "id": m.market_id,
            "slug": m.slug,
            "title": m.question,
            "category": (m.category or "—").title(),
            "yes_price": round(yes.price, 4),
            "no_price": round(1 - yes.price, 4),
            "volume_24h": int(m.volume_usd),
            "liquidity": int(m.liquidity_usd),
            "ends_at": m.close_time.isoformat() if m.close_time else None,
            "series": series,
        }

    return list(await asyncio.gather(*[_enrich(m) for m in markets]))


async def _live_orderbook(platform: str, market_id: str) -> dict[str, Any] | None:
    conn = _get_connector(platform)
    if conn is None or not market_id:
        return None
    m = await conn.get_market(market_id)
    if m is None or not m.outcomes:
        return None
    yes = _yes_outcome(m)
    book = await conn.get_order_book(yes.token_id)
    if book is None:
        return None
    return {
        "market_id": market_id,
        "bids": [{"price": round(lv.price, 4), "size": round(lv.size, 2)} for lv in book.bids],
        "asks": [{"price": round(lv.price, 4), "size": round(lv.size, 2)} for lv in book.asks],
        "source": platform,
    }


async def _live_scan(platform: str, limit: int) -> dict[str, Any] | None:
    conn = _get_connector(platform)
    s = _settings()
    if conn is None or s is None:
        return None

    scanner = MarketScanner(conn, top_n=limit)
    scanned = await scanner.scan()
    reader = RuleReader()
    size = _target_size_usd()

    async def _eval(sm):
        m = sm.market
        yes = _yes_outcome(m)
        book = await conn.get_order_book(yes.token_id)
        if book is None or book.best_bid is None or book.best_ask is None:
            return None
        ba = _ob.analyze(book, Side.BUY, size, s.decision.max_slippage_pct)
        if ba is None:
            return None
        rules = await reader.read(m)
        prob = _probability.estimate(
            market_implied=yes.price,
            side_is_yes=True,
            resolution_clarity=rules.resolution_clarity,
            time_to_close_hours=_hours_until(m.close_time),
        )
        opp = TradeOpportunity(
            market=m, outcome=yes, side=Side.BUY, book=book, probability=prob,
            spread=ba.spread, slippage_pct=ba.slippage_pct,
            max_fill_usd=ba.max_fill_usd_at_target_slippage,
            liquidity_quality=ba.liquidity_quality,
            resolution_clarity=rules.resolution_clarity,
            source_credibility=0.6, wallet_signal=0.0, catalyst_strength=0.0,
            manipulation_risk=ba.manipulation_risk, correlation_risk=0.0,
        )
        _decision.evaluate(opp, s.decision)
        return opp

    results = await asyncio.gather(*[_eval(sm) for sm in scanned], return_exceptions=True)
    opps = [r for r in results if _HAS_CORE and isinstance(r, TradeOpportunity)]

    rows: list[dict[str, Any]] = []
    for o in opps:
        if o.manipulation_risk < 0.3 and o.liquidity_quality > 0.6:
            risk = "LOW"
        elif o.manipulation_risk > 0.6:
            risk = "HIGH"
        else:
            risk = "MED"
        enters = o.decision.value == "ENTER"
        rows.append({
            "market_id": o.market.market_id,
            "market": o.market.question,
            "side": "YES",
            "model_price": round(o.probability.estimated_prob, 4),
            "market_price": round(o.probability.market_implied_prob, 4),
            "edge": round(o.probability.edge, 4),
            "confidence": round(o.probability.confidence, 3),
            "expected_value": round(o.probability.edge * o.probability.confidence, 4),
            "size_suggested": int(size) if enters else 0,
            "catalyst": f"resolution clarity {o.resolution_clarity:.0%} · no news feed",
            "risk": risk,
            "decision": o.decision.value,
        })

    rows.sort(key=lambda r: r["expected_value"], reverse=True)
    best = next((r for r in rows if r["edge"] > 0 and r["decision"] != "NO_TRADE"), None)
    return {
        "ts": STATE.last_scan_ts,
        "mode": _mode(),
        "best": best,
        "opportunities": rows,
        "source": platform,
    }


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
        "live_data": _HAS_CORE,  # real connectors wired when core loaded
        "platform": DEFAULT_PLATFORM,
        "last_scan_ts": STATE.last_scan_ts,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/platforms")
def platforms() -> dict[str, Any]:
    """Connectors available to the dashboard (from the pluggable registry)."""
    avail = ["manifold"]
    if _HAS_CORE:
        try:
            avail = registry.available()
        except Exception:
            pass
    return {"platforms": avail, "default": DEFAULT_PLATFORM}


@app.get("/api/markets")
async def markets(platform: str = DEFAULT_PLATFORM) -> dict[str, Any]:
    if _HAS_CORE:
        try:
            live = await _cached(
                f"markets:{platform}:{WEB_MARKET_LIMIT}", 20.0,
                lambda: _live_markets(platform, WEB_MARKET_LIMIT),
            )
            if live:
                return {"markets": live, "source": platform}
        except Exception as e:
            print(f"[markets] live fetch failed, using demo: {e}")

    # Demo fallback — slight per-call jitter so the UI feels alive.
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
async def orderbook(market_id: str = "", platform: str = DEFAULT_PLATFORM) -> dict[str, Any]:
    if _HAS_CORE and market_id:
        try:
            live = await _cached(
                f"ob:{platform}:{market_id}", 10.0,
                lambda: _live_orderbook(platform, market_id),
            )
            if live:
                return live
        except Exception as e:
            print(f"[orderbook] live fetch failed, using demo: {e}")

    m = next((x for x in DEMO_MARKETS if x["id"] == market_id), DEMO_MARKETS[0])
    return {"market_id": m["id"], **_orderbook(m["yes_price"]), "source": "demo"}


@app.get("/api/scan")
async def scan(platform: str = DEFAULT_PLATFORM) -> dict[str, Any]:
    """Real decision pipeline (scanner → probability → decision), read-only.
    Falls back to a synthetic demo scan if the engine/connector is unavailable.
    """
    STATE.last_scan_ts = time.time()
    if _HAS_CORE:
        try:
            live = await _cached(
                f"scan:{platform}", 20.0, lambda: _live_scan(platform, 12)
            )
            if live is not None:
                return live
        except Exception as e:
            print(f"[scan] live scan failed, using demo: {e}")

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
