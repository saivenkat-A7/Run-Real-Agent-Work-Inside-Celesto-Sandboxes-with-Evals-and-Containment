"""Validates every graded artifact exactly as the task spec describes."""
import json
import math
import re
import statistics
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = re.compile(r"^sbx-[a-z0-9]{8,}$")
load = lambda p: json.loads((ROOT / p).read_text())


def test_env_example_and_no_env():
    text = (ROOT / ".env.example").read_text()
    keys = {l.split("=")[0] for l in text.splitlines() if "=" in l and not l.startswith("#")}
    assert {"CELESTO_PROVIDER", "CELESTO_API_KEY", "LLM_API_KEY", "LLM_MODEL", "DATABASE_URL", "API_PORT"} <= keys
    assert not (ROOT / ".env").exists()
    assert "sk-" not in text


def test_compose():
    import yaml
    c = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    assert {"api", "ledger"} <= set(c["services"])
    for s in ("api", "ledger"):
        hc = c["services"][s]["healthcheck"]
        assert all(k in hc for k in ("interval", "timeout", "retries", "start_period"))
    assert "pg_isready" in str(c["services"]["ledger"]["healthcheck"]["test"])
    assert "http://localhost:8080/health" in str(c["services"]["api"]["healthcheck"]["test"])
    assert any("./seeds" in v for v in c["services"]["ledger"]["volumes"])
    assert c["services"]["api"]["depends_on"]["ledger"]["condition"] == "service_healthy"
    assert "firecracker" not in c["services"]


def test_problem():
    p = load("reports/problem.json")
    assert len(p["who"]) >= 40 and len(p["agent_work"]) >= 40 and len(p["proof_output"]) >= 20
    assert p["idea_source"] in ("idea_bank", "original")


def test_commands_log():
    lines = [json.loads(l) for l in (ROOT / "logs/commands.jsonl").read_text().splitlines() if l.strip()]
    assert lines
    for l in lines:
        datetime.fromisoformat(l["ts"])
        assert NAME.match(l["sandbox_name"]) and l["command"].strip()
        assert l["decision"] in ("allow", "block")
        assert l["execution_target"] == "celesto_sandbox"
    assert any(l["decision"] == "block" for l in lines)   # blocked attempts are still lines


def test_capabilities():
    caps = load("reports/capabilities.json")["capabilities"]
    ok = {"persistence", "snapshots", "celestofs", "browser", "published_ports", "network_policy",
          "safety_hooks", "host_mounts", "coding_agent_preset", "agentor_durable"}
    ids = [c["id"] for c in caps]
    assert len(caps) >= 2 and len(set(ids)) == len(ids) and set(ids) <= ok
    for c in caps:
        assert len(c["why"]) >= 80 and (ROOT / c["evidence_path"]).exists()


def test_reliability():
    r = load("reports/reliability.json")
    runs = r["runs"]
    assert r["run_count"] == len(runs) >= 20
    names = [x["sandbox_name"] for x in runs]
    assert len(set(names)) == len(names) and all(NAME.match(n) for n in names)
    for x in runs:
        assert x["fresh"] is True and isinstance(x["success"], bool)
        assert all(x[k] >= 0 for k in ("wall_clock_s", "boot_to_ready_s", "cost_usd"))
    n = len(runs)
    assert abs(r["success_rate"] - sum(x["success"] for x in runs) / n) <= 0.001
    w = sorted(x["wall_clock_s"] for x in runs)
    assert abs(r["median_wall_clock_s"] - statistics.median(w)) <= 0.001
    assert abs(r["p90_wall_clock_s"] - w[math.ceil(0.9 * n) - 1]) <= 0.001
    assert abs(r["median_boot_to_ready_s"] - statistics.median(sorted(x["boot_to_ready_s"] for x in runs))) <= 0.001
    assert abs(r["total_cost_usd"] - sum(x["cost_usd"] for x in runs)) <= 0.01
    assert r["postmortem_path"] == "reports/postmortem.md"
    assert len((ROOT / "reports/postmortem.md").read_text()) >= 200


def test_lifecycle():
    lc = load("reports/lifecycle.json")
    assert lc["cleanup_on_success"] is lc["cleanup_on_failure"] is lc["cleanup_on_interrupt"] is True
    names = lc["sandbox_names"]
    assert names and len(set(names)) == len(names) and all(NAME.match(n) for n in names)
    log = (ROOT / "logs/commands.jsonl").read_text() + (ROOT / "reports/reliability.json").read_text()
    assert all(n in log for n in names)


def test_containment():
    c = load("reports/containment.json")
    assert c["attack"] in ("prompt_injection_exfil", "destructive_command", "suspicious_package")
    assert c["blocked"] is True and c["host_untouched"] is True
    assert c["evidence_paths"] and all((ROOT / p).exists() for p in c["evidence_paths"])


def test_failure_policy():
    f = load("reports/failure_policy.json")
    assert f["failed_step"] == 7 and f["total_steps"] == 10
    assert f["policy"] in ("resume", "rollback", "fresh") and len(f["rationale"]) >= 200
    assert f["trace_path"] == "reports/failure_trace.jsonl"
    tr = [json.loads(l) for l in (ROOT / f["trace_path"]).read_text().splitlines() if l.strip()]
    assert any(t.get("event") == "policy_applied" and t.get("policy") == f["policy"] for t in tr)


def test_concurrency():
    c = load("reports/concurrency.json")
    names = [j["sandbox_name"] for j in c["jobs"]]
    assert len(names) >= 5 and len(set(names)) == len(names) and all(NAME.match(n) for n in names)
    assert all(j["started_at"] for j in c["jobs"]) and len(c["breakage_notes"]) >= 40


def test_readme_phrases():
    t = (ROOT / "README.md").read_text()
    for p in ("Problem statement", "How I used Celesto", "Eval report", "Containment test",
              "State and failure design", "Setup"):
        assert p in t
