"""Append-only ledger + trace + risk + audit. UPDATE/DELETE blocked by triggers.
SQLite is the default (with a process-wide write lock). PostgresStore is a real adapter (psycopg 3),
selected only when DATABASE_URL is set (e.g. a free Neon/Supabase database); it is never required."""
from __future__ import annotations
import abc, json, os, sqlite3, threading
from decimal import Decimal
from .models import TraceRow, RiskEvent

TABLES = {
 "trace": "trace_id TEXT PRIMARY KEY, ts TEXT, ticket_id TEXT, agent_id TEXT, crew TEXT, stage TEXT, msg_type TEXT, content TEXT, evidence TEXT, confidence TEXT",
 "ledger": "seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT DEFAULT CURRENT_TIMESTAMP, mode TEXT, ticket_id TEXT, kind TEXT, amount TEXT, fee TEXT, memo TEXT",
 "risk_events": "seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, ticket_id TEXT, reason TEXT, severity TEXT",
 "audit_log": "seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT DEFAULT CURRENT_TIMESTAMP, actor TEXT, action TEXT, detail TEXT",
}
INSERTS = {
 "trace": "INSERT INTO trace VALUES (?,?,?,?,?,?,?,?,?,?)",
 "ledger": "INSERT INTO ledger(mode,ticket_id,kind,amount,fee,memo) VALUES (?,?,?,?,?,?)",
 "risk_events": "INSERT INTO risk_events(ts,kind,ticket_id,reason,severity) VALUES (?,?,?,?,?)",
 "audit_log": "INSERT INTO audit_log(actor,action,detail) VALUES (?,?,?)",
}

class AppendOnlyStore(abc.ABC):
    """Typed write API shared by every backend; subclasses implement _insert/_select only."""
    @abc.abstractmethod
    def _insert(self, table: str, params: tuple) -> None: ...
    @abc.abstractmethod
    def rows(self, table: str) -> list: ...
    def append_trace(self, r: TraceRow):
        self._insert("trace", (r.trace_id, r.ts.isoformat(), r.ticket_id, r.agent_id, r.crew, r.stage, r.msg_type, r.content,
                               json.dumps(list(r.evidence_refs)), None if r.confidence is None else str(r.confidence)))
    def append_ledger(self, mode, ticket_id, kind, amount: Decimal, fee: Decimal, memo=""):
        if not isinstance(amount, Decimal) or not isinstance(fee, Decimal): raise TypeError("ledger amounts must be Decimal")
        self._insert("ledger", (mode, ticket_id, kind, str(amount), str(fee), memo))
    def append_risk(self, e: RiskEvent):
        self._insert("risk_events", (e.ts.isoformat(), e.kind, e.ticket_id, e.reason, e.severity))
    def audit(self, actor, action, detail=""):
        self._insert("audit_log", (actor, action, detail))
    def net_pnl(self, mode) -> Decimal:
        return sum((Decimal(r[5]) - Decimal(r[6]) for r in self.rows("ledger") if r[2] == mode), Decimal(0))

class SQLiteStore(AppendOnlyStore):
    backend = "sqlite"
    def __init__(self, path=":memory:"):
        self._lock = threading.RLock()   # serialises all writes/reads on the shared connection (asyncio.to_thread workers)
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=10)
        if path != ":memory:": self.db.execute("PRAGMA journal_mode=WAL")
        with self._lock:
            for t, cols in TABLES.items():
                self.db.execute(f"CREATE TABLE IF NOT EXISTS {t} ({cols})")
                for op in ("UPDATE","DELETE"):
                    self.db.execute(f"CREATE TRIGGER IF NOT EXISTS no_{op.lower()}_{t} BEFORE {op} ON {t} "
                                    f"BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END")
            self.db.commit()
    def _insert(self, table, params):
        with self._lock:
            self.db.execute(INSERTS[table], params); self.db.commit()
    def rows(self, table):
        if table not in TABLES: raise KeyError(table)
        with self._lock: return self.db.execute(f"SELECT * FROM {table}").fetchall()

PG_TABLES = {t: c.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY") for t, c in TABLES.items()}
class PostgresStore(AppendOnlyStore):
    """Real psycopg 3 adapter. Append-only enforced server-side by a trigger that raises on UPDATE/DELETE."""
    backend = "postgres"
    def __init__(self, url: str):
        import psycopg   # optional dependency
        self._lock = threading.RLock(); self.db = psycopg.connect(url, autocommit=True)
        with self._lock:
            self.db.execute("CREATE OR REPLACE FUNCTION crew_append_only() RETURNS trigger LANGUAGE plpgsql AS "
                            "$$ BEGIN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME; END $$")
            for t, cols in PG_TABLES.items():
                self.db.execute(f"CREATE TABLE IF NOT EXISTS {t} ({cols})")
                self.db.execute(f"DROP TRIGGER IF EXISTS {t}_append_only ON {t}")
                self.db.execute(f"CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE ON {t} "
                                f"FOR EACH ROW EXECUTE FUNCTION crew_append_only()")
    def _insert(self, table, params):
        with self._lock: self.db.execute(INSERTS[table].replace("?", "%s"), params)
    def rows(self, table):
        if table not in TABLES: raise KeyError(table)
        order = "ts" if table == "trace" else "seq"
        with self._lock: return [tuple(r) for r in self.db.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()]

def make_store(sqlite_path=":memory:") -> AppendOnlyStore:
    """DATABASE_URL (postgres://...) selects Postgres; otherwise SQLite. URL comes from env/.env only."""
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith(("postgres://", "postgresql://")): return PostgresStore(url)
    return SQLiteStore(sqlite_path)
