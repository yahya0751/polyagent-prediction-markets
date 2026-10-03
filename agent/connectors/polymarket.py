"""Polymarket CLOB connector.

Read paths use Polymarket's public Gamma + CLOB HTTP endpoints — no auth
required. Write paths require py-clob-client (installed via the `live`
extra) plus a funded Polygon EOA.

Endpoints used (public, documented):
  GET https://gamma-api.polymarket.com/markets   — market metadata
  GET https://clob.polymarket.com/book?token_id= — order book
  GET https://clob.polymarket.com/markets/{cid}  — market + tokens

References:
  - https://docs.polymarket.com/
  - https://github.com/Polymarket/py-clob-client

Anything not strictly necessary for the MVP is fenced behind a
`supports_live_trading` flag and a runtime check.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..logging_setup import get_logger
from ..types import Market, Order, OrderBook, OrderBookLevel, Outcome, PricePoint, Side
from .base import BaseConnector
from .registry import register

log = get_logger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"


@register("polymarket")
class PolymarketConnector(BaseConnector):
    name = "polymarket"

    def __init__(
        self,
        private_key: str = "",
        funder_address: str = "",
        api_key: str = "",
        api_secret: str = "",
        api_passphrase: str = "",
        live: bool = False,
        timeout_s: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        # ``transport`` is an injection seam for offline tests (httpx.MockTransport).
        self._client = httpx.AsyncClient(timeout=timeout_s, transport=transport)
        self._private_key = private_key
        self._funder_address = funder_address
        self._api_key = api_key
        self._api_secret = api_secret
        self._api_passphrase = api_passphrase
        self._live = live and bool(private_key) and bool(funder_address)
        self._clob = None  # py_clob_client.ClobClient, lazy-init

    @property
    def supports_live_trading(self) -> bool:
        return self._live

    async def stop(self) -> None:
        await self._client.aclose()

    # ---------- Market data ----------

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=0.5, max=4))
    async def _get_json(self, url: str, params: dict | None = None) -> Any:
        r = await self._client.get(url, params=params)
        r.raise_for_status()
        return r.json()

    async def list_markets(self, limit: int = 100) -> list[Market]:
        # Gamma returns active markets by default. We page if asked for many.
        params = {
            "limit": min(limit, 500),
            "active": "true",
            "closed": "false",
            "order": "volume",
            "ascending": "false",
        }
        try:
            data = await self._get_json(f"{GAMMA_BASE}/markets", params=params)
        except Exception as e:
            log.error("polymarket.list_markets_failed", error=str(e))
            return []

        out: list[Market] = []
        for raw in data:
            m = self._parse_market(raw)
            if m is not None:
                out.append(m)
        return out

    async def get_market(self, market_id: str) -> Optional[Market]:
        try:
            data = await self._get_json(f"{GAMMA_BASE}/markets", params={"condition_ids": market_id})
        except Exception as e:
            log.error("polymarket.get_market_failed", error=str(e), market_id=market_id)
            return None
        if not data:
            return None
        return self._parse_market(data[0])

    async def get_order_book(self, token_id: str) -> Optional[OrderBook]:
        try:
            data = await self._get_json(f"{CLOB_BASE}/book", params={"token_id": token_id})
        except Exception as e:
            log.warning("polymarket.book_fetch_failed", token_id=token_id, error=str(e))
            return None

        try:
            bids = [OrderBookLevel(price=float(b["price"]), size=float(b["size"]))
                    for b in data.get("bids", [])]
            asks = [OrderBookLevel(price=float(a["price"]), size=float(a["size"]))
                    for a in data.get("asks", [])]
            bids.sort(key=lambda x: -x.price)
            asks.sort(key=lambda x: x.price)
            return OrderBook(
                token_id=token_id,
                bids=bids,
                asks=asks,
                timestamp=datetime.now(timezone.utc),
            )
        except (KeyError, ValueError, TypeError) as e:
            log.warning("polymarket.book_parse_failed", token_id=token_id, error=str(e))
            return None

    async def get_price_history(self, token_id: str, *, limit: int = 150) -> list[PricePoint]:
        """Real historical prices from the CLOB prices-history endpoint.

        Returns points already in ``{t: epoch_seconds, p: price}`` form.
        """
        try:
            data = await self._get_json(
                f"{CLOB_BASE}/prices-history",
                params={"market": token_id, "interval": "1w", "fidelity": 60},
            )
        except Exception as e:
            log.warning("polymarket.history_fetch_failed", token_id=token_id, error=str(e))
            return []
        raw = data.get("history", []) if isinstance(data, dict) else []
        points: list[PricePoint] = []
        for pt in raw:
            try:
                points.append(PricePoint(t=int(pt["t"]), p=round(float(pt["p"]), 4)))
            except (KeyError, ValueError, TypeError):
                continue
        points.sort(key=lambda p: p.t)
        if len(points) > limit:
            step = len(points) / limit
            points = [points[int(i * step)] for i in range(limit)] + points[-1:]
        return points

    # ---------- Helpers ----------

    @staticmethod
    def _parse_market(raw: dict) -> Optional[Market]:
        """Parse one Gamma market record. Returns None on malformed input
        rather than raising — bad records shouldn't kill a scan loop."""
        try:
            condition_id = raw.get("conditionId") or raw.get("condition_id")
            if not condition_id:
                return None

            # Outcomes + tokens. Gamma returns these as parallel JSON arrays
            # encoded as strings. Defensive parsing handles both.
            outcomes_raw = raw.get("outcomes")
            token_ids_raw = raw.get("clobTokenIds") or raw.get("clob_token_ids")
            outcomes_list = _maybe_parse_json_list(outcomes_raw)
            token_ids_list = _maybe_parse_json_list(token_ids_raw)

            if not outcomes_list or not token_ids_list:
                return None
            if len(outcomes_list) != len(token_ids_list):
                return None

            prices_raw = raw.get("outcomePrices") or "[]"
            prices_list = _maybe_parse_json_list(prices_raw)
            prices = [_safe_float(p, default=0.5) for p in prices_list] \
                if prices_list else [0.5] * len(outcomes_list)
            if len(prices) != len(outcomes_list):
                prices = [0.5] * len(outcomes_list)

            outcomes = [
                Outcome(token_id=str(tid), name=str(name), price=p)
                for tid, name, p in zip(token_ids_list, outcomes_list, prices)
            ]

            close_time = None
            for key in ("endDate", "endDateIso", "end_date_iso", "end_date"):
                if key in raw and raw[key]:
                    close_time = _parse_iso(raw[key])
                    break

            return Market(
                market_id=str(condition_id),
                slug=str(raw.get("slug", "")),
                question=str(raw.get("question", "")),
                description=str(raw.get("description", "")),
                category=str(raw.get("category", "uncategorized")),
                close_time=close_time,
                resolution_source=str(raw.get("resolutionSource", "")),
                rules_text=str(raw.get("description", "")),
                outcomes=outcomes,
                volume_usd=_safe_float(raw.get("volumeNum") or raw.get("volume"), 0.0),
                liquidity_usd=_safe_float(raw.get("liquidityNum") or raw.get("liquidity"), 0.0),
                is_active=bool(raw.get("active", True)),
                is_closed=bool(raw.get("closed", False)),
            )
        except Exception as e:
            log.debug("polymarket.parse_market_skipped", error=str(e))
            return None

    # ---------- Trading ----------

    def _ensure_clob_client(self):
        if self._clob is not None:
            return self._clob
        if not self._live:
            raise RuntimeError(
                "Live trading not configured. Set POLYMARKET_PRIVATE_KEY "
                "and POLYMARKET_FUNDER_ADDRESS, install with `pip install "
                "polyagent[live]`, and ensure compliance checks pass."
            )
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.constants import POLYGON
        except ImportError as e:
            raise RuntimeError(
                "py-clob-client not installed. `pip install polyagent[live]`."
            ) from e

        self._clob = ClobClient(
            host=CLOB_BASE,
            chain_id=POLYGON,
            key=self._private_key,
            funder=self._funder_address,
        )
        # Polymarket requires deriving + setting API creds.
        if self._api_key and self._api_secret and self._api_passphrase:
            from py_clob_client.clob_types import ApiCreds
            self._clob.set_api_creds(
                ApiCreds(
                    api_key=self._api_key,
                    api_secret=self._api_secret,
                    api_passphrase=self._api_passphrase,
                )
            )
        else:
            # Derive on first use. Will hit the network.
            self._clob.set_api_creds(self._clob.create_or_derive_api_creds())
        return self._clob

    async def place_limit_order(
        self,
        market_id: str,
        token_id: str,
        side: Side,
        price: float,
        size: float,
    ) -> Order:
        if not self._live:
            raise RuntimeError("Live trading not enabled on this connector instance.")

        client = self._ensure_clob_client()
        from py_clob_client.clob_types import OrderArgs
        from py_clob_client.order_builder.constants import BUY, SELL

        args = OrderArgs(
            token_id=token_id,
            price=price,
            size=size,
            side=BUY if side is Side.BUY else SELL,
        )
        # py-clob-client is sync; we accept the blocking call here. For high
        # throughput, wrap in run_in_executor; the agent's loop is slow enough
        # that this is fine.
        signed = client.create_order(args)
        resp = client.post_order(signed)
        order_id = str(resp.get("orderID") or resp.get("order_id") or "")
        return Order(
            order_id=order_id,
            market_id=market_id,
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            placed_at=datetime.now(timezone.utc),
            is_paper=False,
            status=str(resp.get("status", "open")),
        )

    async def cancel_order(self, order_id: str) -> bool:
        if not self._live:
            raise RuntimeError("Live trading not enabled.")
        client = self._ensure_clob_client()
        try:
            client.cancel(order_id=order_id)
            return True
        except Exception as e:
            log.error("polymarket.cancel_failed", order_id=order_id, error=str(e))
            return False

    async def list_open_orders(self) -> list[Order]:
        if not self._live:
            return []
        client = self._ensure_clob_client()
        try:
            raw_orders = client.get_orders()
        except Exception as e:
            log.error("polymarket.list_orders_failed", error=str(e))
            return []
        out: list[Order] = []
        for r in raw_orders:
            try:
                out.append(Order(
                    order_id=str(r.get("id", "")),
                    market_id=str(r.get("market", "")),
                    token_id=str(r.get("asset_id", "")),
                    side=Side.BUY if str(r.get("side", "")).upper() == "BUY" else Side.SELL,
                    price=float(r.get("price", 0)),
                    size=float(r.get("original_size", 0)),
                    filled=float(r.get("size_matched", 0)),
                    placed_at=_parse_iso(r.get("created_at")) or datetime.now(timezone.utc),
                    status=str(r.get("status", "open")),
                    is_paper=False,
                ))
            except (ValueError, TypeError):
                continue
        return out


def _maybe_parse_json_list(v: Any) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        import json
        try:
            parsed = json.loads(v)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _safe_float(v: Any, default: float) -> float:
    try:
        return float(v) if v is not None else default
    except (ValueError, TypeError):
        return default


def _parse_iso(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    try:
        s = str(v).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except ValueError:
        return None
