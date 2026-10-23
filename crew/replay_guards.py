"""Offline-only validators for archived India policy checks and wallet replay fixtures.

This module has no broker SDK, network client, signer, order method, or external
data source. It is not a SEBI compliance adapter and must not be wired to live
market feeds or execution. D5 remains archived/checks-only.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


class ReplayInputError(ValueError):
    """Input cannot safely be used in an offline replay."""


def require_cnc_product(product_type: str) -> None:
    """Reject non-CNC product labels in India policy fixtures; sends no orders."""
    if not isinstance(product_type, str) or product_type.upper() != "CNC":
        raise ReplayInputError("India Gate 0 policy fixture allows CNC only; no broker execution is implemented")


_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


class WalletActivityReplay:
    """Normalize explicitly identified trade fills from local replay fixtures.

    The source must provide a stable ``fill_id`` (or source event ID). A tx hash
    alone is insufficient because one transaction can contain multiple fills.
    Deduplication is process-local and intended only for replay tests.
    """

    def __init__(self, leader_address: str):
        if not isinstance(leader_address, str) or not _ADDRESS_RE.fullmatch(leader_address):
            raise ReplayInputError("leader_address must be a 20-byte 0x-prefixed address")
        self.leader_address = leader_address.lower()
        self._seen_fill_ids: set[str] = set()

    @staticmethod
    def _decimal(value: Any, field: str) -> Decimal:
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            raise ReplayInputError(f"{field} must be a finite decimal") from None
        if not result.is_finite():
            raise ReplayInputError(f"{field} must be a finite decimal")
        return result

    def process_page(self, activities: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for item in activities:
            if not isinstance(item, dict):
                raise ReplayInputError("each activity must be an object")
            if str(item.get("type", "")).upper() != "TRADE":
                continue

            fill_id = item.get("fill_id")
            tx_hash = item.get("transaction_hash")
            token_id = item.get("token_id")
            side = str(item.get("side", "")).upper()
            if not isinstance(fill_id, str) or not fill_id.strip():
                raise ReplayInputError("trade activity requires a stable source fill_id")
            if not isinstance(tx_hash, str) or not tx_hash.strip():
                raise ReplayInputError("trade activity requires transaction_hash")
            if not isinstance(token_id, str) or not token_id.strip():
                raise ReplayInputError("trade activity requires token_id")
            if side not in {"BUY", "SELL"}:
                raise ReplayInputError("side must be BUY or SELL")

            price = self._decimal(item.get("price"), "price")
            size = self._decimal(item.get("size"), "size")
            if price <= 0 or size <= 0:
                raise ReplayInputError("price and size must be positive")
            if fill_id in self._seen_fill_ids:
                continue

            notional_raw = item.get("usdc_size")
            notional = self._decimal(notional_raw, "usdc_size") if notional_raw is not None else price * size
            if notional <= 0:
                raise ReplayInputError("usdc_size must be positive")
            self._seen_fill_ids.add(fill_id)
            events.append({
                "event_id": fill_id,
                "leader_address": self.leader_address,
                "tx_hash": tx_hash,
                "token_id": token_id,
                "side": side,
                "price": price,
                "size": size,
                "usdc_notional": notional,
                "timestamp": item.get("timestamp"),
                "outcome_index": item.get("outcome_index"),
            })
        return events
