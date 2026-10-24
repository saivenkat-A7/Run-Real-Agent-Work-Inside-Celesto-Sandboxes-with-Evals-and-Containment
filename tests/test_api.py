from fastapi.testclient import TestClient

from app.db import MemoryStore
from app.main import create_app

c = TestClient(create_app(MemoryStore()))
GOOD = {"run_id": "r1", "sandbox_name": "sbx-abcdef12", "problem_id": "p", "state": "created",
        "execution_target": "celesto_sandbox"}


def test_health():
    r = c.get("/health"); assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_seed_listed():
    r = c.get("/api/runs"); assert r.status_code == 200
    assert "sbx-seeddemo1" in [x["sandbox_name"] for x in r.json()]


def test_post_ok_and_listed():
    r = c.post("/api/runs", json=GOOD); assert r.status_code == 201 and r.json()["run_id"] == "r1"
    assert any(x["run_id"] == "r1" for x in c.get("/api/runs").json())


def test_post_rejects():
    for bad in ({**GOOD, "execution_target": "host"}, {**GOOD, "state": "weird"},
                {**GOOD, "sandbox_name": "sbx-SHORT"}, {**GOOD, "sandbox_name": "nope-abcdef12"},
                {k: v for k, v in GOOD.items() if k != "run_id"}, [1]):
        assert c.post("/api/runs", json=bad).status_code == 400
    assert c.post("/api/runs", content=b"{not json", headers={"content-type": "application/json"}).status_code == 400


def test_reports_served():
    assert c.get("/reports/reliability.json").status_code == 200
