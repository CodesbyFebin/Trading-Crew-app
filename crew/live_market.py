"""Read-only Binance Spot public market data. This module cannot access accounts or place orders."""
from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from decimal import Decimal, InvalidOperation
from threading import Event
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen


PUBLIC_REST = "https://data-api.binance.vision"
PUBLIC_WS = "wss://data-stream.binance.vision/stream"
ALLOWED_SYMBOLS = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"}
ALLOWED_INTERVALS = {60, 300, 900, 3600}


def _d(value: Any, name: str, *, positive: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{name} must be a finite decimal") from None
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError(f"{name} must be a finite {'positive ' if positive else ''}decimal")
    return result


class BinancePublicMarketFeed:
    """Public market stream + REST candle bootstrap, with bounded in-memory state.

    The only network targets are Binance public market-data endpoints. No credentials,
    private user stream, balances, orders, signing, or exchange execution are present.
    """

    def __init__(self, symbols: list[str] | None = None, *, stale_after_s: int = 30):
        raw = symbols or os.getenv("CREW_LIVE_MARKET_SYMBOLS", "BTCUSDT,ETHUSDT").split(",")
        selected = [str(s).strip().upper() for s in raw if str(s).strip()]
        if not selected or len(selected) > 5 or len(set(selected)) != len(selected) or any(s not in ALLOWED_SYMBOLS for s in selected):
            raise ValueError("symbols must be a unique subset of the configured public-market allowlist")
        self.symbols = tuple(selected)
        self.stale_after_s = max(5, int(stale_after_s))
        self._bars: dict[str, deque[dict[str, Any]]] = {s: deque(maxlen=2000) for s in self.symbols}
        self._quotes: dict[str, dict[str, Any]] = {s: {} for s in self.symbols}
        self._last_event_s: dict[str, float] = {}
        self._status = "STARTING"
        self._connected_at: float | None = None
        self._last_message_s: float | None = None
        self._last_error: str | None = None
        self._messages = 0
        self._reconnects = 0
        self._http_errors = 0
        self._rejected_messages = 0
        self._last_rejected_event: dict[str, Any] | None = None
        self._running = False
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="binance-public-market-feed")

    async def stop(self) -> None:
        self._running = False
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._status = "STOPPED"

    def _fetch_klines(self, symbol: str) -> list[list[Any]]:
        url = f"{PUBLIC_REST}/api/v3/klines?{urlencode({'symbol': symbol, 'interval': '1m', 'limit': 500})}"
        with urlopen(url, timeout=8) as response:
            payload = json.loads(response.read())
        if not isinstance(payload, list):
            raise ValueError("Binance kline response was not a list")
        return payload

    def _ingest_klines(self, symbol: str, rows: list[list[Any]]) -> None:
        bars = self._bars[symbol]
        parsed: dict[int, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, list) or len(row) < 7:
                continue
            start_ms = int(row[0])
            candle = {
                "time": start_ms // 1000,
                "open": str(_d(row[1], "open", positive=True)),
                "high": str(_d(row[2], "high", positive=True)),
                "low": str(_d(row[3], "low", positive=True)),
                "close": str(_d(row[4], "close", positive=True)),
                "volume": str(_d(row[5], "volume")),
                "closed": int(row[6]) < int(time.time() * 1000),
            }
            low = _d(candle["low"], "low")
            high = _d(candle["high"], "high")
            open_price = _d(candle["open"], "open")
            close = _d(candle["close"], "close")
            volume = _d(candle["volume"], "volume")
            if low > high or not low <= open_price <= high or not low <= close <= high or volume < 0:
                continue
            parsed[candle["time"]] = candle
        if parsed:
            merged = {int(c["time"]): c for c in bars}
            merged.update(parsed)
            bars.clear()
            bars.extend(merged[k] for k in sorted(merged)[-bars.maxlen:])

    async def _bootstrap(self) -> None:
        for symbol in self.symbols:
            try:
                rows = await asyncio.to_thread(self._fetch_klines, symbol)
                self._ingest_klines(symbol, rows)
            except Exception as exc:
                self._http_errors += 1
                self._last_error = f"REST candle bootstrap: {type(exc).__name__}: {str(exc)[:160]}"

    def ingest_message(self, payload: dict[str, Any], *, received_ms: int | None = None) -> None:
        """Validate and apply a raw or combined Binance stream event (also used by tests)."""
        if not isinstance(payload, dict):
            raise ValueError("market event must be an object")
        event = payload.get("data", payload)
        if not isinstance(event, dict):
            raise ValueError("combined stream data must be an object")
        symbol = str(event.get("s", "")).upper()
        if symbol not in self._quotes:
            raise ValueError("event symbol is not subscribed")
        now_ms = int(received_ms if received_ms is not None else time.time() * 1000)
        # Binance Spot bookTicker events omit the `e` event-type field. The stream
        # name identifies them as bookTicker, and the payload itself carries b/a.
        event_type = event.get("e") or ""
        if event_type in {"bookTicker", ""} and ("b" in event and "a" in event):
            bid = _d(event.get("b"), "bid", positive=True)
            ask = _d(event.get("a"), "ask", positive=True)
            if bid >= ask:
                raise ValueError("crossed or locked quote rejected")
            self._quotes[symbol].update({"bid": str(bid), "ask": str(ask), "mid": str((bid + ask) / 2)})
            self._last_event_s[symbol] = now_ms / 1000
        elif event_type in {"aggTrade", "trade"}:
            price = _d(event.get("p"), "price", positive=True)
            quantity = _d(event.get("q"), "quantity", positive=True)
            event_ms = int(event.get("T", event.get("E", now_ms)))
            minute = event_ms // 60_000 * 60
            bars = self._bars[symbol]
            if bars and minute < int(bars[-1]["time"]):
                raise ValueError("out-of-order trade event rejected")
            if bars and minute == int(bars[-1]["time"]):
                bar = bars[-1]
                bar["high"] = str(max(_d(bar["high"], "high"), price))
                bar["low"] = str(min(_d(bar["low"], "low"), price))
                bar["close"] = str(price)
                bar["volume"] = str(_d(bar["volume"], "volume") + quantity)
                bar["closed"] = False
            else:
                if bars:
                    bars[-1]["closed"] = True
                bars.append({"time": minute, "open": str(price), "high": str(price), "low": str(price),
                             "close": str(price), "volume": str(quantity), "closed": False})
            self._quotes[symbol]["last"] = str(price)
            self._quotes[symbol]["last_trade_size"] = str(quantity)
            self._quotes[symbol]["trade_id"] = event.get("a", event.get("t"))
            self._last_event_s[symbol] = now_ms / 1000
        elif event_type == "serverShutdown":
            self._status = "RECONNECTING"
        else:
            raise ValueError("unsupported Binance market-data event")
        self._last_message_s = now_ms / 1000
        self._messages += 1

    async def _run(self) -> None:
        await self._bootstrap()
        delay = 1
        while self._running:
            try:
                import websockets

                streams = "/".join(f"{s.lower()}@{kind}" for s in self.symbols for kind in ("aggTrade", "bookTicker"))
                async with websockets.connect(
                    f"{PUBLIC_WS}?{urlencode({'streams': streams})}",
                    ping_interval=20, ping_timeout=60, open_timeout=10,
                    close_timeout=5, max_queue=1000,
                ) as socket:
                    self._status = "CONNECTED"
                    self._connected_at = time.time()
                    self._last_error = None
                    delay = 1
                    async for raw in socket:
                        payload = None
                        try:
                            payload = json.loads(raw)
                            self.ingest_message(payload)
                        except (ValueError, TypeError, json.JSONDecodeError) as exc:
                            self._rejected_messages += 1
                            event = payload.get("data", payload) if isinstance(payload, dict) else {}
                            if not isinstance(event, dict):
                                event = {}
                            self._last_rejected_event = {
                                "stream": str(payload.get("stream", ""))[:80] if isinstance(payload, dict) else "",
                                "event_type": str(event.get("e", "<missing>"))[:40],
                                "fields": sorted(str(k)[:40] for k in event)[:20],
                            }
                            self._last_error = (
                                f"event rejected ({self._last_rejected_event['event_type']}): {str(exc)[:160]}"
                            )
                    if self._running:
                        self._status = "RECONNECTING"
                        self._reconnects += 1
                        try:
                            await asyncio.wait_for(self._stop.wait(), timeout=1)
                        except asyncio.TimeoutError:
                            pass
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._running:
                    break
                self._status = "RECONNECTING" if self._messages else "DISCONNECTED"
                self._last_error = f"{type(exc).__name__}: {str(exc)[:160]}"
                self._reconnects += 1
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, 30)

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        quotes = {}
        for symbol in self.symbols:
            quote = dict(self._quotes[symbol])
            updated = self._last_event_s.get(symbol)
            age = round(max(0.0, now - updated), 3) if updated is not None else None
            quote.update({"updated_at": updated, "age_s": age, "stale": age is None or age > self.stale_after_s,
                          "latest_candle": dict(self._bars[symbol][-1]) if self._bars[symbol] else None})
            quotes[symbol] = quote
        age = round(max(0.0, now - self._last_message_s), 3) if self._last_message_s is not None else None
        status = self._status
        if status == "CONNECTED" and (age is None or age > self.stale_after_s):
            status = "STALE"
        return {
            "source": "Binance Spot public market-data stream",
            "status": status,
            "read_only": True,
            "authenticated": False,
            "account_data_available": False,
            "order_execution_available": False,
            "symbols": list(self.symbols),
            "quotes": quotes,
            "asof_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "last_message_age_s": age,
            "stale_after_s": self.stale_after_s,
            "messages_received": self._messages,
            "reconnects": self._reconnects,
            "rest_errors": self._http_errors,
            "rejected_messages": self._rejected_messages,
            "last_rejected_event": self._last_rejected_event,
            "last_error": self._last_error,
            "note": "Live exchange prices are separate from the synthetic replay, paper fills, and paper PnL.",
        }

    def candles(self, symbol: str, interval_s: int = 60, limit: int = 500) -> dict[str, Any]:
        symbol = symbol.upper()
        if symbol not in self._bars:
            raise ValueError("symbol is not in the live market-data allowlist")
        if interval_s not in ALLOWED_INTERVALS:
            raise ValueError(f"interval must be one of {sorted(ALLOWED_INTERVALS)} seconds")
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        grouped: dict[int, dict[str, Any]] = {}
        for bar in self._bars[symbol]:
            bucket = int(bar["time"]) // interval_s * interval_s
            current = grouped.get(bucket)
            if current is None:
                grouped[bucket] = {"time": bucket, "open": bar["open"], "high": bar["high"],
                                   "low": bar["low"], "close": bar["close"], "volume": bar["volume"]}
            else:
                current["high"] = str(max(_d(current["high"], "high"), _d(bar["high"], "high")))
                current["low"] = str(min(_d(current["low"], "low"), _d(bar["low"], "low")))
                current["close"] = bar["close"]
                current["volume"] = str(_d(current["volume"], "volume") + _d(bar["volume"], "volume"))
        status = "LIVE_MARKET_DATA" if self._status == "CONNECTED" else "CACHED_PUBLIC_DATA" if grouped else "NO_DATA"
        return {"source": "Binance Spot public market-data REST + WebSocket", "data_status": status,
                "connection_status": self._status,
                "symbol": symbol, "symbols": list(self.symbols), "interval_seconds": interval_s,
                "candles": list(grouped.values())[-limit:],
                "read_only": True, "provenance": "public Binance Spot market data; not connected to account or execution"}
