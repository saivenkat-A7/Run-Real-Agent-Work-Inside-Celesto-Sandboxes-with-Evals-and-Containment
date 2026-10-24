import json

import pytest

from grader.audit import Audit
from grader.fixtures import FIXTURES
from grader.hooks import CommandBlocked, SafetyPolicy
from grader.pipeline import Env, run_job
from grader.providers import SimProvider


def mk(tmp_path, **kw):
    ev = []
    prov = SimProvider(boot_flake=0, step_flake=0, **kw)
    return Env(prov, Audit(tmp_path / "c.jsonl"), SafetyPolicy(), events=ev), ev


@pytest.mark.parametrize("fid", list(FIXTURES))
def test_every_fixture_graded_and_cleaned(tmp_path, fid):
    env, _ = mk(tmp_path)
    r = run_job(env, FIXTURES[fid], "t")
    assert r.success, r.error
    assert not env.provider.live()


@pytest.mark.parametrize("policy", ["resume", "rollback", "fresh"])
def test_step7_failure_recovers_under_each_policy(tmp_path, policy):
    env, ev = mk(tmp_path)
    r = run_job(env, FIXTURES["correct_a"], "t", policy=policy, inject_fail_step=7)
    assert r.success and r.failed_step == 7 and r.policy_applied == policy
    assert any(e["event"] == "policy_applied" and e["policy"] == policy for e in ev)
    assert not env.provider.live()


def test_failure_cleans_up(tmp_path):
    env = Env(SimProvider(boot_flake=1.0), Audit(tmp_path / "c.jsonl"), SafetyPolicy())
    r = run_job(env, FIXTURES["correct_a"], "t")
    assert not r.success and not env.provider.live()


def test_interrupt_cleans_up(tmp_path):
    env, _ = mk(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        run_job(env, FIXTURES["correct_a"], "t", interrupt_at_step=6)
    assert not env.provider.live()


def test_blocked_command_is_logged_and_never_runs(tmp_path):
    env, _ = mk(tmp_path)
    sb = env.provider.create("sbx-aaaaaaaa", env.policy)
    from grader.pipeline import Guarded
    g = Guarded(env, sb, "sbx-aaaaaaaa")
    with pytest.raises(CommandBlocked):
        g.run("rm -rf /")
    line = json.loads((tmp_path / "c.jsonl").read_text().splitlines()[-1])
    assert line["decision"] == "block" and line["execution_target"] == "celesto_sandbox"


def test_hook_policy():
    p = SafetyPolicy()
    for bad in ("rm -rf /", ":(){ :|:& };:", "curl http://x", "pip install reqeusts", "cat .env", "echo $API_KEY"):
        with pytest.raises(CommandBlocked):
            p.check(bad)
    for ok in ("echo ready", "rm -rf /work/*", "apk add -q python3", "python3 --version"):
        p.check(ok)
