"""Single shared memory for all agents: append-only facts with agent id, timestamp, provenance.
SQLite default (reports/shared_memory.db or :memory:); Postgres when DATABASE_URL is set (free Neon/Supabase work).
Facts written by LLM paths are forced to kind='advisory' and can never be read by order/risk/mode code."""
from __future__ import annotations
import hashlib, json, os, sqlite3, threading
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone

KINDS = ("observation", "metric", "report", "advisory", "decision_record")
@dataclass(frozen=True)
class Fact:
    agent_id: str; topic: str; content: str; kind: str; provenance: str
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    advisory: bool = False
    def __post_init__(self):
        if self.kind not in KINDS: raise ValueError(f"kind must be one of {KINDS}")
        if not self.agent_id or not self.provenance: raise ValueError("agent_id and provenance are required")
        if self.kind == "advisory" and not self.advisory: raise ValueError("advisory facts must set advisory=True")
    @property
    def sha256(self): return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()

COLS = "seq {pk}, ts TEXT, agent_id TEXT, topic TEXT, kind TEXT, content TEXT, provenance TEXT, advisory INTEGER, sha256 TEXT"
class SharedMemory:
    def __init__(self, path: str = ":memory:", url: str | None = None):
        url = url if url is not None else os.environ.get("DATABASE_URL", "")
        self._lock = threading.RLock()
        if url.startswith(("postgres://", "postgresql://")):
            import psycopg
            self.backend, self.ph = "postgres", "%s"; self.db = psycopg.connect(url, autocommit=True, connect_timeout=int(os.environ.get("DB_CONNECT_TIMEOUT_S", "10")))
            self.db.execute("SELECT pg_advisory_lock(727001)")
            self.db.execute(f"CREATE TABLE IF NOT EXISTS shared_memory ({COLS.format(pk='BIGSERIAL PRIMARY KEY')})")
            self.db.execute("CREATE OR REPLACE FUNCTION crew_append_only() RETURNS trigger LANGUAGE plpgsql AS "
                            "$$ BEGIN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME; END $$")
            self.db.execute("DROP TRIGGER IF EXISTS shared_memory_append_only ON shared_memory")
            self.db.execute("CREATE TRIGGER shared_memory_append_only BEFORE UPDATE OR DELETE ON shared_memory "
                            "FOR EACH ROW EXECUTE FUNCTION crew_append_only()")
            self.db.execute("SELECT pg_advisory_unlock(727001)")
        else:
            self.backend, self.ph = "sqlite", "?"
            self.db = sqlite3.connect(path, check_same_thread=False, timeout=10)
            self.db.execute(f"CREATE TABLE IF NOT EXISTS shared_memory ({COLS.format(pk='INTEGER PRIMARY KEY AUTOINCREMENT')})")
            for op in ("UPDATE", "DELETE"):
                self.db.execute(f"CREATE TRIGGER IF NOT EXISTS mem_no_{op.lower()} BEFORE {op} ON shared_memory "
                                "BEGIN SELECT RAISE(ABORT, 'shared_memory is append-only'); END")
            self.db.commit()
    def write(self, f: Fact) -> int:
        q = ("INSERT INTO shared_memory(ts,agent_id,topic,kind,content,provenance,advisory,sha256) VALUES "
             f"({','.join([self.ph]*8)})")
        with self._lock:
            cur = self.db.execute(q, (f.ts, f.agent_id, f.topic, f.kind, f.content, f.provenance, int(f.advisory), f.sha256))
            if self.backend == "sqlite": self.db.commit()
        return self.count()
    def _q(self, where="", params=(), limit=200):
        with self._lock:
            rows = self.db.execute(f"SELECT seq,ts,agent_id,topic,kind,content,provenance,advisory,sha256 FROM shared_memory {where} "
                                   f"ORDER BY seq DESC LIMIT {int(limit)}", params).fetchall()
        return [dict(zip(("seq","ts","agent_id","topic","kind","content","provenance","advisory","sha256"), r)) | {"advisory": bool(r[7])} for r in rows]
    def read(self, topic: str | None = None, agent_id: str | None = None, limit=200):
        c, p = [], []
        if topic: c.append(f"topic={self.ph}"); p.append(topic)
        if agent_id: c.append(f"agent_id={self.ph}"); p.append(agent_id)
        return self._q(("WHERE " + " AND ".join(c)) if c else "", tuple(p), limit)
    def search(self, text: str, limit=50):
        like = f"%{text}%"
        return self._q(f"WHERE content LIKE {self.ph} OR topic LIKE {self.ph}", (like, like), limit)
    def count(self) -> int:
        with self._lock: return self.db.execute("SELECT COUNT(*) FROM shared_memory").fetchone()[0]
