"""CLI:  python -m grader.cli all --provider sim|local|cloud   (writes everything under reports/ and logs/)"""
from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from grader import reports as R
from grader.audit import Audit
from grader.config import Settings
from grader.hooks import SafetyPolicy
from grader.ledger import HttpLedger, NullLedger
from grader.pipeline import Env
from grader.providers import SimProvider, make_provider

ROOT = Path(__file__).resolve().parent.parent


def _sigterm(*_):
    raise KeyboardInterrupt()    # SIGTERM takes the same cleanup path as Ctrl-C


def main(argv=None):
    ap = argparse.ArgumentParser(prog="grader")
    ap.add_argument("cmd", choices=["all", "eval", "containment", "failure", "concurrency", "static"])
    ap.add_argument("--provider", default=None, help="sim | local | cloud (default: $CELESTO_PROVIDER)")
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--policy", default="rollback", choices=["resume", "rollback", "fresh"])
    a = ap.parse_args(argv)
    signal.signal(signal.SIGTERM, _sigterm)
    cfg = Settings.from_env()
    kind = a.provider or cfg.provider
    cfg.provider = kind
    prov = SimProvider(cfg, network_mode="on") if kind == "sim" else make_provider(kind, cfg)
    log = ROOT / cfg.log_dir / "commands.jsonl"
    if a.cmd == "all":
        log.parent.mkdir(exist_ok=True); log.write_text("")      # fresh evidence per full run
    ledger = HttpLedger(cfg.ledger_url) if cfg.ledger_url else NullLedger()
    env = Env(prov, Audit(log), SafetyPolicy.from_settings(cfg), ledger, cfg)
    names = []
    try:
        if a.cmd in ("all", "static"):
            R.write_static(ROOT)
        if a.cmd in ("all", "eval"):
            recs = R.run_eval(env, kind, ROOT, a.runs, a.policy)
            names += [n for r in recs for n in r.names_used]
            ok_success = not prov.live()
        if a.cmd in ("all", "failure"):
            rec, _ = R.run_failure_demo(env, kind, ROOT, a.policy)
            names += rec.names_used
            ok_failure = not prov.live()
        if a.cmd in ("all", "containment"):
            blocked, untouched, cname = R.run_containment(env, kind, ROOT, cfg)
            names.append(cname)
            print(f"containment: blocked={blocked} host_untouched={untouched}")
        if a.cmd in ("all", "concurrency"):
            names += [r.sandbox_name for r in R.run_concurrency(env, kind, ROOT, a.jobs)]
        if a.cmd == "all":
            ok_int, _ = R.interrupt_check(env)
            R.write_lifecycle(ROOT, names, ok_success, ok_failure, ok_int)
            R.update_readme(ROOT)
    finally:
        left = prov.live()
        if left:
            print(f"WARNING: sandboxes still live: {sorted(left)}", file=sys.stderr)
    print("done; live sandboxes:", len(prov.live()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
