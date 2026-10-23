"""Append-only ledger + trace + risk + audit. UPDATE/DELETE blocked by triggers.
SQLite is the default (with a process-wide write lock). PostgresStore is a real adapter (psycopg 3),
selected only when DATABASE_URL is set (e.g. a free Neon/Supabase database); it is never required."""
from __future__ import annotations
import abc, json, os, sqlite3, threading, uuid
from decimal import Decimal
from .models import TraceRow, RiskEvent

# run_id is the LAST column so positional row access is unchanged; rows() never returns it.
TABLES = {
 "trace": "trace_id TEXT, ts TEXT, ticket_id TEXT, agent_id TEXT, crew TEXT, stage TEXT, msg_type TEXT, content TEXT, evidence TEXT, confidence TEXT, run_id TEXT NOT NULL, PRIMARY KEY (run_id, trace_id)",
 "ledger": "seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT DEFAULT CURRENT_TIMESTAMP, mode TEXT, ticket_id TEXT, kind TEXT, amount TEXT, fee TEXT, memo TEXT, run_id TEXT NOT NULL",
 "risk_events": "seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, ticket_id TEXT, reason TEXT, severity TEXT, run_id TEXT NOT NULL",
 "audit_log": "seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT DEFAULT CURRENT_TIMESTAMP, actor TEXT, action TEXT, detail TEXT, run_id TEXT NOT NULL",
}
COLS = {"trace": ["trace_id","ts","ticket_id","agent_id","crew","stage","msg_type","content","evidence","confidence"],
        "ledger": ["seq","ts","mode","ticket_id","kind","amount","fee","memo"],
        "risk_events": ["seq","ts","kind","ticket_id","reason","severity"], "audit_log": ["seq","ts","actor","action","detail"]}
INSERT_COLS = {"trace": COLS["trace"], "ledger": ["mode","ticket_id","kind","amount","fee","memo"],
               "risk_events": ["ts","kind","ticket_id","reason","severity"], "audit_log": ["actor","action","detail"]}
INSERTS = {t: f"INSERT INTO {t}({','.join(c + ['run_id'])}) VALUES ({','.join(['?']*(len(c)+1))})" for t, c in INSERT_COLS.items()}
ORDER = {"trace": "rowid", "ledger": "seq", "risk_events": "seq", "audit_log": "seq"}
LEGACY_RUN = "legacy"
_INIT_LOCK = threading.Lock()

class AppendOnlyStore(abc.ABC):
    """Typed write API shared by every backend; subclasses implement _insert/_select only.
    Every row carries this store's run_id; rows()/net_pnl() are scoped to it, so concurrent runs sharing one database
    never see each other's ledger, trace, risk events or audit rows."""
    run_id: str
    @abc.abstractmethod
    def _insert(self, table: str, params: tuple) -> None: ...
    @abc.abstractmethod
    def rows(self, table: str) -> list: ...
    @abc.abstractmethod
    def latest_safety_action(self):
        """Return the latest global kill/owner-reset audit action across runs."""
        ...
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
    def __init__(self, path=":memory:", run_id: str | None = None):
        self.run_id = run_id or uuid.uuid4().hex
        self._lock = threading.RLock()   # serialises all writes/reads on the shared connection (asyncio.to_thread workers)
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.db.execute("PRAGMA busy_timeout=30000")
        with _INIT_LOCK, self._lock:   # schema/migration is serialised in-process; busy_timeout covers other processes
            if path != ":memory:": self.db.execute("PRAGMA journal_mode=WAL")
            for t, cols in TABLES.items():
                self.db.execute(f"CREATE TABLE IF NOT EXISTS {t} ({cols})")
                have = [r[1] for r in self.db.execute(f"PRAGMA table_info({t})")]
                if "run_id" not in have:   # migration for pre-run_id databases (ADD COLUMN is not an UPDATE/DELETE)
                    self.db.execute(f"ALTER TABLE {t} ADD COLUMN run_id TEXT NOT NULL DEFAULT '{LEGACY_RUN}'")
                key = "trace_id" if t == "trace" else "seq"
                self.db.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{t}_run ON {t}(run_id, {key})")
                self.db.execute(f"CREATE INDEX IF NOT EXISTS ix_{t}_run ON {t}(run_id)")
                for op in ("UPDATE","DELETE"):
                    self.db.execute(f"CREATE TRIGGER IF NOT EXISTS no_{op.lower()}_{t} BEFORE {op} ON {t} "
                                    f"BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END")
            self.db.commit()
    def _insert(self, table, params):
        with self._lock:
            self.db.execute(INSERTS[table], (*params, self.run_id)); self.db.commit()
    def rows(self, table, run_id: str | None = None):
        if table not in TABLES: raise KeyError(table)
        with self._lock:
            return self.db.execute(f"SELECT {','.join(COLS[table])} FROM {table} WHERE run_id=? ORDER BY {ORDER[table]}",
                                   (run_id or self.run_id,)).fetchall()
    def run_ids(self):
        with self._lock: return [r[0] for r in self.db.execute("SELECT DISTINCT run_id FROM ledger UNION SELECT DISTINCT run_id FROM trace")]
    def latest_safety_action(self):
        with self._lock:
            return self.db.execute("SELECT action,detail,actor FROM audit_log WHERE action IN ('kill','kill_reset') ORDER BY seq DESC LIMIT 1").fetchone()

PG_TABLES = {t: c.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY") for t, c in TABLES.items()}
PG_ORDER = {"trace": "ts, trace_id", "ledger": "seq", "risk_events": "seq", "audit_log": "seq"}
class PostgresStore(AppendOnlyStore):
    """Real psycopg 3 adapter. Append-only enforced server-side by a trigger that raises on UPDATE/DELETE."""
    backend = "postgres"
    def __init__(self, url: str, run_id: str | None = None):
        self.run_id = run_id or uuid.uuid4().hex
        import psycopg   # optional dependency
        self._lock = threading.RLock(); self.db = psycopg.connect(url, autocommit=True, connect_timeout=int(os.environ.get("DB_CONNECT_TIMEOUT_S", "10")))
        with self._lock:
            self.db.execute("SELECT pg_advisory_lock(727001)")   # serialise concurrent DDL across sessions
            try:
                self.db.execute("CREATE OR REPLACE FUNCTION crew_append_only() RETURNS trigger LANGUAGE plpgsql AS "
                                "$$ BEGIN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME; END $$")
                for t, cols in PG_TABLES.items():
                    self.db.execute(f"CREATE TABLE IF NOT EXISTS {t} ({cols})")
                    self.db.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS run_id TEXT NOT NULL DEFAULT '{LEGACY_RUN}'")
                    key = "trace_id" if t == "trace" else "seq"
                    self.db.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{t}_run ON {t}(run_id, {key})")
                    self.db.execute(f"CREATE INDEX IF NOT EXISTS ix_{t}_run ON {t}(run_id)")
                    # Never drop the guard: a drop/create migration leaves a window
                    # where concurrent sessions can mutate the append-only ledger.
                    self.db.execute(f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger "
                                    f"WHERE tgname = '{t}_append_only' AND tgrelid = '{t}'::regclass "
                                    f"AND NOT tgisinternal) THEN CREATE TRIGGER {t}_append_only "
                                    f"BEFORE UPDATE OR DELETE ON {t} FOR EACH ROW "
                                    f"EXECUTE FUNCTION crew_append_only(); END IF; END $$")
                    # Row triggers do not fire on TRUNCATE; add a statement-level guard (idempotent, additive migration).
                    self.db.execute(f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger "
                                    f"WHERE tgname = '{t}_no_truncate' AND tgrelid = '{t}'::regclass "
                                    f"AND NOT tgisinternal) THEN CREATE TRIGGER {t}_no_truncate "
                                    f"BEFORE TRUNCATE ON {t} FOR EACH STATEMENT "
                                    f"EXECUTE FUNCTION crew_append_only(); END IF; END $$")
            finally: self.db.execute("SELECT pg_advisory_unlock(727001)")
    def _insert(self, table, params):
        with self._lock: self.db.execute(INSERTS[table].replace("?", "%s"), (*params, self.run_id))
    def rows(self, table, run_id: str | None = None):
        if table not in TABLES: raise KeyError(table)
        with self._lock:
            return [tuple(r) for r in self.db.execute(f"SELECT {','.join(COLS[table])} FROM {table} WHERE run_id=%s ORDER BY {PG_ORDER[table]}",
                                                      (run_id or self.run_id,)).fetchall()]
    def latest_safety_action(self):
        with self._lock:
            row = self.db.execute("SELECT action,detail,actor FROM audit_log WHERE action IN ('kill','kill_reset') ORDER BY seq DESC LIMIT 1").fetchone()
            return tuple(row) if row else None

def make_store(sqlite_path=":memory:", run_id: str | None = None) -> AppendOnlyStore:
    """DATABASE_URL (postgres://...) selects Postgres; otherwise SQLite. URL comes from env/.env only."""
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith(("postgres://", "postgresql://")): return PostgresStore(url, run_id)
    return SQLiteStore(sqlite_path, run_id)
