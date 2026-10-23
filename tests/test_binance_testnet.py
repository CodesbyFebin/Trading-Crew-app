import hashlib
import hmac
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from crew.binance_testnet import (
    AmbiguousOrderOutcome,
    BinanceSpotTestnet,
    TestnetConfigurationError,
)


def make_client(responder=None):
    calls = []

    def transport(method, url, headers, timeout):
        calls.append((method, url, headers, timeout))
        if responder:
            return responder(method, url, headers, timeout)
        if urlparse(url).path.endswith("exchangeInfo"):
            return 200, {"symbols": [{"symbol": "BTCUSDT", "status": "TRADING", "filters": [
                {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "100", "stepSize": "0.001"},
                {"filterType": "PRICE_FILTER", "minPrice": "0.01", "maxPrice": "1000000", "tickSize": "0.01"},
                {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
            ]}]}
        return 200, {"status": "ok"}

    return BinanceSpotTestnet("test-key", "test-secret", transport=transport,
                              clock_ms=lambda: 1700000000000), calls


def test_signed_calls_are_pinned_to_testnet_and_hmac_is_attached():
    client, calls = make_client()
    assert client.account() == {"status": "ok"}
    method, url, headers, timeout = calls[0]
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "testnet.binance.vision"
    assert parsed.path == "/api/v3/account"
    assert params["timestamp"] == ["1700000000000"]
    assert len(params["signature"][0]) == 64
    assert headers["X-MBX-APIKEY"] == "test-key"
    assert method == "GET" and timeout <= 15
    unsigned = [(key, value[0]) for key, value in params.items() if key != "signature"]
    canonical = "&".join(f"{key}={value}" for key, value in unsigned)
    expected = hmac.new(b"test-secret", canonical.encode(), hashlib.sha256).hexdigest()
    assert params["signature"] == [expected]


def test_limit_order_checks_exchange_filters_then_uses_idempotency_key():
    client, calls = make_client()
    result = client.place_limit_order(symbol="BTCUSDT", side="BUY", quantity=Decimal("0.010"),
                                      price=Decimal("50000.00"), client_order_id="tc-test-001")
    assert result == {"status": "ok"}
    method, url, _, _ = calls[-1]
    params = parse_qs(urlparse(url).query)
    assert method == "POST"
    assert params["type"] == ["LIMIT"]
    assert params["timeInForce"] == ["GTC"]
    assert params["quantity"] == ["0.010"]
    assert params["price"] == ["50000.00"]
    assert params["newClientOrderId"] == ["tc-test-001"]


@pytest.mark.parametrize("kwargs", [
    {"quantity": 0.01, "price": Decimal("50000")},
    {"quantity": Decimal("0.0101"), "price": Decimal("50000")},
    {"quantity": Decimal("0.010"), "price": Decimal("50000.001")},
    {"quantity": Decimal("0.0009"), "price": Decimal("50000")},
])
def test_order_rejects_float_or_exchange_filter_violation(kwargs):
    client, calls = make_client()
    with pytest.raises(ValueError):
        client.place_limit_order(symbol="BTCUSDT", side="BUY", client_order_id="tc-test-002", **kwargs)
    # Exchange info can be read, but no order POST is sent on a failed validation.
    assert all(call[0] != "POST" for call in calls)


def test_invalid_side_symbol_and_client_id_fail_before_order_submission():
    client, calls = make_client()
    for values in [
        {"symbol": "BTCUSDT", "side": "SHORT", "quantity": "0.01", "price": "50000", "client_order_id": "id-1"},
        {"symbol": "../api", "side": "BUY", "quantity": "0.01", "price": "50000", "client_order_id": "id-1"},
        {"symbol": "BTCUSDT", "side": "BUY", "quantity": "0.01", "price": "50000", "client_order_id": "x" * 37},
    ]:
        with pytest.raises(ValueError):
            client.place_limit_order(**values)
    assert calls == []


def test_ambiguous_post_is_never_retried():
    attempts = []

    def timed_out(method, url, headers, timeout):
        attempts.append(method)
        if urlparse(url).path.endswith("exchangeInfo"):
            return 200, {"symbols": [{"symbol": "BTCUSDT", "status": "TRADING", "filters": [
                {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "100", "stepSize": "0.001"},
                {"filterType": "PRICE_FILTER", "minPrice": "0.01", "maxPrice": "1000000", "tickSize": "0.01"},
                {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
            ]}]}
        if method == "POST":
            raise TimeoutError("simulated timeout")
        return 200, {"status": "NEW"}

    client, calls = make_client(timed_out)
    with pytest.raises(AmbiguousOrderOutcome) as exc:
        client.place_limit_order(symbol="BTCUSDT", side="BUY", quantity="0.01",
                                 price="50000", client_order_id="tc-amb-1")
    assert exc.value.client_order_id == "tc-amb-1"
    assert attempts == ["GET", "POST"]  # exchangeInfo, then exactly one order POST
    assert client.get_order(symbol="BTCUSDT", client_order_id="tc-amb-1") == {"status": "NEW"}


def test_missing_credentials_fail_closed(monkeypatch):
    monkeypatch.delenv("BINANCE_TESTNET_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_TESTNET_API_SECRET", raising=False)
    with pytest.raises(TestnetConfigurationError):
        BinanceSpotTestnet()
