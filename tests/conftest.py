import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("CREW_APPROVAL_HMAC_KEY", "test-only-key")
os.environ["LIVE_ENABLED"] = "false"
os.environ["CREW_MEMORY_PATH"] = ":memory:"
for _k in ("OPENROUTER_API_KEY","KILOCODE_API_KEY","GROQ_API_KEY","CLINE_API_KEY","DATABASE_URL","REDIS_URL"): os.environ.pop(_k, None)
os.environ.update(CREW_OWNER_TOKEN="own-t", CREW_OPERATOR_TOKEN="op-t", CREW_VIEWER_TOKEN="view-t")
import pytest
@pytest.fixture(scope="session")
def paper():
    from crew.engine import CrewSystem
    s = CrewSystem(); s.run_paper_day(); return s
@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from crew.api import app
    with TestClient(app) as c: yield c
