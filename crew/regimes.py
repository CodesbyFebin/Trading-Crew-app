"""Causal regime labels and descriptive stratification for local replay data.

This is a research/reporting feature only. Its output does not route strategies,
create order intents, or change risk limits. Labels use only current and prior
feature rows for the same symbol; no exchange or news feeds are used.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from typing import Iterable

from .desk_d4 import Feat

D = Decimal


@dataclass(frozen=True)
class RegimeVector:
    timestamp: int
    symbol: str
    trend: str
    volatility: str
    spread: str
    label: str
    prior_observations: int

    def as_dict(self) -> dict[str, int | str]:
        return {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "trend": self.trend,
            "volatility": self.volatility,
            "spread": self.spread,
            "label": self.label,
            "prior_observations": self.prior_observations,
        }


def classify_replay_features(
    features: Iterable[Feat],
    *,
    slope_threshold: Decimal = D("0.0001"),
    baseline_window: int = 60,
    minimum_baseline: int = 20,
    high_volatility_multiple: Decimal = D("1.5"),
    wide_spread_multiple: Decimal = D("1.5"),
) -> dict[tuple[str, int], RegimeVector]:
    """Classify replay features with trailing medians, excluding the current row.

    The fixed defaults are transparent research thresholds, not tuned parameters
    and not a production market-regime model. Input must be chronological within
    each symbol. Insufficient history is reported as UNKNOWN.
    """
    if baseline_window < 1 or minimum_baseline < 1 or minimum_baseline > baseline_window:
        raise ValueError("baseline window must be positive and cover the minimum baseline")
    for name, value in (("slope_threshold", slope_threshold),
                        ("high_volatility_multiple", high_volatility_multiple),
                        ("wide_spread_multiple", wide_spread_multiple)):
        if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
            raise ValueError(f"{name} must be a finite non-negative Decimal")

    history: dict[str, tuple[deque[Decimal], deque[Decimal]]] = {}
    last_ts: dict[str, int] = {}
    vectors: dict[tuple[str, int], RegimeVector] = {}
    for feature in features:
        if not isinstance(feature, Feat):
            raise TypeError("replay regime input must contain Feat rows")
        if not feature.symbol or feature.ts <= 0:
            raise ValueError("feature requires a symbol and positive timestamp")
        if feature.symbol in last_ts and feature.ts <= last_ts[feature.symbol]:
            raise ValueError(f"features for {feature.symbol} must be strictly chronological")
        if not all(isinstance(value, Decimal) and value.is_finite() for value in
                   (feature.slope, feature.vol, feature.spread_bps)):
            raise ValueError("regime inputs must be finite Decimal values")
        if feature.vol < 0 or feature.spread_bps < 0:
            raise ValueError("volatility and spread must be non-negative")

        vol_history, spread_history = history.setdefault(
            feature.symbol,
            (deque(maxlen=baseline_window), deque(maxlen=baseline_window)),
        )
        trend = "TREND_UP" if feature.slope > slope_threshold else (
            "TREND_DOWN" if feature.slope < -slope_threshold else "CHOP"
        )
        prior_count = min(len(vol_history), len(spread_history))
        if prior_count < minimum_baseline:
            volatility = spread = "UNKNOWN"
        else:
            vol_median = D(str(median(vol_history)))
            spread_median = D(str(median(spread_history)))
            volatility = "HIGH" if vol_median > 0 and feature.vol >= vol_median * high_volatility_multiple else "BASELINE"
            spread = "WIDE" if spread_median > 0 and feature.spread_bps >= spread_median * wide_spread_multiple else "BASELINE"

        label = f"{trend}|VOL_{volatility}|SPREAD_{spread}"
        vectors[(feature.symbol, feature.ts)] = RegimeVector(
            feature.ts, feature.symbol, trend, volatility, spread, label, prior_count
        )
        # Append only after classification so the current observation cannot
        # influence its own baseline.
        vol_history.append(feature.vol)
        spread_history.append(feature.spread_bps)
        last_ts[feature.symbol] = feature.ts
    return vectors


def summarize_realized_by_regime(trades: Iterable[tuple[str, Decimal]]) -> list[dict[str, str | int]]:
    """Summarize closed replay outcomes by entry regime, after modeled costs."""
    groups: dict[str, list[Decimal]] = defaultdict(list)
    for regime, net_pnl in trades:
        if not isinstance(regime, str) or not regime:
            raise ValueError("trade regime must be a non-empty label")
        if not isinstance(net_pnl, Decimal) or not net_pnl.is_finite():
            raise ValueError("trade P&L must be a finite Decimal")
        groups[regime].append(net_pnl)

    rows = []
    for regime, values in sorted(groups.items()):
        net = sum(values, D(0))
        rows.append({
            "regime": regime,
            "closed_trades": len(values),
            "positive_trades": sum(value > 0 for value in values),
            "negative_trades": sum(value < 0 for value in values),
            "net_pnl_after_costs": str(net.quantize(D("0.0001"))),
            "mean_net_pnl": str((net / len(values)).quantize(D("0.0001"))),
        })
    return rows
