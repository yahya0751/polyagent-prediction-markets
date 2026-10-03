from datetime import datetime, timezone

from agent.config import RiskCfg
from agent.core import exits
from agent.core.exits import ExitAction
from agent.types import Position, Side


def _cfg() -> RiskCfg:
    return RiskCfg(
        bankroll_usd=1000, max_position_pct_bankroll=0.02,
        max_category_exposure_pct=0.15, max_correlated_exposure_pct=0.10,
        max_daily_loss_pct=0.05, max_drawdown_pct=0.20,
        max_open_positions=5, kelly_fraction=0.25, min_position_usd=5,
        hard_stop_loss_pct=0.20, trailing_stop_activation_profit=0.10,
        trailing_stop_distance=0.05,
        partial_take_profit_levels=[],
    )


def _pos(**overrides) -> Position:
    base = dict(
        market_id="m", token_id="t", side=Side.BUY,
        avg_entry_price=0.40, size=100,
        opened_at=datetime.now(timezone.utc),
        last_update=datetime.now(timezone.utc),
        stop_loss_price=0.32,
        take_profit_prices=[0.50, 0.59],
    )
    base.update(overrides)
    return Position(**base)


def test_thesis_invalidation_full_exit():
    d = exits.evaluate(_pos(), current_price=0.41, cfg=_cfg(),
                       thesis_invalidated=True)
    assert d.action is ExitAction.EXIT and d.fraction == 1.0


def test_smart_wallet_exodus_full_exit():
    d = exits.evaluate(_pos(), current_price=0.41, cfg=_cfg(),
                       smart_wallet_dropoff=0.6)
    assert d.action is ExitAction.EXIT


def test_hard_stop_loss():
    d = exits.evaluate(_pos(), current_price=0.30, cfg=_cfg())
    assert d.action is ExitAction.EXIT
    assert "stop" in d.reason


def test_take_profit_partial():
    d = exits.evaluate(_pos(), current_price=0.51, cfg=_cfg())
    assert d.action is ExitAction.REDUCE
    assert d.fraction > 0


def test_liquidity_collapse_exit():
    d = exits.evaluate(_pos(), current_price=0.41, cfg=_cfg(),
                       liquidity_quality_now=0.10)
    assert d.action is ExitAction.EXIT


def test_trailing_activates_then_triggers():
    cfg = _cfg()
    p = _pos()
    # Move price up to activate trailing
    exits.update_trailing(p, current_price=0.55, cfg=cfg)
    assert p.trailing_stop_price is not None
    initial_trail = p.trailing_stop_price
    # Move further up: trail follows
    exits.update_trailing(p, current_price=0.60, cfg=cfg)
    assert p.trailing_stop_price > initial_trail
    # Now drop below trailing: should exit
    d = exits.evaluate(p, current_price=p.trailing_stop_price - 0.01, cfg=cfg)
    assert d.action is ExitAction.EXIT
    assert "trailing" in d.reason


def test_no_trigger_holds():
    d = exits.evaluate(_pos(), current_price=0.41, cfg=_cfg())
    assert d.action is ExitAction.HOLD
