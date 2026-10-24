"""Run-ledger storage: Postgres in production, in-memory for tests (DATABASE_URL=memory:)."""
from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime, timezone

NAME_RE = re.compile(r"^sbx-[a-z0-9]{8,}$")
STATES = ("created", "ready", "running", "succeeded", "failed", "deleted")
TARGET = "celesto_sandbox"
FIELDS = ("run_id", "sandbox_name", "problem_id", "state", "execution_target")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    sandbox_name TEXT NOT NULL CHECK (sandbox_name ~ '^sbx-[a-z0-9]{8,}$'),
    problem_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('created','ready','running','succeeded','failed','deleted')),
    execution_target TEXT NOT NULL CHECK (execution_target = 'celesto_sandbox'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)"""

SEED = {"run_id": "run-seeddemo1", "sandbox_name": "sbx-seeddemo1",
        "problem_id": "hostile-submission-autograder", "state": "deleted",
        "execution_target": TARGET}

UPSERT = ("INSERT INTO runs (run_id, sandbox_name, problem_id, state, execution_target) "
          "VALUES (%(run_id)s, %(sandbox_name)s, %(problem_id)s, %(state)s, %(execution_target)s) ")


def validate(body) -> tuple[dict | None, str | None]:
    """Return (clean_row, error). Any error maps to HTTP 400."""
    if not isinstance(body, dict):
        return None, "body must be a JSON object"
    row = {}
    for f in FIELDS:
        v = body.get(f)
        if not isinstance(v, str) or not v.strip():
            return None, f"{f} must be a non-empty string"
        row[f] = v
    if not NAME_RE.match(row["sandbox_name"]):
        return None, "sandbox_name must match sbx-[a-z0-9]{8,}"
    if row["state"] not in STATES:
        return None, f"state must be one of {STATES}"
    if row["execution_target"] != TARGET:
        return None, f"execution_target must be '{TARGET}'"
    return row, None


class MemoryStore:
    def __init__(self):
        self._rows: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.upsert(dict(SEED))

    def upsert(self, row: dict) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            old = self._rows.get(row["run_id"])
            stored = {**row, "created_at": old["created_at"] if old else now, "updated_at": now}
            self._rows[row["run_id"]] = stored
            return dict(stored)

    def list(self) -> list[dict]:
        with self._lock:
            return sorted((dict(r) for r in self._rows.values()), key=lambda r: (r["created_at"], r["run_id"]))


class PgStore:
    def __init__(self, url: str, wait_s: float = 60.0):
        import psycopg
        from psycopg.rows import dict_row
        self._psycopg, self._dict_row, self.url = psycopg, dict_row, url
        deadline = time.time() + wait_s
        while True:
            try:
                with self._conn() as c:
                    c.execute(SCHEMA)  # no-op when the seed SQL already created it
                    c.execute(UPSERT + "ON CONFLICT (run_id) DO NOTHING", SEED)
                return
            except Exception:
                if time.time() > deadline:
                    raise
                time.sleep(1)

    def _conn(self):
        return self._psycopg.connect(self.url, autocommit=True, row_factory=self._dict_row)

    def upsert(self, row: dict) -> dict:
        with self._conn() as c:
            cur = c.execute(
                UPSERT + "ON CONFLICT (run_id) DO UPDATE SET sandbox_name=EXCLUDED.sandbox_name, "
                "problem_id=EXCLUDED.problem_id, state=EXCLUDED.state, updated_at=now() RETURNING *", row)
            return _ser(cur.fetchone())

    def list(self) -> list[dict]:
        with self._conn() as c:
            return [_ser(r) for r in c.execute("SELECT * FROM runs ORDER BY created_at, run_id").fetchall()]


def _ser(r: dict) -> dict:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()}


def make_store(url: str | None = None):
    url = url or os.environ.get("DATABASE_URL", "memory:")
    return MemoryStore() if url.startswith("memory:") else PgStore(url)
