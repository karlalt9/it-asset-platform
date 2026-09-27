"""接口层测试：上报鉴权、读取鉴权、幂等与数据接口。"""

from __future__ import annotations

from app.config import settings


def test_health(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ---------- 上报接口：只有 Agent 令牌能调用 ----------


def test_report_requires_token(client, report_payload) -> None:
    assert client.post("/api/v1/agents/report", json=report_payload()).status_code == 401


def test_report_with_wrong_token_is_rejected(client, report_payload) -> None:
    response = client.post(
        "/api/v1/agents/report",
        json=report_payload(),
        headers={"X-Agent-Token": "wrong-token"},
    )
    assert response.status_code == 401


def test_read_token_cannot_report(client, report_payload, read_headers) -> None:
    """读取令牌不能拿来伪造上报，两个令牌职责分开。"""
    response = client.post(
        "/api/v1/agents/report", json=report_payload(), headers=read_headers
    )
    assert response.status_code == 401


# ---------- 读取接口：只有读取令牌能调用 ----------


def test_read_endpoints_require_token(client) -> None:
    for path in ("/api/v1/devices", "/api/v1/alerts", "/api/v1/stats/overview"):
        assert client.get(path).status_code == 401, path


def test_read_with_wrong_token_is_rejected(client) -> None:
    assert client.get("/api/v1/devices", headers={"X-Read-Token": "wrong"}).status_code == 401


def test_agent_token_cannot_read(client, report_payload, auth_headers) -> None:
    """装在别人电脑上的 Agent 令牌读不到任何数据。"""
    client.post("/api/v1/agents/report", json=report_payload(), headers=auth_headers)

    assert client.get("/api/v1/devices", headers=auth_headers).status_code == 401
    assert client.get("/api/v1/alerts", headers=auth_headers).status_code == 401
    assert client.get("/api/v1/stats/overview", headers=auth_headers).status_code == 401


def test_csv_export_requires_token(client) -> None:
    assert client.get("/api/v1/devices/export/csv").status_code == 401


# ---------- 功能测试 ----------


def test_report_accepted_and_idempotent(
    client, report_payload, auth_headers, read_headers
) -> None:
    first = client.post(
        "/api/v1/agents/report", json=report_payload(), headers=auth_headers
    )
    assert first.status_code == 200
    assert first.json()["status"] == "stored"
    assert first.json()["device_id"] > 0

    second = client.post(
        "/api/v1/agents/report", json=report_payload(), headers=auth_headers
    )
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"

    listing = client.get("/api/v1/devices", headers=read_headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 1


def test_device_detail_and_patch(client, report_payload, auth_headers, read_headers) -> None:
    device_id = client.post(
        "/api/v1/agents/report", json=report_payload(), headers=auth_headers
    ).json()["device_id"]

    detail = client.get(f"/api/v1/devices/{device_id}", headers=read_headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["device"]["hostname"] == "PC-TEST-001"
    assert body["recent_reports"][0]["summary"] == "测试上报"

    patched = client.patch(
        f"/api/v1/devices/{device_id}",
        json={"owner": "张伟", "department": "品质部", "location": "质检中心"},
        headers=read_headers,
    )
    assert patched.status_code == 200
    assert patched.json()["owner"] == "张伟"
    assert patched.json()["department"] == "品质部"


def test_missing_device_returns_404(client, read_headers) -> None:
    assert client.get("/api/v1/devices/9999", headers=read_headers).status_code == 404


def test_delete_device_removes_related_data(
    client, report_payload, auth_headers, read_headers
) -> None:
    """删除设备会连带清理巡检记录、指标和告警。"""
    metrics = [
        {"key": "disk.used_percent", "value": 95.0, "unit": "%", "dimension": "D:"}
    ]
    device_id = client.post(
        "/api/v1/agents/report",
        json=report_payload(metrics=metrics),
        headers=auth_headers,
    ).json()["device_id"]

    assert client.get("/api/v1/devices", headers=read_headers).json()["total"] == 1
    assert client.get("/api/v1/alerts", headers=read_headers).json()["total"] == 1

    deleted = client.delete(f"/api/v1/devices/{device_id}", headers=read_headers)
    assert deleted.status_code == 204

    assert client.get(f"/api/v1/devices/{device_id}", headers=read_headers).status_code == 404
    assert client.get("/api/v1/devices", headers=read_headers).json()["total"] == 0
    assert client.get("/api/v1/alerts", headers=read_headers).json()["total"] == 0
    assert client.get("/api/v1/stats/overview", headers=read_headers).json()["device_total"] == 0


def test_delete_device_requires_read_token(client, report_payload, auth_headers) -> None:
    device_id = client.post(
        "/api/v1/agents/report", json=report_payload(), headers=auth_headers
    ).json()["device_id"]

    assert client.delete(f"/api/v1/devices/{device_id}").status_code == 401
    assert (
        client.delete(
            f"/api/v1/devices/{device_id}", headers={"X-Agent-Token": "test-token"}
        ).status_code
        == 401
    )


def test_delete_missing_device_returns_404(client, read_headers) -> None:
    assert client.delete("/api/v1/devices/9999", headers=read_headers).status_code == 404


def test_alert_list_and_resolve(client, report_payload, auth_headers, read_headers) -> None:
    metrics = [
        {"key": "disk.used_percent", "value": 95.0, "unit": "%", "dimension": "D:"}
    ]
    client.post(
        "/api/v1/agents/report",
        json=report_payload(metrics=metrics),
        headers=auth_headers,
    )

    listing = client.get("/api/v1/alerts", headers=read_headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    alert = listing.json()["items"][0]
    assert alert["hostname"] == "PC-TEST-001"
    assert alert["level"] == "warning"

    resolved = client.patch(
        f"/api/v1/alerts/{alert['id']}/resolve",
        json={"note": "已清理 D 盘临时文件"},
        headers=read_headers,
    )
    assert resolved.status_code == 200
    assert resolved.json()["resolved_by"] == "manual"
    assert resolved.json()["note"] == "已清理 D 盘临时文件"

    assert client.get("/api/v1/alerts", headers=read_headers).json()["total"] == 0
    resolved_list = client.get("/api/v1/alerts?state=resolved", headers=read_headers)
    assert resolved_list.json()["total"] == 1


def test_overview_counts(client, report_payload, auth_headers, read_headers) -> None:
    client.post(
        "/api/v1/agents/report", json=report_payload(), headers=auth_headers
    )

    response = client.get("/api/v1/stats/overview", headers=read_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["device_total"] == 1
    assert body["device_online"] == 1
    assert body["device_offline"] == 0
    assert body["rule_count"] >= 8
    assert len(body["alert_trend"]) == 7


def test_metrics_series(client, report_payload, auth_headers, read_headers) -> None:
    device_id = client.post(
        "/api/v1/agents/report", json=report_payload(), headers=auth_headers
    ).json()["device_id"]

    response = client.get(
        f"/api/v1/devices/{device_id}/metrics?key=cpu.load_percent",
        headers=read_headers,
    )
    assert response.status_code == 200
    series = response.json()["series"]
    assert len(series) == 1
    assert series[0]["key"] == "cpu.load_percent"
    assert len(series[0]["points"]) == 1


def test_csv_export_with_token(client, report_payload, auth_headers, read_headers) -> None:
    client.post(
        "/api/v1/agents/report", json=report_payload(), headers=auth_headers
    )

    response = client.get("/api/v1/devices/export/csv", headers=read_headers)
    assert response.status_code == 200
    assert response.content.startswith("\ufeff".encode("utf-8"))
    text = response.content.decode("utf-8-sig")
    assert "主机名" in text
    assert "PC-TEST-001" in text


def test_default_rules_file_exists() -> None:
    assert settings.rules_file.is_file()
