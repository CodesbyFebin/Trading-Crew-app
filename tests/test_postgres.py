"""Runs only when TEST_DATABASE_URL points at a disposable Postgres (local or free Neon/Supabase)."""
import os, pytest
from decimal import Decimal as D
URL = os.environ.get("TEST_DATABASE_URL")
if not URL and os.environ.get("REQUIRE_POSTGRES") == "1":
    raise RuntimeError("REQUIRE_POSTGRES=1 but TEST_DATABASE_URL is not set (CI must run the Postgres tests, not skip them)")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")
def test_postgres_store_and_memory_append_only():
    import psycopg
    from crew.store import PostgresStore
    from crew.memory import SharedMemory, Fact
    s = PostgresStore(URL); n = len(s.rows("ledger"))
    s.append_ledger("PAPER", "t1", "BUY", D("-10"), D("0.01")); s.audit("test", "pg", "x")
    assert len(s.rows("ledger")) == n + 1
    with pytest.raises(psycopg.Error): s.db.execute("UPDATE ledger SET memo='y'")
    with pytest.raises(psycopg.Error): s.db.execute("DELETE FROM audit_log")
    m = SharedMemory(url=URL); c = m.count(); m.write(Fact("S45","recon","drift 0","metric","pg-test"))
    assert m.count() == c + 1 and m.search("drift 0")
    with pytest.raises(psycopg.Error): m.db.execute("DELETE FROM shared_memory")
def test_engine_on_postgres():
    from crew.engine import CrewSystem
    from crew.store import PostgresStore
    s = CrewSystem(store=PostgresStore(URL)); r = s.run_paper_day()
    assert r["D4"]["net_pnl_after_costs"] == "-3.6518"

def test_postgres_truncate_blocked():
    import psycopg
    from crew.store import PostgresStore, TABLES
    from crew.memory import SharedMemory
    s = PostgresStore(URL); m = SharedMemory(url=URL)
    for t in TABLES:
        with pytest.raises(psycopg.Error): s.db.execute(f"TRUNCATE {t}")
    with pytest.raises(psycopg.Error): m.db.execute("TRUNCATE shared_memory")

def test_postgres_concurrent_init_and_legacy_migration():
    """8 sessions initialise at once on a fresh schema that holds a pre-run_id ledger: no errors, rows preserved,
    each guard trigger exists exactly once."""
    import threading, uuid, psycopg
    from crew.store import PostgresStore, LEGACY_RUN
    from crew.memory import SharedMemory
    sch = "mig_" + uuid.uuid4().hex[:8]
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute(f"CREATE SCHEMA {sch}")
        c.execute(f"CREATE TABLE {sch}.ledger (seq BIGSERIAL PRIMARY KEY, ts TEXT DEFAULT CURRENT_TIMESTAMP, mode TEXT, ticket_id TEXT, kind TEXT, amount TEXT, fee TEXT, memo TEXT)")
        c.execute(f"INSERT INTO {sch}.ledger(mode,ticket_id,kind,amount,fee,memo) VALUES ('PAPER','old','BUY','-1','0.001','legacy row')")
    url = URL + ("&" if "?" in URL else "?") + f"options=-csearch_path%3D{sch}"
    errs = []
    def init():
        try: PostgresStore(url); SharedMemory(url=url)
        except Exception as e: errs.append(e)
    th = [threading.Thread(target=init) for _ in range(8)]; [t.start() for t in th]; [t.join() for t in th]
    assert errs == []
    s = PostgresStore(url)
    assert [r[7] for r in s.rows("ledger", LEGACY_RUN)] == ["legacy row"]
    with psycopg.connect(URL, autocommit=True) as c:
        n = c.execute("SELECT tgname, count(*) FROM pg_trigger t JOIN pg_class k ON k.oid=t.tgrelid JOIN pg_namespace ns ON ns.oid=k.relnamespace "
                      "WHERE ns.nspname=%s AND NOT tgisinternal GROUP BY tgname", (sch,)).fetchall()
        c.execute(f"DROP SCHEMA {sch} CASCADE")
    d = dict(n); assert d.get("ledger_append_only") == 1 and d.get("ledger_no_truncate") == 1 and d.get("shared_memory_no_truncate") == 1
    assert all(v == 1 for v in d.values())
