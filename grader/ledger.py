"""Ledger sinks. The pipeline reports state transitions; where they land is pluggable."""
from __future__ import annotations

import json
import urllib.request

TARGET = "celesto_sandbox"


class NullLedger:
    def update(self, run_id, sandbox_name, problem_id, state): ...


class StoreLedger:
    """Direct store access (used when the pipeline runs inside the api process)."""
    def __init__(self, store):
        self.store = store

    def update(self, run_id, sandbox_name, problem_id, state):
        self.store.upsert({"run_id": run_id, "sandbox_name": sandbox_name, "problem_id": problem_id,
                           "state": state, "execution_target": TARGET})


class HttpLedger:
    """POSTs to the Run Ledger API. Best-effort: a down ledger must never leak a sandbox."""
    def __init__(self, base_url):
        self.url = base_url.rstrip("/") + "/api/runs"
        self.errors = 0

    def update(self, run_id, sandbox_name, problem_id, state):
        body = json.dumps({"run_id": run_id, "sandbox_name": sandbox_name, "problem_id": problem_id,
                           "state": state, "execution_target": TARGET}).encode()
        try:
            req = urllib.request.Request(self.url, body, {"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5).read()
        except Exception:
            self.errors += 1
