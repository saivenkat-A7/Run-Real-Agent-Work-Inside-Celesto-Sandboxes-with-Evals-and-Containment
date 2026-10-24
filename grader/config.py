from __future__ import annotations

import os
from dataclasses import dataclass, field

PRICE_PER_HOUR = {"micro": 0.015, "standard": 0.030, "large": 0.080}  # Celesto Cloud list prices


@dataclass
class Settings:
    provider: str = "local"            # local | cloud (| sim, CLI only)
    api_key: str = ""
    backend: str = "firecracker"
    size: str = "micro"
    network_mode: str = "on"           # on | off  (local firecracker only)
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    ledger_url: str = ""
    allowed_packages: tuple = ("python3",)
    allowed_hosts: tuple = ()
    reports_dir: str = "reports"
    log_dir: str = "logs"
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ.get
        csv = lambda k, d: tuple(x.strip() for x in e(k, d).split(",") if x.strip())
        return cls(
            provider=e("CELESTO_PROVIDER", "local"), api_key=e("CELESTO_API_KEY", ""),
            backend=e("CELESTO_BACKEND", "firecracker"), size=e("CELESTO_SIZE", "micro"),
            network_mode=e("CELESTO_NETWORK_MODE", "on"), llm_base_url=e("LLM_BASE_URL", ""),
            llm_api_key=e("LLM_API_KEY", ""), llm_model=e("LLM_MODEL", ""),
            ledger_url=e("LEDGER_API_URL", ""), allowed_packages=csv("ALLOWED_PACKAGES", "python3"),
            allowed_hosts=csv("ALLOWED_HOSTS", ""), reports_dir=e("REPORTS_DIR", "reports"),
            log_dir=e("LOG_DIR", "logs"))

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key and not self.llm_api_key.startswith("replace") and self.llm_base_url
                    and "example-llm-host" not in self.llm_base_url and self.llm_model
                    and not self.llm_model.startswith("replace"))

    def hourly_price(self) -> float:
        return PRICE_PER_HOUR.get(self.size, 0.015)
