"""SQLite append-only ledger + trace. UPDATE/DELETE blocked by triggers."""
from __future__ import annotations
import abc, json, sqlite3
from decimal import Decimal
from .models import TraceRow, RiskEvent

TABLES = {
 "trace": "trace_id TEXT PRIMARY KEY, ts TEXT, ticket_id TEXT, agent_id TEXT, crew TEXT, stage TEXT, msg_type TEXT, content TEXT, evidence TEXT, confidence TEXT",
 "ledger": "seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT DEFAULT CURRENT_TIMESTAMP, mode TEXT, ticket_id TEXT, kind TEXT, amount TEXT, fee TEXT, memo TEXT",
 "risk_events": "seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, ticket_id TEXT, reason TEXT, severity TEXT",
 "audit_log": "seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT DEFAULT CURRENT_TIMESTAMP, actor TEXT, action TEXT, detail TEXT",
}
class AppendOnlyStore(abc.ABC):
    @abc.abstractmethod
    def append_trace(self, r: TraceRow) -> None: ...

class SQLiteStore(AppendOnlyStore):
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)  # writes serialized by GIL + single writer
        for t, cols in TABLES.items():
            self.db.execute(f"CREATE TABLE IF NOT EXISTS {t} ({cols})")
            for op in ("UPDATE","DELETE"):
                self.db.execute(f"CREATE TRIGGER IF NOT EXISTS no_{op.lower()}_{t} BEFORE {op} ON {t} "
                                f"BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END")
        self.db.commit()
    def append_trace(self, r):
        self.db.execute("INSERT INTO trace VALUES (?,?,?,?,?,?,?,?,?,?)", (r.trace_id, r.ts.isoformat(), r.ticket_id, r.agent_id,
            r.crew, r.stage, r.msg_type, r.content, json.dumps(list(r.evidence_refs)), None if r.confidence is None else str(r.confidence)))
        self.db.commit()
    def append_ledger(self, mode, ticket_id, kind, amount: Decimal, fee: Decimal, memo=""):
        if not isinstance(amount, Decimal) or not isinstance(fee, Decimal): raise TypeError("ledger amounts must be Decimal")
        self.db.execute("INSERT INTO ledger(mode,ticket_id,kind,amount,fee,memo) VALUES (?,?,?,?,?,?)", (mode,ticket_id,kind,str(amount),str(fee),memo))
        self.db.commit()
    def append_risk(self, e: RiskEvent):
        self.db.execute("INSERT INTO risk_events(ts,kind,ticket_id,reason,severity) VALUES (?,?,?,?,?)", (e.ts.isoformat(),e.kind,e.ticket_id,e.reason,e.severity)); self.db.commit()
    def audit(self, actor, action, detail=""):
        self.db.execute("INSERT INTO audit_log(actor,action,detail) VALUES (?,?,?)", (actor,action,detail)); self.db.commit()
    def rows(self, table):
        return self.db.execute(f"SELECT * FROM {table}").fetchall()
    def net_pnl(self, mode) -> Decimal:
        return sum((Decimal(a)-Decimal(f) for a,f in self.db.execute("SELECT amount,fee FROM ledger WHERE mode=?", (mode,))), Decimal(0))

class PostgresStore(AppendOnlyStore):  # stub interface only
    def __init__(self, *a, **k): raise NotImplementedError("Postgres adapter not built in Phase 1")
    def append_trace(self, r): ...
