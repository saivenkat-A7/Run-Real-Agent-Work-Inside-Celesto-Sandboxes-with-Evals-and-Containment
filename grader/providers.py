"""Sandbox providers.

* CelestoProvider  - the real thing (Celesto SDK; local microVM or Celesto Cloud).
* SimProvider      - an in-memory FAKE guest used for offline development / CI / reviewers without KVM.
                     It never executes anything (not on the host either). Anything it produces is labelled
                     provenance=simulated in the reports. It is NOT evidence about Celesto.
"""
from __future__ import annotations

import json
import random
import re
import threading
import time
from dataclasses import dataclass


@dataclass
class Res:
    exit_code: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class ProviderError(Exception):
    pass


# --------------------------------------------------------------------------- real Celesto
def _sdk_guard(policy):
    """Defence in depth: the same policy as a Celesto Callback, enforced inside the SDK's run()."""
    from celesto import Callback, CommandBlockedError
    from grader.hooks import CommandBlocked

    class Guard(Callback):
        def on_pre_run(self, ctx):
            try:
                policy.check(ctx.command)
            except CommandBlocked as e:
                raise CommandBlockedError(f"blocked: {e.reason}", vm_id=ctx.vm_id, command=ctx.command)
    return Guard()


class CelestoSandbox:
    supports_snapshots = False

    def __init__(self, provider, name, policy):
        self.p, self.name, self.policy = provider, name, policy
        self.cfg = provider.cfg
        self.vm = None
        self.vm_id = None
        self._cloud = self.cfg.provider == "cloud"
        self.supports_snapshots = not self._cloud

    def start(self):
        cfg = self.cfg
        if self._cloud:
            from celesto import Computer
            self.vm = Computer(provider="cloud", api_key=cfg.api_key or None)
            self.vm.__enter__()   # creates the computer; we own deletion in delete()
            self.vm_id = self.vm.id
        else:
            from celesto import Celesto
            kw = dict(backend=cfg.backend, comm_channel="vsock", callbacks=[_sdk_guard(self.policy)])
            if cfg.network_mode == "off":
                kw["internet_settings"] = {"mode": "off"}
            self.vm = Celesto(**kw)
            self.vm.start()
            self.vm_id = self.vm.vm_id

    def run(self, cmd, timeout=60) -> Res:
        r = self.vm.run(cmd, timeout=timeout)
        return Res(r.exit_code, r.stdout, r.stderr)

    def snapshot(self, snap_id):
        if not self.supports_snapshots:
            raise ProviderError("snapshots need the local runtime")
        self.vm.snapshot(snapshot_id=snap_id, resume_source=True)

    def restore(self, snap_id):
        from celesto import Celesto
        try:
            self.vm.stop()
        except Exception:
            pass
        try:
            self.vm.delete()
        except Exception:
            pass
        self.vm = Celesto.from_snapshot(snap_id, backend=self.cfg.backend, resume_vm=True, force=True)
        self.vm.add_callback(_sdk_guard(self.policy))
        self.vm_id = self.vm.vm_id

    def delete(self):
        vm, self.vm = self.vm, None
        if vm is None:
            return
        if self._cloud:
            try:
                vm.delete()
            finally:
                vm.__exit__(None, None, None)
        else:
            try:
                vm.stop()
            except Exception:
                pass
            vm.delete()


class CelestoProvider:
    simulated = False

    def __init__(self, cfg):
        self.cfg = cfg
        self._live: set[str] = set()
        self._lock = threading.Lock()

    def now(self):
        return time.monotonic()

    def create(self, name, policy):
        sb = CelestoSandbox(self, name, policy)
        with self._lock:
            self._live.add(name)          # registered BEFORE start: a half-created guest is still tracked
        try:
            sb.start()
        except BaseException:
            try:
                sb.delete()
            finally:
                with self._lock:
                    self._live.discard(name)
            raise
        return sb

    def released(self, name):
        with self._lock:
            self._live.discard(name)

    def live(self):
        with self._lock:
            return set(self._live)

    def cost(self, wall_s):
        return 0.0 if self.cfg.provider == "local" else round(wall_s / 3600 * self.cfg.hourly_price(), 6)


# --------------------------------------------------------------------------- simulator
_SCORE = {"correct": (100, 0), "wrong_logic": (60, 0), "infinite_loop": (40, 3), "crash": (20, 0)}
_WRITE = re.compile(r"printf %s '([A-Za-z0-9+/=]*)' \| base64 -d > (\S+)$")


class SimSandbox:
    def __init__(self, prov, name, policy):
        self.prov, self.name, self.policy = prov, name, policy
        self.fs: dict[str, str] = {}
        self.snaps: dict[str, dict] = {}
        self.supports_snapshots = True
        self.vm_id = "sim-" + name[4:]

    def start(self):
        pr = self.prov
        pr.tick(pr.rng.uniform(0.35, 0.65))                       # microVM boot-ish latency
        if pr.rng.random() < pr.boot_flake:
            pr.tick(2.0)
            raise ProviderError("simulated: guest did not become reachable (boot flake)")

    def run(self, cmd, timeout=60) -> Res:
        import base64
        pr = self.prov
        pr.tick(pr.rng.uniform(0.05, 0.25))
        m = _WRITE.search(cmd)
        if m:
            self.fs[m.group(2)] = base64.b64decode(m.group(1)).decode()
            return Res(0)
        if cmd.startswith("echo ready"):
            return Res(0, "ready\n")
        if "python3 --version" in cmd:
            return Res(0, "Python 3.12.3\n")
        if "py_compile /work/submission.py" in cmd:
            try:
                compile(self.fs.get("/work/submission.py", ""), "submission.py", "exec")   # parse only, never exec
                return Res(0)
            except SyntaxError as e:
                return Res(1, "", f"SyntaxError: {e.msg}")
        if "kill -9" in cmd:
            return Res(137, "", "Killed")
        if "run_tests.py" in cmd:
            if pr.rng.random() < pr.step_flake:
                return Res(137, "", "simulated: harness killed (OOM-ish flake)")
            sub = self.fs.get("/work/submission.py", "")
            beh = re.search(r"sim-behavior:(\w+)", sub)
            b = beh.group(1) if beh else self._guess(sub)
            score, to = _SCORE[b]
            pr.tick(3.0 * to + pr.rng.uniform(0.2, 0.6))
            self.fs["/work/result.json"] = json.dumps({"passed": score // 20, "total": 5, "timeouts": to,
                                                       "errors": 0, "score": score})
            return Res(0)
        if cmd.startswith("cat "):
            p = cmd.split()[1]
            return Res(0, self.fs[p]) if p in self.fs else Res(1, "", "No such file")
        if re.match(r"rm -rf /work/\*", cmd):
            self.fs = {k: v for k, v in self.fs.items() if not k.startswith("/work/")}
            return Res(0)
        if re.search(r"\b(curl|wget)\b|urllib|socket", cmd):
            if pr.network_mode == "off":
                return Res(6, "", "Could not resolve host / Network is unreachable")
            return Res(0, "simulated: request went out", "")
        if cmd.startswith("ls"):
            return Res(0, "\n".join(sorted(k.rsplit("/", 1)[-1] for k in self.fs)) + "\n")
        return Res(0)

    @staticmethod
    def _guess(sub):  # fallback when a fixture carries no marker
        return "infinite_loop" if "while True" in sub else "crash" if "raise" in sub else "correct"

    def snapshot(self, snap_id):
        self.prov.tick(0.4)
        self.snaps[snap_id] = dict(self.fs)

    def restore(self, snap_id):
        self.prov.tick(0.6)
        self.fs = dict(self.snaps[snap_id])

    def delete(self):
        self.prov.tick(0.1)


class SimProvider:
    simulated = True

    def __init__(self, cfg=None, seed=20261024, boot_flake=0.08, step_flake=0.10, network_mode="off"):
        self.cfg = cfg
        self.rng = random.Random(seed)
        self.boot_flake, self.step_flake, self.network_mode = boot_flake, step_flake, network_mode
        self._t = 0.0
        self._live: set[str] = set()
        self._lock = threading.Lock()
        self.max_live = 0

    # virtual clock: simulated latency without sleeping
    def tick(self, s):
        with self._lock:
            self._t += s

    def now(self):
        with self._lock:
            return self._t

    def create(self, name, policy):
        sb = SimSandbox(self, name, policy)
        with self._lock:
            self._live.add(name)
            self.max_live = max(self.max_live, len(self._live))
        try:
            sb.start()
        except BaseException:
            self.released(name)
            raise
        return sb

    def released(self, name):
        with self._lock:
            self._live.discard(name)

    def live(self):
        with self._lock:
            return set(self._live)

    def cost(self, wall_s):   # ESTIMATE at Micro cloud list price - nothing was billed
        return round(wall_s / 3600 * 0.015, 6)


def make_provider(kind, cfg):
    if kind == "sim":
        return SimProvider(cfg, network_mode=cfg.network_mode if cfg else "off")
    if kind in ("local", "cloud"):
        import celesto  # noqa: F401  (fail early with a clear error if the SDK is missing)
        cfg.provider = kind
        return CelestoProvider(cfg)
    raise ValueError(f"unknown provider {kind!r} (use local, cloud or sim)")
