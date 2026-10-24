"""Run Ledger API (trusted control plane)."""
from __future__ import annotations

import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.db import make_store, validate

ROOT = Path(__file__).resolve().parent.parent


def create_app(store=None) -> FastAPI:
    app = FastAPI(title="Run Ledger API")
    app.state.store = store or make_store()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/runs")
    def list_runs():
        return app.state.store.list()

    @app.post("/api/runs")
    async def post_run(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)
        row, err = validate(body)
        if err:
            return JSONResponse({"error": err}, status_code=400)
        return JSONResponse(app.state.store.upsert(row), status_code=201)

    @app.post("/api/jobs")
    async def start_job(request: Request):
        """Grade one fixture submission in a fresh Celesto sandbox (background thread)."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        fixture_id = (body or {}).get("fixture", "correct_a")
        try:
            from grader.audit import Audit
            from grader.config import Settings
            from grader.fixtures import FIXTURES
            from grader.hooks import SafetyPolicy
            from grader.ledger import StoreLedger
            from grader.pipeline import Env, run_job
            from grader.providers import make_provider
            if fixture_id not in FIXTURES:
                return JSONResponse({"error": f"unknown fixture {fixture_id}"}, status_code=400)
            cfg = Settings.from_env()
            provider = make_provider(cfg.provider, cfg)
        except Exception as e:  # SDK missing / not configured
            return JSONResponse({"error": f"sandbox provider unavailable: {e}"}, status_code=503)
        run_id = f"run-{uuid.uuid4().hex[:10]}"
        env = Env(provider, Audit(ROOT / cfg.log_dir / "commands.jsonl"), SafetyPolicy.from_settings(cfg),
                  StoreLedger(app.state.store), cfg)
        threading.Thread(target=run_job, args=(env, FIXTURES[fixture_id], run_id), daemon=True).start()
        return JSONResponse({"run_id": run_id, "status": "started"}, status_code=202)

    reports = ROOT / "reports"
    if reports.is_dir():
        app.mount("/reports", StaticFiles(directory=str(reports)), name="reports")
    return app


def __getattr__(name):  # lazy: `uvicorn app.main:app` builds it; tests import create_app only
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
