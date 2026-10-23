import time
from decimal import Decimal

import pytest

from crew.live_market import BinancePublicMarketFeed


def test_live_feed_validates_quotes_aggregates_trade_candles_and_reports_read_only():
    feed = BinancePublicMarketFeed(["BTCUSDT"])
    now_ms = int(time.time() * 1000)
    feed.ingest_message({"stream": "btcusdt@bookTicker", "data": {
        "e": "bookTicker", "s": "BTCUSDT", "b": "100.00", "B": "2", "a": "100.10", "A": "3",
    }}, received_ms=now_ms)
    # Keep both trades inside one 5-minute bucket even when the wall clock is near
    # a 5-minute boundary; otherwise this aggregation assertion becomes time-flaky.
    minute_a = ((now_ms // 300_000) - 1) * 300_000 + 60_000 + 1_000
    minute_b = minute_a + 60_000
    feed.ingest_message({"data": {"e": "aggTrade", "s": "BTCUSDT", "a": 10, "p": "100.05", "q": "2", "T": minute_a}}, received_ms=now_ms)
    feed.ingest_message({"data": {"e": "aggTrade", "s": "BTCUSDT", "a": 11, "p": "99.95", "q": "1", "T": minute_a + 2_000}}, received_ms=now_ms)
    feed.ingest_message({"data": {"e": "aggTrade", "s": "BTCUSDT", "a": 12, "p": "100.20", "q": "3", "T": minute_b}}, received_ms=now_ms)

    state = feed.snapshot()
    assert state["status"] == "STARTING"  # no network socket was opened in this unit test
    assert state["read_only"] and not state["authenticated"] and not state["order_execution_available"]
    assert state["quotes"]["BTCUSDT"]["bid"] == "100.00"
    assert state["quotes"]["BTCUSDT"]["ask"] == "100.10"
    assert state["quotes"]["BTCUSDT"]["last"] == "100.20"

    one_minute = feed.candles("BTCUSDT", 60)
    assert len(one_minute["candles"]) == 2
    assert Decimal(one_minute["candles"][0]["high"]) == Decimal("100.05")
    assert Decimal(one_minute["candles"][0]["low"]) == Decimal("99.95")
    assert Decimal(one_minute["candles"][0]["volume"]) == Decimal("3")
    assert len(feed.candles("BTCUSDT", 300)["candles"]) == 1


def test_live_feed_rejects_bad_symbols_prices_crossed_quotes_and_intervals():
    with pytest.raises(ValueError, match="allowlist"):
        BinancePublicMarketFeed(["NOTREAL"])
    feed = BinancePublicMarketFeed(["BTCUSDT"])
    with pytest.raises(ValueError, match="crossed"):
        feed.ingest_message({"e": "bookTicker", "s": "BTCUSDT", "b": "101", "a": "100"})
    with pytest.raises(ValueError, match="positive"):
        feed.ingest_message({"e": "aggTrade", "s": "BTCUSDT", "a": 1, "p": "0", "q": "1", "T": 1_800_000_000_000})
    with pytest.raises(ValueError, match="interval"):
        feed.candles("BTCUSDT", 7)
    with pytest.raises(ValueError, match="allowlist"):
        feed.candles("UNKNOWN", 60)


def test_live_feed_rejects_out_of_order_stream_trades():
    feed = BinancePublicMarketFeed(["BTCUSDT"])
    now_ms = int(time.time() * 1000)
    latest_minute = now_ms // 60_000 * 60_000
    feed.ingest_message({"e": "aggTrade", "s": "BTCUSDT", "a": 2, "p": "100", "q": "1", "T": latest_minute}, received_ms=now_ms)
    with pytest.raises(ValueError, match="out-of-order"):
        feed.ingest_message({"e": "aggTrade", "s": "BTCUSDT", "a": 1, "p": "99", "q": "1", "T": latest_minute - 60_000}, received_ms=now_ms)
