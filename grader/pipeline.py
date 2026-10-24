"""The 10-step grading job + sandbox lifecycle (Created -> Ready -> Running -> ... -> Deleted).

Steps: 1 boot+ready probe | 2 write submission | 3 write harness | 4 toolchain check |
       5 checkpoint (snapshot) | 6 compile check | 7 run tests (the risky step) | 8 read result |
       9 agent review + write grade | 10 read proof output.
Lifecycle hygiene lives in `run_job`'s try/finally (see `finally:` block) - success, failure and Ctrl-C
all end at Deleted.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from grader import agent
from grader.audit import Audit
from grader.fixtures import HARNESS, Fixture, verdict_for, write_file_cmd
from grader.hooks import CommandBlocked, SafetyPolicy
from grader.ledger import NullLedger
from grader.naming import new_sandbox_name

PROBLEM_ID = "hostile-submission-autograder"
FAULT_CMD = "sh -c 'kill -9 $$'"           # the designed crash: the harness process dies mid-step 7
TEST_CMD = "cd /work && timeout 30 python3 run_tests.py"


class StepFailure(Exception):
    def __init__(self, step, reason):
        super().__init__(f"step {step}: {reason}")
        self.step, self.reason = step, reason


@dataclass
class Env:
    provider: object
    audit: Audit
    policy: SafetyPolicy
    ledger: object = field(default_factory=NullLedger)
    cfg: object = None
    events: list | None = None             # optional trace sink (list of dicts)

    def emit(self, **kw):
        if self.events is not None:
            from datetime import datetime, timezone
            self.events.append({"ts": datetime.now(timezone.utc).isoformat(), **kw})


class Guarded:
    """Policy check -> audit line -> guest. A blocked command never reaches the guest but is still logged."""
    def __init__(self, env: Env, sb, name):
        self.env, self.sb, self.name = env, sb, name

    def run(self, cmd, timeout=60):
        try:
            self.env.policy.check(cmd)
        except CommandBlocked as e:
            self.env.audit.record(self.name, cmd, "block", e.reason)
            raise
        self.env.audit.record(self.name, cmd, "allow")
        return self.sb.run(cmd, timeout)


@dataclass
class RunRecord:
    run_id: str
    sandbox_name: str
    fresh: bool = True
    success: bool = False
    wall_clock_s: float = 0.0
    boot_to_ready_s: float = 0.0
    cost_usd: float = 0.0
    fixture: str = ""
    failed_step: int | None = None
    policy_applied: str | None = None
    error: str | None = None
    names_used: list = field(default_factory=list)

    def public(self):
        return {"sandbox_name": self.sandbox_name, "fresh": self.fresh, "success": self.success,
                "wall_clock_s": round(self.wall_clock_s, 3), "boot_to_ready_s": round(self.boot_to_ready_s, 3),
                "cost_usd": round(self.cost_usd, 6), "fixture": self.fixture, "failed_step": self.failed_step,
                "policy_applied": self.policy_applied, "error": self.error}


def run_job(env: Env, fx: Fixture, run_id: str, policy: str = "rollback", inject_fail_step: int | None = None,
            interrupt_at_step: int | None = None, problem_id: str = PROBLEM_ID) -> RunRecord:
    prov, led = env.provider, env.ledger
    name = new_sandbox_name()
    rec = RunRecord(run_id, name, fixture=fx.id, names_used=[name])
    t0 = prov.now()
    live: dict[str, object] = {}          # name -> raw sandbox, everything we must delete
    state = {"snap": None, "attempt7": 0, "compile_ok": True, "result": {}, "grade": {}}
    cur = {"name": name, "g": None}

    def trace(**kw):
        env.emit(run_id=run_id, sandbox_name=cur["name"], **kw)

    def boot(nm):
        t_c = prov.now()
        try:
            sb = prov.create(nm, env.policy)
        except BaseException:
            if not rec.boot_to_ready_s:        # never became Ready: record time burned until the failure
                rec.boot_to_ready_s = prov.now() - t_c
            raise
        live[nm] = sb
        led.update(run_id, nm, problem_id, "created"); trace(event="state", state="Created")
        g = Guarded(env, sb, nm)
        for attempt in range(5):           # boot probe: Ready = probe passed
            r = g.run("echo ready")
            if r.ok and "ready" in r.stdout:
                break
            if attempt == 4:
                raise StepFailure(1, "boot probe never passed")
        led.update(run_id, nm, problem_id, "ready"); trace(event="state", state="Ready")
        cur["g"], cur["name"] = g, nm
        return prov.now() - t_c

    def step(n, label):
        if interrupt_at_step == n:
            raise KeyboardInterrupt()      # simulates Ctrl-C arriving mid-run
        trace(event="step_started", step=n, label=label)

    def prepare(g):
        step(2, "write submission"); _must(g.run(write_file_cmd("/work/submission.py", fx.code)), 2)
        step(3, "write harness"); _must(g.run(write_file_cmd("/work/run_tests.py", HARNESS)), 3)
        step(4, "toolchain check"); _must(g.run("python3 --version || apk add -q python3"), 4)
        step(5, "checkpoint")
        if cur_sb().supports_snapshots:
            snap = f"before-step7-{cur['name']}"
            env.audit.record(cur["name"], f"[celesto.snapshot] {snap}", "allow")
            cur_sb().snapshot(snap); state["snap"] = snap
            trace(event="snapshot_taken", snapshot=snap)

    def cur_sb():
        return live[cur["name"]]

    def compile_and_test(g):
        step(6, "compile check")
        c = g.run("python3 -m py_compile /work/submission.py")
        state["compile_ok"] = c.ok
        if not c.ok:
            trace(event="compile_error"); return
        step(7, "run tests")
        cmd = FAULT_CMD if (inject_fail_step == 7 and state["attempt7"] == 0) else TEST_CMD
        state["attempt7"] += 1
        r = g.run(cmd, timeout=90)
        if not r.ok:
            raise StepFailure(7, f"harness exited {r.exit_code}: {r.stderr.strip()[:120]}")
        step(8, "read result")
        out = g.run("cat /work/result.json")
        try:
            state["result"] = json.loads(out.stdout)
        except ValueError:
            raise StepFailure(8, "result.json unreadable")

    try:
        try:
            rec.boot_to_ready_s = boot(name)
            g = cur["g"]
            led.update(run_id, name, problem_id, "running"); trace(event="state", state="Running")
            prepare(g)
            try:
                compile_and_test(g)
            except StepFailure as f:
                if f.step != 7:
                    raise
                rec.failed_step, rec.policy_applied = 7, policy
                led.update(run_id, cur["name"], problem_id, "failed")
                trace(event="step_failed", step=7, reason=f.reason, state="MidTaskFailure")
                applied = policy
                if policy == "rollback" and not cur_sb().supports_snapshots:
                    applied = "fresh"; rec.policy_applied = "fresh"
                    trace(event="policy_degraded", requested="rollback", to="fresh",
                          why="provider has no snapshots")
                trace(event="policy_applied", policy=applied, step=7)
                if applied == "resume":
                    trace(event="resumed", note="same disk, same guest")
                elif applied == "rollback":
                    cur_sb().restore(state["snap"])
                    trace(event="snapshot_restored", snapshot=state["snap"], state="RolledBack")
                else:  # fresh: new unique name, brand new disk; the old guest is deleted
                    old = cur["name"]
                    _delete(env, live, old, run_id, problem_id, led)
                    nn = new_sandbox_name(); rec.names_used.append(nn)
                    boot(nn)
                    trace(event="fresh_started", previous=old, state="FreshStart")
                    g = cur["g"]
                    prepare(g)
                g = cur["g"]
                led.update(run_id, cur["name"], problem_id, "running")
                compile_and_test(g)         # ONE retry; a second failure fails the job
                trace(event="step_completed", step=7, after_policy=applied)
            g = cur["g"]
            _finish(env, g, fx, state, cfg=env.cfg, trace=trace, step=step)
            rec.success = True
        except StepFailure as f:
            rec.failed_step, rec.error = f.step, f.reason
        except CommandBlocked as b:
            rec.error = f"blocked:{b.reason}"
        except Exception as e:
            rec.error = f"{type(e).__name__}: {e}"[:200]
        led.update(run_id, cur["name"], problem_id, "succeeded" if rec.success else "failed")
        trace(event="state", state="Succeeded" if rec.success else "Failed")
    finally:
        # ---- lifecycle hygiene: runs on success, failure AND KeyboardInterrupt/SIGTERM ----
        for nm in list(live):
            _delete(env, live, nm, run_id, problem_id, led)
        trace(event="cleanup_done", state="Deleted", remaining=sorted(prov.live()))
    rec.sandbox_name = name
    rec.wall_clock_s = prov.now() - t0
    rec.cost_usd = prov.cost(rec.wall_clock_s)
    return rec


def _must(r, step):
    if not r.ok:
        raise StepFailure(step, f"exit {r.exit_code}: {r.stderr.strip()[:120]}")


def _delete(env, live, nm, run_id, problem_id, led):
    sb = live.pop(nm, None)
    if sb is None:
        return
    try:
        sb.delete()
    except Exception as e:
        env.emit(run_id=run_id, sandbox_name=nm, event="cleanup_error", error=str(e)[:200])
    finally:
        env.provider.released(nm)
        led.update(run_id, nm, problem_id, "deleted")


def _finish(env, g, fx, state, cfg, trace, step):
    if state["compile_ok"]:
        res = state["result"]
        score, verdict = int(res.get("score", 0)), verdict_for(int(res.get("score", 0)))
    else:
        res, score, verdict = {"passed": 0, "total": 5, "timeouts": 0, "errors": 1}, 0, "compile_error"
    step(9, "agent review + grade")
    fb = agent.review(g, fx, {**res, "score": score}, cfg, emit=lambda **k: trace(**k))
    grade = {"submission": fx.id, "score": score, "verdict": verdict, "passed": res.get("passed", 0),
             "timeouts": res.get("timeouts", 0), "feedback": fb}
    _must(g.run(write_file_cmd("/work/grade.json", json.dumps(grade))), 9)
    step(10, "read proof output")
    out = g.run("cat /work/grade.json")
    _must(out, 10)
    got = json.loads(out.stdout)                       # proof output exists and is parseable
    if got["score"] != fx.expected_score or got["verdict"] != fx.expected_verdict:
        raise StepFailure(10, f"wrong grade {got['score']}/{got['verdict']}, expected "
                              f"{fx.expected_score}/{fx.expected_verdict}")
    trace(event="step_completed", step=10)
