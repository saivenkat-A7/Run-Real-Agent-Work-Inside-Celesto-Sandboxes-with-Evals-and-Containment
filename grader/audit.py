"""Append-only command audit log (logs/commands.jsonl). Every attempt is a line, blocked or not."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

EXECUTION_TARGET = "celesto_sandbox"


class Audit:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(self, sandbox_name: str, command: str, decision: str, reason: str = "", ts: str | None = None):
        assert decision in ("allow", "block")
        line = {"ts": ts or datetime.now(timezone.utc).isoformat(), "sandbox_name": sandbox_name,
                "command": command or "<empty>", "decision": decision,
                "execution_target": EXECUTION_TARGET}
        if reason:
            line["reason"] = reason
        with self._lock, self.path.open("a") as f:
            f.write(json.dumps(line) + "\n")
