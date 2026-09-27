"""运行配置。

所有配置项都可以通过环境变量覆盖，方便在容器里部署。
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


class Settings:
    def __init__(self) -> None:
        self.app_name = "IT 资产巡检平台"
        self.version = "0.1.0"
        self.data_dir = Path(_env("IAP_DATA_DIR", str(BASE_DIR / "data")))
        self.database_url = _env(
            "IAP_DATABASE_URL",
            f"sqlite:///{(self.data_dir / 'iap.db').as_posix()}",
        )
        self.rules_file = Path(_env("IAP_RULES_FILE", str(BASE_DIR / "config" / "rules.json")))
        self.agent_token = _env("IAP_AGENT_TOKEN", "dev-agent-token")
        self.read_token = _env("IAP_READ_TOKEN", "dev-read-token")
        self.offline_after_minutes = int(_env("IAP_OFFLINE_AFTER_MINUTES", "1440"))
        self.cors_origins = [
            item.strip()
            for item in _env(
                "IAP_CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080",
            ).split(",")
            if item.strip()
        ]


settings = Settings()
