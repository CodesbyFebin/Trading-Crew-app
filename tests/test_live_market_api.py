import time

from crew import api
from crew.live_market import BinancePublicMarketFeed


def test_live_market_api_is_authenticated_read_only_and_has_no_execution_state(client, monkeypatch):
    feed = BinancePublicMarketFeed(["BTCUSDT"])
    feed.ingest_message({"e": "bookTicker", "s": "BTCUSDT", "b": "100", "a": "101"})
    feed.ingest_message({"e": "aggTrade", "s": "BTCUSDT", "a": 1, "p": "100.5", "q": "2", "T": int(time.time() * 1000)})
    monkeypatch.setattr(api, "LIVE_FEED", feed)

    state_response = client.get("/api/market-data", headers={"Authorization": "Bearer view-t"})
    assert state_response.status_code == 200
    state = state_response.json()
    assert state["read_only"] and not state["authenticated"] and not state["order_execution_available"]
    assert state["quotes"]["BTCUSDT"]["last"] == "100.5"
    assert client.get("/api/market-data").status_code == 401

    candles = client.get("/api/market-data/candles?symbol=BTCUSDT&interval=60", headers={"Authorization": "Bearer view-t"})
    assert candles.status_code == 200 and candles.json()["data_status"] == "CACHED_PUBLIC_DATA"
    assert candles.json()["candles"]
    assert client.get("/api/market-data/candles?symbol=BTCUSDT&interval=7", headers={"Authorization": "Bearer view-t"}).status_code == 400
    assert client.get("/api/market-data/candles?symbol=UNKNOWN&interval=60", headers={"Authorization": "Bearer view-t"}).status_code == 400
