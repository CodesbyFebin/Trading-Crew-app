"""Runs only when TEST_DATABASE_URL points at a disposable Postgres (local or free Neon/Supabase)."""
import os, pytest
from decimal import Decimal as D
URL = os.environ.get("TEST_DATABASE_URL")
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
