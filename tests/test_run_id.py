import os, sqlite3, threading
from decimal import Decimal as D
import pytest
from crew.engine import CrewSystem
from crew.store import SQLiteStore, PostgresStore

def _concurrent(make):
    ref = {p: CrewSystem(fast=p[0], slow=p[1]).run_paper_day()["D4"] for p in ((20, 60), (10, 30))}
    out = {}
    errs = []
    def go(p):
        try: s = CrewSystem(fast=p[0], slow=p[1], store=make()); out[p] = (s.run_paper_day()["D4"], s.store)
        except Exception as e: errs.append(repr(e))
    ts = [threading.Thread(target=go, args=(p,)) for p in ref]; [t.start() for t in ts]; [t.join() for t in ts]
    assert not errs and len(out) == 2, errs
    for p, (d, st) in out.items():
        for k in ("net_pnl_after_costs", "fills", "round_trips", "winning_round_trips", "reconciliation_drift", "equity_curve"):
            assert d[k] == ref[p][k], (p, k)
        assert D(d["reconciliation_drift"]) == 0
        assert len(st.rows("ledger")) == d["fills"]
    a, b = (st for _, st in out.values()); assert a.run_id != b.run_id

def test_two_concurrent_runs_sqlite_file(tmp_path):
    db = str(tmp_path/"shared.db"); _concurrent(lambda: SQLiteStore(db))

def test_migration_of_pre_run_id_db(tmp_path):
    db = str(tmp_path/"old.db"); c = sqlite3.connect(db)
    c.execute("CREATE TABLE ledger (seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT DEFAULT CURRENT_TIMESTAMP, mode TEXT, ticket_id TEXT, kind TEXT, amount TEXT, fee TEXT, memo TEXT)")
    c.execute("INSERT INTO ledger(mode,ticket_id,kind,amount,fee,memo) VALUES ('PAPER','old','BUY','-5','0.1','')"); c.commit(); c.close()
    s = SQLiteStore(db); assert s.rows("ledger") == [] and len(s.rows("ledger", run_id="legacy")) == 1
    s.append_ledger("PAPER", "new", "BUY", D("-1"), D("0.01")); assert s.net_pnl("PAPER") == D("-1.01")
    with pytest.raises(sqlite3.DatabaseError): s.db.execute("UPDATE ledger SET memo='x'")
    cols = [r[1] for r in s.db.execute("PRAGMA table_info(ledger)")]; assert cols[-1] == "run_id"

@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")
def test_two_concurrent_runs_postgres():
    _concurrent(lambda: PostgresStore(os.environ["TEST_DATABASE_URL"]))
