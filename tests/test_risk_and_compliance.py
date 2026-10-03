import os
from datetime import datetime, timezone

from agent.config import (
    AgentCfg,
    ComplianceCfg,
    DecisionCfg,
    ExecutionCfg,
    LoggingCfg,
    RiskCfg,
    ScannersCfg,
    Secrets,
    Settings,
    WalletsCfg,
)
from agent.core import compliance
from agent.core.risk import RiskManager
from agent.types import (
    Market,
    Mode,
    OrderBook,
    OrderBookLevel,
    Outcome,
    ProbabilityEstimate,
    Side,
    TradeOpportunity,
)


def _settings(mode: Mode, **secret_overrides) -> Settings:
    return Settings(
        agent=AgentCfg(loop_interval_seconds=30, max_concurrent_scans=4),
        compliance=ComplianceCfg(
            allowed_jurisdictions=["GB", "DE"],
            allowed_platforms=["polymarket"],
            require_manual_approval=False,
        ),
        risk=RiskCfg(
            bankroll_usd=1000, max_position_pct_bankroll=0.02,
            max_category_exposure_pct=0.15, max_correlated_exposure_pct=0.10,
            max_daily_loss_pct=0.05, max_drawdown_pct=0.20,
            max_open_positions=5, kelly_fraction=0.25, min_position_usd=5,
            hard_stop_loss_pct=0.20, trailing_stop_activation_profit=0.10,
            trailing_stop_distance=0.05, partial_take_profit_levels=[],
        ),
        decision=DecisionCfg(
            min_edge=0.05, min_confidence=0.55, min_liquidity_usd=200,
            max_spread=0.03, max_slippage_pct=0.02,
            min_resolution_clarity=0.70, min_source_credibility=0.60,
            min_trade_score=0.30, weights={},
        ),
        execution=ExecutionCfg(
            default_order_type="limit", max_chase_ticks=2,
            stale_order_seconds=120, min_tick=0.01,
        ),
        scanners=ScannersCfg(
            market_scan_top_n=50, unusual_volume_zscore=2.0,
            stale_reaction_minutes=30,
        ),
        wallets=WalletsCfg(enabled=False, min_trades_for_ranking=10,
                           smart_wallet_min_sharpe=1.0),
        logging=LoggingCfg(jsonl_path="/tmp/polyagent_test.jsonl"),
        secrets=Secrets(mode=mode, **secret_overrides),
    )


def _opp() -> TradeOpportunity:
    m = Market(market_id="m", slug="s", question="Q?",
               outcomes=[Outcome(token_id="t", name="Yes", price=0.40)])
    book = OrderBook(
        token_id="t",
        bids=[OrderBookLevel(price=0.39, size=100)],
        asks=[OrderBookLevel(price=0.40, size=100)],
        timestamp=datetime.now(timezone.utc),
    )
    return TradeOpportunity(
        market=m, outcome=m.outcomes[0], side=Side.BUY, book=book,
        probability=ProbabilityEstimate(
            estimated_prob=0.50, confidence=0.70,
            market_implied_prob=0.40, edge=0.10,
            fair_value_low=0.45, fair_value_high=0.55,
        ),
        spread=0.01, slippage_pct=0.005, max_fill_usd=500,
        liquidity_quality=0.8, resolution_clarity=0.85,
        source_credibility=0.75, wallet_signal=0.4,
        catalyst_strength=0.6, manipulation_risk=0.1, correlation_risk=0.0,
    )


def test_compliance_paper_mode_always_clears():
    s = _settings(Mode.PAPER)
    assert compliance.block_reasons(s) == []


def test_compliance_live_requires_jurisdiction_and_tos():
    s = _settings(Mode.AUTO)
    blocks = compliance.block_reasons(s)
    assert any("COMPLIANCE_JURISDICTION" in b for b in blocks)
    assert any("COMPLIANCE_TOS_ACK" in b for b in blocks)


def test_compliance_blocks_us():
    s = _settings(Mode.AUTO,
                  compliance_jurisdiction="US",
                  compliance_tos_ack="I_HAVE_READ_TOS")
    blocks = compliance.block_reasons(s)
    assert any("US" in b and "hard-block" in b for b in blocks)


def test_compliance_passes_with_allowlisted_juris_and_tos_ack():
    s = _settings(Mode.AUTO,
                  compliance_jurisdiction="GB",
                  compliance_tos_ack="I_HAVE_READ_TOS")
    assert compliance.block_reasons(s) == []


def test_kelly_sizing_caps_at_max_position_pct():
    s = _settings(Mode.PAPER)
    rm = RiskManager(s.risk, kill_switch_file="/tmp/_test_ks")
    o = _opp()
    # Force a huge edge to push raw Kelly above the cap
    o.probability.estimated_prob = 0.95
    o.probability.market_implied_prob = 0.40
    size = rm.size_usd(o)
    cap = s.risk.max_position_pct_bankroll * s.risk.bankroll_usd
    assert size <= cap + 0.01


def test_kill_switch_file_blocks():
    s = _settings(Mode.PAPER)
    ks_path = "/tmp/polyagent_kill_test"
    if os.path.exists(ks_path):
        os.remove(ks_path)
    rm = RiskManager(s.risk, kill_switch_file=ks_path)
    assert not rm.kill_switch_active()
    rm.trip_kill_switch("test")
    assert rm.kill_switch_active()
    blocks = rm.pretrade_block_reasons(_opp())
    assert any("kill switch" in b for b in blocks)
    os.remove(ks_path)
