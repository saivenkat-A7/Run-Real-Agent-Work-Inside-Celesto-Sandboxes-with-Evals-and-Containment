"""The agent: an LLM in a loop whose only tool is `run_shell`, executed inside the Celesto guest.

Every command goes through the guarded sandbox (safety hook -> audit -> guest), so a prompt-injected
or hallucinated command is a log line, not an incident. When no LLM is configured the loop degrades to
a deterministic scripted inspector so evals are reproducible and free.
"""
from __future__ import annotations

import json
import urllib.request

from grader.hooks import CommandBlocked

SYSTEM = (
    "You review a student's autograded Python submission inside a sandbox. Tool: run_shell. "
    'Reply with ONLY JSON: {"tool":"run_shell","command":"..."} to inspect, or {"feedback":"<2 sentences>"} '
    "to finish. Files: /work/submission.py, /work/result.json. Never run network or install commands."
)


def _scripted(guard, fx, result) -> str:
    listing = guard.run("ls /work").stdout.split()
    return (f"Score {result.get('score')}/100: {result.get('passed')}/{result.get('total')} cases passed, "
            f"{result.get('timeouts', 0)} timed out, {result.get('errors', 0)} errored. "
            f"Files seen in guest: {', '.join(listing)}.")


def _chat(cfg, messages) -> str:
    req = urllib.request.Request(
        cfg.llm_base_url.rstrip("/") + "/chat/completions",
        json.dumps({"model": cfg.llm_model, "messages": messages, "temperature": 0}).encode(),
        {"Content-Type": "application/json", "Authorization": f"Bearer {cfg.llm_api_key}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def review(guard, fx, result, cfg, emit=lambda **k: None, max_turns: int = 4) -> str:
    if cfg is None or not cfg.llm_enabled:
        return _scripted(guard, fx, result)
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Grader result: {json.dumps(result)}. Inspect then give feedback."}]
    try:
        for _ in range(max_turns):
            reply = _chat(cfg, msgs)
            msgs.append({"role": "assistant", "content": reply})
            try:
                obj = json.loads(reply)
            except ValueError:
                return _scripted(guard, fx, result)
            if "feedback" in obj:
                return str(obj["feedback"])[:500]
            cmd = obj.get("command", "")
            try:
                r = guard.run(cmd)
                obs = f"exit={r.exit_code}\n{r.stdout[:800]}\n{r.stderr[:300]}"
            except CommandBlocked as e:       # the model misbehaved; the hook said no
                obs = f"BLOCKED by safety hook: {e.reason}"
                emit(event="agent_command_blocked", command=cmd, reason=e.reason)
            msgs.append({"role": "user", "content": obs})
    except Exception as e:                    # LLM outage must not fail grading
        emit(event="llm_error", error=str(e)[:200])
    return _scripted(guard, fx, result)
