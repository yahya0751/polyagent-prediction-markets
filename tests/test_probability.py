from agent.core.probability import estimate


def test_neutral_inputs_return_implied():
    e = estimate(market_implied=0.40, side_is_yes=True)
    assert abs(e.estimated_prob - 0.40) < 1e-6
    assert abs(e.edge) < 1e-6


def test_positive_news_pushes_up():
    e = estimate(market_implied=0.40, side_is_yes=True, news_signal=1.0)
    assert e.estimated_prob > 0.40
    assert e.edge > 0


def test_disagreement_lowers_confidence():
    agree = estimate(market_implied=0.40, side_is_yes=True,
                     news_signal=1.0, wallet_signal=1.0)
    disagree = estimate(market_implied=0.40, side_is_yes=True,
                        news_signal=1.0, wallet_signal=-1.0)
    assert agree.confidence > disagree.confidence


def test_low_resolution_clarity_lowers_confidence():
    clear = estimate(market_implied=0.40, side_is_yes=True,
                     news_signal=1.0, resolution_clarity=1.0)
    murky = estimate(market_implied=0.40, side_is_yes=True,
                     news_signal=1.0, resolution_clarity=0.3)
    assert clear.confidence > murky.confidence


def test_no_orientation_inverts_signs():
    e_yes = estimate(market_implied=0.40, side_is_yes=True, news_signal=1.0)
    e_no = estimate(market_implied=0.40, side_is_yes=False, news_signal=1.0)
    # YES p went up; NO p must have gone down
    assert e_yes.estimated_prob > 0.40
    assert e_no.estimated_prob < 0.60
