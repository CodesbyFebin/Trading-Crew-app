"""Mode ladder + promotion gates (pure functions over recorded stats)."""
from __future__ import annotations
import enum, os
from dataclasses import dataclass
from decimal import Decimal
from .models import Approval

class Mode(str, enum.Enum):
    REPLAY="REPLAY"; PAPER="PAPER"; LIVE_APPROVAL="LIVE_APPROVAL"; LIVE_AUTO="LIVE_AUTO"
LADDER = [Mode.REPLAY, Mode.PAPER, Mode.LIVE_APPROVAL, Mode.LIVE_AUTO]
def live_enabled() -> bool: return os.environ.get("LIVE_ENABLED","false").lower() == "true"

@dataclass(frozen=True)
class Stats:
    oos_net_expectancy: Decimal | None = None; calibration_ok: bool = False
    paper_days: int = 0; paper_net_expectancy: Decimal | None = None
    reconciliation_drift: Decimal | None = None; kill_drill_passed: bool = False
    live_days: int = 0; slippage_within_model: bool = False

@dataclass(frozen=True)
class GateResult:
    allowed: bool; reasons: tuple[str,...]

def gate(frm: Mode, to: Mode, s: Stats, approval: Approval | None = None) -> GateResult:
    r = []
    if LADDER.index(to) != LADDER.index(frm) + 1: return GateResult(False, ("can only promote one rung",))
    if to is Mode.PAPER:
        if s.oos_net_expectancy is None or s.oos_net_expectancy <= 0: r.append("needs positive out-of-sample net expectancy")
        if not s.calibration_ok: r.append("needs calibration")
    elif to is Mode.LIVE_APPROVAL:
        if s.paper_days < 30: r.append(f"needs 30+ paper days (have {s.paper_days})")
        if s.paper_net_expectancy is None or s.paper_net_expectancy <= 0: r.append("needs positive paper net expectancy")
        if s.reconciliation_drift is None or s.reconciliation_drift != 0: r.append("reconciliation drift present/unknown")
        if not s.kill_drill_passed: r.append("kill-switch drill not passed")
        if not live_enabled(): r.append("LIVE_ENABLED=false")
    elif to is Mode.LIVE_AUTO:
        if s.live_days < 30: r.append(f"needs 30+ supervised live days (have {s.live_days})")
        if not s.slippage_within_model: r.append("live slippage outside/unknown versus model")
        if s.reconciliation_drift is None or s.reconciliation_drift != 0: r.append("reconciliation drift present/unknown")
        if not s.kill_drill_passed: r.append("kill-switch drill not passed")
        if not live_enabled(): r.append("LIVE_ENABLED=false")
    if LADDER.index(to) > LADDER.index(Mode.PAPER):
        want = f"promote:{frm.value}->{to.value}"
        if approval is None or not approval.verify() or approval.subject != want or approval.decision != "APPROVE":
            r.append("signed owner approval required")
    return GateResult(not r, tuple(r))

class ModeController:
    def __init__(self, log=None):
        self.mode = Mode.PAPER; self.log = log if log is not None else []
    def promote(self, to: Mode, s: Stats, approval=None) -> GateResult:
        g = gate(self.mode, to, s, approval)
        self.log.append(("promote", self.mode.value, to.value, g.allowed, g.reasons))
        if g.allowed: self.mode = to
        return g
    def demote(self, reason: str) -> Mode:
        i = LADDER.index(self.mode)
        if i > 0: self.mode = LADDER[i-1]
        self.log.append(("auto-demote", self.mode.value, reason)); return self.mode
    def on_breach(self, reason: str) -> Mode: return self.demote(reason)
