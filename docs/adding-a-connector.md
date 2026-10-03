# Adding a connector

A *connector* is PolyAgent's adapter to one prediction-market platform.
Polymarket is one connector; Manifold is another. Adding a third (Kalshi,
PredictIt, Metaculus, …) means implementing one interface — **no engine, CLI,
or dashboard code changes.**

This is the single best first contribution. Budget ~an afternoon.

## The interface

Every connector subclasses `BaseConnector` (`agent/connectors/base.py`):

```python
class BaseConnector(ABC):
    name: str = "base"

    # read paths
    async def list_markets(self, limit: int = 100) -> list[Market]: ...
    async def get_market(self, market_id: str) -> Optional[Market]: ...
    async def get_order_book(self, token_id: str) -> Optional[OrderBook]: ...

    # trade paths (optional for a read-only data source)
    async def place_limit_order(self, market_id, token_id, side, price, size) -> Order: ...
    async def cancel_order(self, order_id: str) -> bool: ...
    async def list_open_orders(self) -> list[Order]: ...

    @property
    def supports_live_trading(self) -> bool: ...
```

The domain types (`Market`, `Outcome`, `OrderBook`, `OrderBookLevel`, `Order`)
live in `agent/types.py` and are pydantic models — if your parse output is
wrong-shaped, it fails loudly at parse time.

## Step by step

1. **Copy the worked example.** `agent/connectors/manifold.py` is a complete,
   tested, read-only connector against a free public API. Start from it.

2. **Register it.** Decorate your class:

   ```python
   from .registry import register

   @register("kalshi")
   class KalshiConnector(BaseConnector):
       name = "kalshi"
   ```

   Auto-discovery imports every module in `agent/connectors/`, so the decorator
   is all you need — your platform immediately shows up in
   `registry.available()`, the `--platform` CLI flag, and (once wired) the
   dashboard's platform switch.

3. **Implement the read paths.** Map the platform's market JSON onto `Market`.
   Keep parsing in a pure `@staticmethod _parse_market(raw) -> Market | None`
   so it can be unit-tested without the network. **Return `None` for records
   you can't handle — never raise out of a scan loop.**

4. **Order book.** If the platform has a real book, map it. If it's an AMM
   (like Manifold), derive an approximate book from price + liquidity and
   document the approximation — see `ManifoldConnector._derive_book`.

5. **Trading (optional).** A read-only connector can leave `place_limit_order`
   raising a clear "not implemented" error (see Manifold). Wiring live trading
   is a fine follow-up PR; keep it behind `supports_live_trading`.

6. **Test it offline.** Copy `tests/test_manifold_connector.py`:
   - unit-test `_parse_market` against a recorded JSON fixture,
   - drive `list_markets` through `httpx.MockTransport` so CI needs no network.

   ```python
   def handler(request): return httpx.Response(200, content=json.dumps(payload))
   conn = KalshiConnector(transport=httpx.MockTransport(handler))
   ```

7. **Try it live (read-only):**

   ```bash
   python -m agent.main scan-once --platform kalshi
   ```

## Checklist

- [ ] `@register("name")` on the class
- [ ] `_parse_market` is pure and returns `None` on bad input
- [ ] Offline unit tests (no network) for parsing + `list_markets`
- [ ] `ruff check .` and `pytest -q` pass
- [ ] Trade paths either implemented behind `supports_live_trading`, or raise
      a clear not-implemented error

That's it — open a PR.
