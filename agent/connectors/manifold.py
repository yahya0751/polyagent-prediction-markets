"""Manifold Markets connector.

Manifold (https://manifold.markets) is a free, open prediction-market
platform with a fully public REST API — no auth required for reads. That
makes it the ideal *second* connector: the agent works end-to-end against
real markets with zero keys and zero cost.

This module is also the canonical worked example for the pluggable
connector architecture. If you want to add PredictIt, Kalshi, Metaculus,
or anything else, copy this file, implement the six `BaseConnector`
methods against the new API, and decorate the class with
``@register("yourplatform")``. No engine code changes. See
``docs/adding-a-connector.md``.

Endpoints used (public, documented at https://docs.manifold.markets/api):
  GET /v0/markets?limit=N      — list LiteMarket records
  GET /v0/market/{id}          — one FullMarket (adds description)

Notes / honest caveats:
  * Manifold is play-money (denominated in "mana", M$). Amounts are stored
    in the ``*_usd`` fields for interface compatibility; they are mana, not
    dollars. The decision/risk math is unit-agnostic, so this is fine for
    paper analysis.
  * Manifold is an automated market maker (cpmm-1), so there is no native
    order book. ``get_order_book`` derives an *approximate* book from the
    market probability and liquidity. Modelling the exact cpmm-1 price
    curve is a good first issue — see ROADMAP.md.
  * Only BINARY markets are mapped today. Multiple-choice support is
    another good first issue.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..logging_setup import get_logger
from ..types import Market, Order, OrderBook, OrderBookLevel, Outcome
from .base import BaseConnector
from .registry import register

log = get_logger(__name__)

API_BASE = "https://api.manifold.markets"
YES_SUFFIX = ":YES"
NO_SUFFIX = ":NO"


@register("manifold")
class ManifoldConnector(BaseConnector):
    name = "manifold"

    def __init__(
        self,
        timeout_s: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
        **_ignored: Any,
    ):
        # ``transport`` is an injection seam for offline tests (httpx.MockTransport).
        self._client = httpx.AsyncClient(base_url=API_BASE, timeout=timeout_s, transport=transport)

    @property
    def supports_live_trading(self) -> bool:
        # Manifold has a betting API, but live trading is not wired yet.
        # Implementing place/cancel against POST /v0/bet is a good first issue.
        return False

    async def stop(self) -> None:
        await self._client.aclose()

    # ---------- Market data ----------

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=0.5, max=4))
    async def _get_json(self, path: str, params: dict | None = None) -> Any:
        r = await self._client.get(path, params=params)
        r.raise_for_status()
        return r.json()

    async def list_markets(self, limit: int = 100) -> list[Market]:
        params = {"limit": min(max(1, limit), 1000)}
        try:
            data = await self._get_json("/v0/markets", params=params)
        except Exception as e:
            log.error("manifold.list_markets_failed", error=str(e))
            return []

        out: list[Market] = []
        for raw in data or []:
            m = self._parse_market(raw)
            if m is not None:
                out.append(m)
        return out

    async def get_market(self, market_id: str) -> Market | None:
        # Accept either a bare market id or a token id ("<id>:YES").
        market_id = _strip_token_suffix(market_id)
        try:
            data = await self._get_json(f"/v0/market/{market_id}")
        except Exception as e:
            log.error("manifold.get_market_failed", error=str(e), market_id=market_id)
            return None
        return self._parse_market(data)

    async def get_order_book(self, token_id: str) -> OrderBook | None:
        market_id = _strip_token_suffix(token_id)
        is_no = token_id.upper().endswith(NO_SUFFIX)
        m = await self.get_market(market_id)
        if m is None or not m.outcomes:
            return None
        outcome = next(
            (o for o in m.outcomes if o.name.upper() == ("NO" if is_no else "YES")),
            m.outcomes[0],
        )
        return self._derive_book(outcome.price, m.liquidity_usd, token_id)

    # ---------- Parsing (pure, unit-tested offline) ----------

    @staticmethod
    def _parse_market(raw: dict) -> Market | None:
        """Parse one Manifold market record into our Market type. Returns
        None for anything we can't trade (non-binary, resolved, malformed)
        rather than raising — one bad record must not kill a scan loop."""
        try:
            if not isinstance(raw, dict):
                return None
            market_id = raw.get("id")
            if not market_id:
                return None
            if raw.get("outcomeType") != "BINARY":
                # Multi-outcome support is a good first issue; skip for now.
                return None
            if raw.get("isResolved"):
                return None

            prob = _safe_float(raw.get("probability"), default=-1.0)
            if not (0.0 <= prob <= 1.0):
                return None

            yes = round(prob, 4)
            no = round(1.0 - prob, 4)
            outcomes = [
                Outcome(token_id=f"{market_id}{YES_SUFFIX}", name="Yes", price=yes),
                Outcome(token_id=f"{market_id}{NO_SUFFIX}", name="No", price=no),
            ]

            close_time = _ms_to_dt(raw.get("closeTime"))
            group_slugs = raw.get("groupSlugs") or []
            category = str(group_slugs[0]) if group_slugs else "manifold"

            # LiteMarket has no description; FullMarket does (str or rich JSON).
            rules_text = _extract_text(raw.get("textDescription") or raw.get("description") or "")

            return Market(
                market_id=str(market_id),
                slug=str(raw.get("slug", "")),
                question=str(raw.get("question", "")),
                description=rules_text,
                category=category,
                close_time=close_time,
                resolution_source="Manifold Markets",
                rules_text=rules_text,
                outcomes=outcomes,
                volume_usd=_safe_float(raw.get("volume"), 0.0),
                liquidity_usd=_safe_float(raw.get("totalLiquidity"), 0.0),
                is_active=not bool(raw.get("isResolved", False)),
                is_closed=bool(raw.get("isResolved", False)),
            )
        except Exception as e:  # pragma: no cover - defensive
            log.debug("manifold.parse_market_skipped", error=str(e))
            return None

    @staticmethod
    def _derive_book(mid: float, liquidity: float, token_id: str) -> OrderBook:
        """Approximate a 5-level book around ``mid``.

        Manifold is a cpmm-1 AMM with no real resting orders. We synthesize
        a book whose spread tightens and depth grows with liquidity, so the
        decision engine's microstructure checks (spread, slippage, fillable
        size) behave sensibly. This is a documented approximation — see the
        module docstring and ROADMAP.md for the exact-curve upgrade.
        """
        mid = max(0.01, min(0.99, mid))
        liq = max(1.0, liquidity)
        spread = 0.06 if liq < 500 else 0.03 if liq < 5000 else 0.01
        depth_base = max(25.0, min(5000.0, liq / 10.0))

        bids: list[OrderBookLevel] = []
        asks: list[OrderBookLevel] = []
        for i in range(5):
            bid_p = round(max(0.01, mid - spread / 2 - i * 0.01), 3)
            ask_p = round(min(0.99, mid + spread / 2 + i * 0.01), 3)
            size = round(depth_base * (1.0 - i * 0.12), 1)
            bids.append(OrderBookLevel(price=bid_p, size=size))
            asks.append(OrderBookLevel(price=ask_p, size=size))

        return OrderBook(
            token_id=token_id,
            bids=bids,
            asks=asks,
            timestamp=datetime.now(UTC),
        )

    # ---------- Trading (not implemented — good first issue) ----------

    async def place_limit_order(self, *args, **kwargs) -> Order:  # pragma: no cover
        raise RuntimeError(
            "ManifoldConnector is read-only. Implementing POST /v0/bet "
            "(requires a Manifold API key) is a good first issue — see ROADMAP.md."
        )

    async def cancel_order(self, order_id: str) -> bool:  # pragma: no cover
        return False

    async def list_open_orders(self) -> list[Order]:
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _strip_token_suffix(s: str) -> str:
    for suf in (YES_SUFFIX, NO_SUFFIX):
        if s.upper().endswith(suf):
            return s[: -len(suf)]
    return s


def _safe_float(v: Any, default: float) -> float:
    try:
        return float(v) if v is not None else default
    except (ValueError, TypeError):
        return default


def _ms_to_dt(v: Any) -> datetime | None:
    """Manifold timestamps are epoch milliseconds."""
    if v is None:
        return None
    try:
        return datetime.fromtimestamp(float(v) / 1000.0, tz=UTC)
    except (ValueError, TypeError, OSError):
        return None


def _extract_text(desc: Any) -> str:
    """Manifold's ``description`` can be a plain string or a TipTap/ProseMirror
    rich-text document (nested ``{type, content, text}`` nodes). Flatten either
    to plain text."""
    if not desc:
        return ""
    if isinstance(desc, str):
        return desc.strip()
    if isinstance(desc, dict):
        parts: list[str] = []
        if isinstance(desc.get("text"), str):
            parts.append(desc["text"])
        for child in desc.get("content", []) or []:
            parts.append(_extract_text(child))
        return " ".join(p for p in parts if p).strip()
    if isinstance(desc, list):
        return " ".join(_extract_text(x) for x in desc).strip()
    return ""
