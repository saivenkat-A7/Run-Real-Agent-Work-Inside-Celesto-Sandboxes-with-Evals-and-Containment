"""Safety hook: code that runs BEFORE the guest sees a command and can veto it.

Unlike a 'please be careful' sentence in a prompt, this cannot be talked out of its decision.
It is deliberately a deny-list + allow-list hybrid: the dangerous *classes* are denied, package
installs and network egress are allow-listed (default: nothing but python3, no hosts).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


class CommandBlocked(Exception):
    def __init__(self, command: str, reason: str):
        super().__init__(f"blocked: {reason}")
        self.command, self.reason = command, reason


_RULES = [
    ("destructive_rm_root", re.compile(r"\brm\s+(-\S+\s+)*(--no-preserve-root|/|/\*|~|\$HOME|/home|/etc|/usr|/bin)(\s|$)")),
    ("fork_bomb", re.compile(r":\s*\(\s*\)\s*\{")),
    ("disk_wipe", re.compile(r"\b(mkfs\S*|dd\s+[^|;]*of=/dev/|shred\s+/dev/|wipefs)\b")),
    ("secret_exposure", re.compile(r"\b(printenv|env)\b|/proc/\S*/environ|\.env\b|\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD)\w*\}?")),
    ("pipe_to_shell", re.compile(r"\b(curl|wget)\b[^|]*\|\s*(sh|bash)\b|base64\s+-d\s*\|\s*(sh|bash)\b")),
]
_NET = re.compile(r"\b(curl|wget|nc|ncat|netcat|ssh|scp|ftp|telnet)\b")
_PKG = re.compile(r"\b(pip3?|npm|apk|apt(-get)?|yarn|gem)\s+(add|install)\b(.*)")


@dataclass
class SafetyPolicy:
    allowed_packages: tuple = ("python3",)
    allowed_hosts: tuple = ()

    @classmethod
    def from_settings(cls, s) -> "SafetyPolicy":
        return cls(tuple(s.allowed_packages), tuple(s.allowed_hosts))

    def check(self, command: str) -> None:
        """Raise CommandBlocked or return None (= allow)."""
        if not command or not command.strip():
            raise CommandBlocked(command, "empty_command")
        for name, rx in _RULES:
            if rx.search(command):
                raise CommandBlocked(command, name)
        m = _PKG.search(command)
        if m:
            pkgs = [t for t in re.split(r"[\s;&|]+", m.group(4)) if t and not t.startswith("-")]
            bad = [p for p in pkgs if p not in self.allowed_packages]
            if bad:  # e.g. the typosquat `pip install reqeusts`
                raise CommandBlocked(command, f"package_not_allowlisted:{','.join(bad)}")
        if _NET.search(command):
            if not any(h in command for h in self.allowed_hosts):
                raise CommandBlocked(command, "network_egress_not_allowlisted")
