from decimal import Decimal

import pytest

from crew.replay_guards import ReplayInputError, WalletActivityReplay, require_cnc_product
from crew.desk_d4 import Feat
from crew.regimes import classify_replay_features, summarize_realized_by_regime


def test_india_replay_policy_rejects_mis_and_margin_products():
    for product in ("MIS", "MTF", "NRML", "BO", "CO", ""):
        with pytest.raises(ReplayInputError):
            require_cnc_product(product)
    require_cnc_product("CNC")


def test_wallet_replay_deduplicates_fills_but_keeps_distinct_fills_in_same_tx():
    feed = WalletActivityReplay("0x0000000000000000000000000000000000000001")
    first = {
        "fill_id": "fill-001", "transaction_hash": "0xabc", "token_id": "tok-1",
        "side": "BUY", "price": "0.42", "size": "100", "type": "TRADE",
        "timestamp": 1700000000,
    }
    second = {**first, "fill_id": "fill-002", "price": "0.43", "size": "50"}

    result = feed.process_page([first, second, first])

    assert [event["event_id"] for event in result] == ["fill-001", "fill-002"]
    assert result[0]["tx_hash"] == result[1]["tx_hash"]
    assert result[0]["price"] == Decimal("0.42")
    assert result[0]["usdc_notional"] == Decimal("42.00")
    assert result[1]["usdc_notional"] == Decimal("21.50")


def test_wallet_replay_requires_stable_fill_id_and_rejects_non_finite_numbers():
    feed = WalletActivityReplay("0x0000000000000000000000000000000000000001")
    base = {
        "transaction_hash": "0xabc", "token_id": "tok-1", "side": "BUY",
        "price": "0.42", "size": "100", "type": "TRADE",
    }
    with pytest.raises(ReplayInputError, match="fill_id"):
        feed.process_page([base])
    with pytest.raises(ReplayInputError, match="finite"):
        feed.process_page([{**base, "fill_id": "fill-1", "price": "NaN"}])


def test_wallet_replay_rejects_invalid_leader_address():
    with pytest.raises(ReplayInputError, match="leader_address"):
        WalletActivityReplay("not-a-wallet")


def test_regime_classification_uses_only_prior_rows_and_marks_unknown_warmup():
    def row(ts, vol, spread, slope=Decimal("0.001")):
        return Feat(ts, "BTCUSDT", Decimal("100"), Decimal("101"), Decimal("100"),
                    Decimal(spread), Decimal("0"), Decimal(vol), Decimal(slope))

    baseline = [row(i, "1", "2") for i in range(1, 22)]
    shock = row(22, "3", "6")
    labels = classify_replay_features(baseline + [shock], minimum_baseline=20)
    assert labels[("BTCUSDT", 1)].volatility == "UNKNOWN"
    assert labels[("BTCUSDT", 21)].volatility == "BASELINE"
    assert labels[("BTCUSDT", 22)].volatility == "HIGH"
    assert labels[("BTCUSDT", 22)].spread == "WIDE"

    changed_future = classify_replay_features(baseline + [row(22, "1000", "1000"), row(23, "9999", "9999")], minimum_baseline=20)
    for ts in range(1, 23):
        assert labels[("BTCUSDT", ts)] == changed_future[("BTCUSDT", ts)]


def test_regime_report_uses_net_decimal_outcomes_and_keeps_small_sample_count():
    rows = summarize_realized_by_regime([
        ("TREND_UP|VOL_BASELINE|SPREAD_BASELINE", Decimal("2.50")),
        ("TREND_UP|VOL_BASELINE|SPREAD_BASELINE", Decimal("-1.25")),
    ])
    assert rows == [{
        "regime": "TREND_UP|VOL_BASELINE|SPREAD_BASELINE",
        "closed_trades": 2,
        "positive_trades": 1,
        "negative_trades": 1,
        "net_pnl_after_costs": "1.2500",
        "mean_net_pnl": "0.6250",
    }]
