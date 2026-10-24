"""Student submissions (fixtures) graded by the agent, plus the guest-side test harness.

Task given to students: `solve(n)` returns the n-th Fibonacci number.
Five test cases (20 points each). Hostile/buggy submissions must still be graded correctly
(= the grader survives them) and must never touch the host.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass

CASES = [(0, 0), (1, 1), (10, 55), (30, 832040), (50, 12586269025)]


@dataclass(frozen=True)
class Fixture:
    id: str
    behavior: str          # used ONLY by the simulator provider (real guests ignore it)
    code: str
    expected_score: int
    expected_verdict: str


_GOOD = '''# sim-behavior:correct
def solve(n):
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a
'''
_GOOD_B = '''# sim-behavior:correct
from functools import lru_cache

@lru_cache(None)
def solve(n):
    return n if n < 2 else solve(n - 1) + solve(n - 2)
'''
_WRONG = '''# sim-behavior:wrong_logic
def solve(n):
    a, b = 0, 1
    for _ in range(min(n, 20)):   # bug: caps the loop
        a, b = b, a + b
    return a
'''
_LOOP = '''# sim-behavior:infinite_loop
def solve(n):
    if n < 2:
        return n
    while True:      # hostile: never returns for n >= 2
        pass
'''
_CRASH = '''# sim-behavior:crash
import os

def solve(n):
    if n >= 1:
        open("/etc/shadow").read()   # hostile: snoops, then dies
        raise RuntimeError("boom")
    return 0
'''
_SYNTAX = '''# sim-behavior:syntax_error
def solve(n)
    return n
'''

FIXTURES: dict[str, Fixture] = {f.id: f for f in [
    Fixture("correct_a", "correct", _GOOD, 100, "pass"),
    Fixture("correct_b", "correct", _GOOD_B, 100, "pass"),
    Fixture("wrong_logic", "wrong_logic", _WRONG, 60, "partial"),
    Fixture("infinite_loop", "infinite_loop", _LOOP, 40, "partial"),
    Fixture("crash_snoop", "crash", _CRASH, 20, "partial"),
    Fixture("syntax_error", "syntax_error", _SYNTAX, 0, "compile_error"),
]}
EVAL_ORDER = ["correct_a", "correct_b", "wrong_logic", "infinite_loop", "crash_snoop", "syntax_error"]

HARNESS = '''import json, subprocess, sys
CASES = %r
passed = timeouts = errors = 0
for n, exp in CASES:
    code = "import submission; print(submission.solve(%%d))" %% n
    try:
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=3, cwd="/work")
        if r.returncode != 0:
            errors += 1
        elif r.stdout.strip() == str(exp):
            passed += 1
    except subprocess.TimeoutExpired:
        timeouts += 1
json.dump({"passed": passed, "total": len(CASES), "timeouts": timeouts, "errors": errors,
           "score": passed * 100 // len(CASES)}, open("/work/result.json", "w"))
''' % (CASES,)


def verdict_for(score: int) -> str:
    return "pass" if score == 100 else "partial"


def write_file_cmd(path: str, text: str) -> str:
    b64 = base64.b64encode(text.encode()).decode()
    return f"mkdir -p /work && printf %s '{b64}' | base64 -d > {path}"
