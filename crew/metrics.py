"""Prometheus exposition built fresh per scrape from real engine telemetry (no global counters, no invented values)."""
from __future__ import annotations
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST

LAT_BUCKETS = (0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)

def render(tel: dict, kill_engaged: bool, mode: str, run_id: str | None, drills: dict) -> tuple[bytes, str]:
    r = CollectorRegistry()
    Counter("crew_intents_submitted", "Order intents submitted to the risk engine (this run)", registry=r).inc(tel["intents_submitted"])
    rej = Counter("crew_rejects", "Rejected signals/intents by reason (this run)", ["reason"], registry=r)
    for k, v in tel["rejects"].items(): rej.labels(k).inc(v)
    Counter("crew_risk_breaches", "Risk-engine vetoes (this run)", registry=r).inc(tel["risk_breaches"])
    q = Counter("crew_quorum_outcomes", "Overseer quorum outcomes (this run)", ["outcome"], registry=r)
    for k, v in tel["quorum"].items(): q.labels(k).inc(v)
    h = Histogram("crew_signal_to_decision_seconds", "Wall time from signal to ticket decision (quorum reject, veto or approval)",
                  buckets=LAT_BUCKETS, registry=r)
    for x in tel["latency_s"]: h.observe(x)
    Gauge("crew_kill_switch_engaged", "1 if the kill switch is engaged", registry=r).set(1 if kill_engaged else 0)
    Gauge("crew_mode_info", "Current mode", ["mode", "run_id"], registry=r).labels(mode, run_id or "").set(1)
    dlq = (drills or {}).get("bus_chaos", {}).get("dlq_reasons")
    if dlq is not None:   # the runtime engine has no message bus; the only bus that runs is the drill's InProcessBus
        Gauge("crew_bus_dlq_size", "Dead-letter queue size of the last bus_chaos drill run", ["source"], registry=r).labels("drill").set(len(dlq))
    return generate_latest(r), CONTENT_TYPE_LATEST
