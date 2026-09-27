"""测试夹具。

必须在导入应用之前设置环境变量，让配置指向临时数据库，
否则测试会写到开发用的 data 目录里。
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_TMP_DIR = Path(tempfile.mkdtemp(prefix="iap-test-"))
_SERVER_DIR = Path(__file__).resolve().parent.parent

os.environ["IAP_DATABASE_URL"] = f"sqlite:///{(_TMP_DIR / 'test.db').as_posix()}"
os.environ["IAP_DATA_DIR"] = str(_TMP_DIR)
os.environ["IAP_AGENT_TOKEN"] = "test-token"
os.environ["IAP_READ_TOKEN"] = "test-read-token"
os.environ["IAP_RULES_FILE"] = str(_SERVER_DIR / "config" / "rules.json")
os.environ["IAP_OFFLINE_AFTER_MINUTES"] = "60"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def session():
    with SessionLocal() as db:
        yield db


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers():
    return {"X-Agent-Token": "test-token"}


@pytest.fixture
def read_headers():
    return {"X-Read-Token": "test-read-token"}


@pytest.fixture
def report_payload():
    def _build(
        report_id: str = "report-0001",
        fingerprint: str = "fp-device-1",
        hostname: str = "PC-TEST-001",
        collected_at: datetime | None = None,
        metrics: list[dict] | None = None,
        summary: str = "测试上报",
    ) -> dict:
        if metrics is None:
            metrics = [
                {"key": "cpu.load_percent", "value": 20.0, "unit": "%"},
                {"key": "memory.used_percent", "value": 50.0, "unit": "%"},
                {
                    "key": "disk.used_percent",
                    "value": 60.0,
                    "unit": "%",
                    "dimension": "C:",
                },
                {"key": "disk.free_gb", "value": 200.0, "unit": "GB", "dimension": "C:"},
            ]
        return {
            "report_id": report_id,
            "collected_at": (collected_at or datetime.now(timezone.utc)).isoformat(),
            "agent_version": "test",
            "summary": summary,
            "device": {
                "fingerprint": fingerprint,
                "hostname": hostname,
                "os_name": "Windows 11 Pro 23H2 (内部版本 22631)",
                "architecture": "AMD64",
                "cpu_model": "Test CPU @ 3.00GHz",
                "cpu_cores": 8,
                "cpu_threads": 16,
                "ram_total_gb": 16.0,
                "ssd_count": 1,
            },
            "metrics": metrics,
            "findings": [],
        }

    return _build
