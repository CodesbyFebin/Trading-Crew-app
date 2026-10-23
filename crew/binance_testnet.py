"""Explicitly testnet-only Binance Spot REST client.

This module is deliberately not registered as a production execution connector and
cannot select a production endpoint. It is for validating request signing and
exchange contracts against Binance Spot Testnet only.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

BASE_URL = "https://testnet.binance.vision"
_SYMBOL = re.compile(r"^[A-Z0-9]{5,20}$")
_CLIENT_ID = re.compile(r"^[A-Za-z0-9_:/.-]{1,36}$")


class TestnetConfigurationError(RuntimeError):
    __test__ = False
    pass


class TestnetRequestError(RuntimeError):
    __test__ = False
    def __init__(self, status: int, payload: Any):
        self.status = status
        self.payload = payload
        # Binance responses do not contain our key/signature; retain only its
        # structured server response for diagnostics.
        super().__init__(f"Binance Spot Testnet HTTP {status}: {payload}")


class AmbiguousOrderOutcome(RuntimeError):
    __test__ = False
    """A POST may have reached the matching engine; query by client id first."""

    def __init__(self, client_order_id: str):
        self.client_order_id = client_order_id
        super().__init__(
            "Testnet order outcome is unknown; query the order by client_order_id "
            f"{client_order_id!r} before considering any retry"
        )


@dataclass(frozen=True)
class SymbolRules:
    symbol: str
    min_qty: Decimal
    max_qty: Decimal
    step_size: Decimal
    min_price: Decimal
    max_price: Decimal
    tick_size: Decimal
    min_notional: Decimal = Decimal("0")


Transport = Callable[[str, str, dict[str, str], float], tuple[int, Any]]


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, float):
        raise ValueError(f"{field} must be passed as Decimal or string, not float")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"invalid {field}") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError(f"{field} must be finite and positive")
    return result


def _default_transport(method: str, url: str, headers: dict[str, str], timeout: float) -> tuple[int, Any]:
    # No redirects: never forward API credentials to a redirect destination.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, hdrs, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirect())
    req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with opener.open(req, timeout=timeout) as response:
            body = response.read(1_000_001)
            if len(body) > 1_000_000:
                raise TestnetRequestError(response.status, {"msg": "response too large"})
            return response.status, json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read(64_001)
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            payload = {"msg": "non-JSON error response"}
        return exc.code, payload


class BinanceSpotTestnet:
    """Testnet-only signed REST client. There is intentionally no live URL option."""

    base_url = BASE_URL

    def __init__(self, api_key: str | None = None, api_secret: str | None = None,
                 *, transport: Transport | None = None,
                 clock_ms: Callable[[], int] | None = None, timeout: float = 5.0):
        self.api_key = api_key if api_key is not None else os.getenv("BINANCE_TESTNET_API_KEY", "")
        self.api_secret = api_secret if api_secret is not None else os.getenv("BINANCE_TESTNET_API_SECRET", "")
        if not self.api_key or not self.api_secret:
            raise TestnetConfigurationError("Set testnet-only BINANCE_TESTNET_API_KEY and BINANCE_TESTNET_API_SECRET")
        if timeout <= 0 or timeout > 15:
            raise ValueError("timeout must be > 0 and <= 15 seconds")
        self.timeout = timeout
        self._transport = transport or _default_transport
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    @staticmethod
    def _encode(params: list[tuple[str, Any]]) -> str:
        return urllib.parse.urlencode([(k, str(v)) for k, v in params])

    def _request(self, method: str, path: str, params: list[tuple[str, Any]] | None = None,
                 *, signed: bool = False) -> Any:
        if not path.startswith("/api/v3/") or ".." in path:
            raise ValueError("invalid testnet endpoint")
        pairs = list(params or [])
        if signed:
            pairs.extend([("timestamp", self._clock_ms()), ("recvWindow", 5000)])
            payload = self._encode(pairs)
            signature = hmac.new(self.api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
            pairs.append(("signature", signature))
        query = self._encode(pairs)
        url = f"{BASE_URL}{path}" + (f"?{query}" if query else "")
        status, payload = self._transport(method, url, {"X-MBX-APIKEY": self.api_key}, self.timeout)
        if not 200 <= status < 300:
            raise TestnetRequestError(status, payload)
        return payload

    def ping(self) -> Any:
        return self._request("GET", "/api/v3/ping")

    def server_time(self) -> Any:
        return self._request("GET", "/api/v3/time")

    def account(self) -> Any:
        return self._request("GET", "/api/v3/account", signed=True)

    def exchange_info(self, symbol: str) -> Any:
        symbol = self._validate_symbol(symbol)
        return self._request("GET", "/api/v3/exchangeInfo", [("symbol", symbol)])

    @staticmethod
    def _validate_symbol(symbol: str) -> str:
        symbol = str(symbol).upper()
        if not _SYMBOL.fullmatch(symbol):
            raise ValueError("invalid symbol")
        return symbol

    def symbol_rules(self, symbol: str) -> SymbolRules:
        symbol = self._validate_symbol(symbol)
        data = self.exchange_info(symbol)
        rows = data.get("symbols", []) if isinstance(data, dict) else []
        row = next((r for r in rows if r.get("symbol") == symbol and r.get("status") == "TRADING"), None)
        if not row:
            raise ValueError("symbol is not available for trading on Spot Testnet")
        filters = {f.get("filterType"): f for f in row.get("filters", [])}
        lot = filters.get("LOT_SIZE")
        price = filters.get("PRICE_FILTER")
        notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
        if not lot or not price:
            raise ValueError("exchangeInfo missing required LOT_SIZE or PRICE_FILTER")
        return SymbolRules(
            symbol=symbol, min_qty=Decimal(lot["minQty"]), max_qty=Decimal(lot["maxQty"]),
            step_size=Decimal(lot["stepSize"]), min_price=Decimal(price["minPrice"]),
            max_price=Decimal(price["maxPrice"]), tick_size=Decimal(price["tickSize"]),
            min_notional=Decimal(notional.get("minNotional", "0")),
        )

    @staticmethod
    def _check_increment(value: Decimal, step: Decimal, name: str) -> None:
        if step <= 0 or value % step != 0:
            raise ValueError(f"{name} does not align to exchange increment {step}")

    def place_limit_order(self, *, symbol: str, side: str, quantity: Decimal | str,
                          price: Decimal | str, client_order_id: str) -> Any:
        symbol = self._validate_symbol(symbol)
        side = str(side).upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if not _CLIENT_ID.fullmatch(str(client_order_id)):
            raise ValueError("client_order_id must be 1-36 safe characters")
        qty, px = _decimal(quantity, "quantity"), _decimal(price, "price")
        rules = self.symbol_rules(symbol)
        if not rules.min_qty <= qty <= rules.max_qty:
            raise ValueError("quantity outside exchange LOT_SIZE bounds")
        if not rules.min_price <= px <= rules.max_price:
            raise ValueError("price outside exchange PRICE_FILTER bounds")
        self._check_increment(qty, rules.step_size, "quantity")
        self._check_increment(px, rules.tick_size, "price")
        if rules.min_notional and qty * px < rules.min_notional:
            raise ValueError("order notional below exchange minimum")
        params = [("symbol", symbol), ("side", side), ("type", "LIMIT"),
                  ("timeInForce", "GTC"), ("quantity", format(qty, "f")),
                  ("price", format(px, "f")), ("newClientOrderId", str(client_order_id))]
        try:
            return self._request("POST", "/api/v3/order", params, signed=True)
        except (TimeoutError, OSError, urllib.error.URLError) as exc:
            raise AmbiguousOrderOutcome(str(client_order_id)) from exc

    def get_order(self, *, symbol: str, client_order_id: str) -> Any:
        symbol = self._validate_symbol(symbol)
        return self._request("GET", "/api/v3/order",
                             [("symbol", symbol), ("origClientOrderId", client_order_id)], signed=True)

    def cancel_order(self, *, symbol: str, client_order_id: str) -> Any:
        symbol = self._validate_symbol(symbol)
        return self._request("DELETE", "/api/v3/order",
                             [("symbol", symbol), ("origClientOrderId", client_order_id)], signed=True)

    def cancel_all_open_orders(self, *, symbol: str) -> Any:
        """Cancel outstanding Testnet orders for one symbol; does not claim to flatten balances."""
        symbol = self._validate_symbol(symbol)
        return self._request("DELETE", "/api/v3/openOrders", [("symbol", symbol)], signed=True)

    def open_orders(self, *, symbol: str | None = None) -> Any:
        params = [("symbol", self._validate_symbol(symbol))] if symbol else []
        return self._request("GET", "/api/v3/openOrders", params, signed=True)
