from __future__ import annotations
from .models import Ticket, TicketState, RiskEvent
class KillSwitch:
    def __init__(self): self.engaged=False; self.reason=""; self.desks_halted: set[str]=set(); self.events=[]
    def engage(self, reason: str, desks, tickets: list[Ticket]):
        self.engaged, self.reason = True, reason
        self.desks_halted = set(desks)
        for t in tickets:
            if t.is_open:
                t.flags.add("KILLED")
                for to in (TicketState.VETOED, TicketState.EXPIRED, TicketState.FAILED):
                    try: t.transition(to, f"kill: {reason}"); break
                    except Exception: continue
        self.events.append(RiskEvent("KILL", None, reason, "CRITICAL"))
    def allow_new_order(self) -> bool: return not self.engaged
    def reset(self, owner_approval) -> bool:
        if owner_approval is not None and owner_approval.verify() and owner_approval.subject=="kill:reset" and owner_approval.decision=="APPROVE":
            self.engaged=False; self.desks_halted=set(); return True
        return False
