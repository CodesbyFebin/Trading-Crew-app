"""Typed data contracts. Modules talk only via these dataclasses. No floats for money."""
from __future__ import annotations
import enum, hashlib, hmac, json, os, uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

def now() -> datetime: return datetime.now(timezone.utc)

class TicketState(str, enum.Enum):
    DISCOVERED="DISCOVERED"; ENRICHED="ENRICHED"; PRICED="PRICED"; RESEARCHED="RESEARCHED"
    RISK_CLEARED="RISK_CLEARED"; APPROVED="APPROVED"; ORDERED="ORDERED"; FILLED="FILLED"
    SETTLED="SETTLED"; AUDITED="AUDITED"
    REJECTED="REJECTED"; VETOED="VETOED"; EXPIRED="EXPIRED"; FAILED="FAILED"

S = TicketState
TERMINAL = {S.AUDITED}
_HAPPY = [S.DISCOVERED,S.ENRICHED,S.PRICED,S.RESEARCHED,S.RISK_CLEARED,S.APPROVED,S.ORDERED,S.FILLED,S.SETTLED,S.AUDITED]
LEGAL: dict[TicketState, set[TicketState]] = {s:set() for s in S}
for a,b in zip(_HAPPY,_HAPPY[1:]): LEGAL[a].add(b)
for s in [S.DISCOVERED,S.ENRICHED,S.PRICED,S.RESEARCHED]: LEGAL[s] |= {S.REJECTED,S.EXPIRED,S.FAILED}
LEGAL[S.RESEARCHED].add(S.VETOED)          # risk gate veto
LEGAL[S.RISK_CLEARED] |= {S.REJECTED,S.EXPIRED,S.VETOED}  # human reject / timeout / kill
LEGAL[S.APPROVED] |= {S.VETOED,S.EXPIRED,S.FAILED}
LEGAL[S.ORDERED] |= {S.FAILED,S.EXPIRED}
LEGAL[S.FILLED] |= {S.FAILED}
for s in [S.REJECTED,S.VETOED,S.EXPIRED,S.FAILED]: LEGAL[s] = {S.AUDITED}  # closed tickets still get audited

class IllegalTransition(Exception): pass

@dataclass(frozen=True)
class Event:
    source: str; kind: str; payload: dict[str,Any]
    idempotency_key: str
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: datetime = field(default_factory=now)

@dataclass
class Ticket:
    desk: str; instrument: str; venue: str
    ticket_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: TicketState = TicketState.DISCOVERED
    history: list[tuple[str,str,str]] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)
    def transition(self, to: TicketState, reason: str = "") -> None:
        if not isinstance(to, TicketState) or to not in LEGAL[self.state]:
            raise IllegalTransition(f"{self.state} -> {to}")
        self.history.append((self.state.value, to.value, reason)); self.state = to
    @property
    def is_open(self) -> bool:
        return self.state not in {S.AUDITED,S.SETTLED,S.REJECTED,S.VETOED,S.EXPIRED,S.FAILED}

@dataclass(frozen=True)
class TraceRow:
    """Message contract: who said what about which ticket, with evidence."""
    ticket_id: str; agent_id: str; crew: str; stage: str
    msg_type: str            # e.g. CLAIM / RESULT / VETO / ESCALATE / HALT
    content: str
    evidence_refs: tuple[str,...] = ()
    confidence: Decimal | None = None
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: datetime = field(default_factory=now)

@dataclass(frozen=True)
class RiskEvent:
    kind: str; ticket_id: str | None; reason: str
    severity: str = "BLOCK"
    ts: datetime = field(default_factory=now)

# ---- signed approvals (HMAC key from env only) ----
APPROVAL_KEY_ENV = "CREW_APPROVAL_HMAC_KEY"
class ApprovalKeyMissing(Exception): pass
def _key() -> bytes:
    k = os.environ.get(APPROVAL_KEY_ENV)
    if not k: raise ApprovalKeyMissing(f"{APPROVAL_KEY_ENV} not set")
    return k.encode()

@dataclass(frozen=True)
class Approval:
    subject: str          # e.g. "promote:PAPER->LIVE_APPROVAL" or ticket id
    approver: str; decision: str   # APPROVE / REJECT
    ts: str = field(default_factory=lambda: now().isoformat())
    signature: str = ""
    def _msg(self) -> bytes:
        return json.dumps([self.subject,self.approver,self.decision,self.ts]).encode()
    def signed(self) -> "Approval":
        sig = hmac.new(_key(), self._msg(), hashlib.sha256).hexdigest()
        return Approval(self.subject,self.approver,self.decision,self.ts,sig)
    def verify(self) -> bool:
        try: exp = hmac.new(_key(), self._msg(), hashlib.sha256).hexdigest()
        except ApprovalKeyMissing: return False
        return bool(self.signature) and hmac.compare_digest(exp, self.signature)

# ---- versioned append-only config ----
@dataclass(frozen=True)
class ConfigVersion:
    version: int; data: dict[str,Any]; author: str; note: str; sha256: str

class ConfigStore:
    def __init__(self): self._v: list[ConfigVersion] = []
    def commit(self, data: dict, author: str, note: str = "") -> ConfigVersion:
        blob = json.dumps(data, sort_keys=True, default=str)
        cv = ConfigVersion(len(self._v)+1, json.loads(blob), author, note, hashlib.sha256(blob.encode()).hexdigest())
        self._v.append(cv); return cv
    def current(self) -> ConfigVersion: return self._v[-1]
    def get(self, v: int) -> ConfigVersion: return self._v[v-1]
    @property
    def versions(self) -> tuple[ConfigVersion,...]: return tuple(self._v)
    def diff(self, a: int, b: int) -> dict[str, tuple[Any,Any]]:
        da, db = self.get(a).data, self.get(b).data
        return {k:(da.get(k),db.get(k)) for k in sorted(set(da)|set(db)) if da.get(k)!=db.get(k)}
    def rollback(self, to: int, author: str) -> ConfigVersion:
        """Rollback = new version copying an old one; history never rewritten."""
        return self.commit(self.get(to).data, author, f"rollback to v{to}")
