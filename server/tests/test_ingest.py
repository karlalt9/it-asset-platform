"""上报入库流程测试：幂等、告警合并与自动恢复。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.config import settings
from app.ingest import ingest_report
from app.models import Alert, Device, Metric, Report
from app.schemas import ReportIn


def _ingest(session, payload: dict, seen_at: datetime | None = None):
    return ingest_report(
        session,
        ReportIn.model_validate(payload),
        settings.rules_file,
        seen_at=seen_at,
    )


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_first_report_creates_device_report_and_metrics(session, report_payload) -> None:
    result = _ingest(session, report_payload())
    session.commit()

    assert result.status == "stored"
    assert _count(session, Device) == 1
    assert _count(session, Report) == 1
    assert _count(session, Metric) == 4

    device = session.scalar(select(Device))
    assert device is not None
    assert device.hostname == "PC-TEST-001"
    assert device.status == "online"


def test_duplicate_report_id_is_ignored(session, report_payload) -> None:
    first = _ingest(session, report_payload())
    session.commit()
    second = _ingest(session, report_payload())
    session.commit()

    assert first.status == "stored"
    assert second.status == "duplicate"
    assert _count(session, Report) == 1
    assert _count(session, Metric) == 4


def test_second_report_reuses_device(session, report_payload) -> None:
    _ingest(session, report_payload(report_id="report-0001"))
    session.commit()
    _ingest(
        session,
        report_payload(report_id="report-0002", hostname="PC-TEST-001-RENAMED"),
    )
    session.commit()

    assert _count(session, Device) == 1
    assert _count(session, Report) == 2
    device = session.scalar(select(Device))
    assert device.hostname == "PC-TEST-001-RENAMED"


def test_rule_hit_creates_alerts(session, report_payload) -> None:
    metrics = [
        {"key": "disk.used_percent", "value": 93.0, "unit": "%", "dimension": "D:"},
        {"key": "disk.free_gb", "value": 8.0, "unit": "GB", "dimension": "D:"},
    ]
    result = _ingest(session, report_payload(metrics=metrics))
    session.commit()

    assert result.alerts_created == 2
    alerts = session.scalars(select(Alert)).all()
    assert {alert.rule_id for alert in alerts} == {"disk_used_high", "disk_free_low"}


def test_repeated_hits_merge_into_single_alert(session, report_payload) -> None:
    metrics = [
        {"key": "disk.used_percent", "value": 93.0, "unit": "%", "dimension": "D:"}
    ]

    _ingest(session, report_payload(report_id="report-0001", metrics=metrics))
    session.commit()
    second = _ingest(session, report_payload(report_id="report-0002", metrics=metrics))
    session.commit()

    assert second.alerts_created == 0
    assert second.alerts_updated == 1
    assert _count(session, Alert) == 1
    alert = session.scalar(select(Alert))
    assert alert.occurrences == 2


def test_alert_closes_automatically_after_recovery(session, report_payload) -> None:
    bad = [{"key": "disk.used_percent", "value": 93.0, "unit": "%", "dimension": "D:"}]
    good = [{"key": "disk.used_percent", "value": 42.0, "unit": "%", "dimension": "D:"}]

    _ingest(session, report_payload(report_id="report-0001", metrics=bad))
    session.commit()
    result = _ingest(session, report_payload(report_id="report-0002", metrics=good))
    session.commit()

    assert result.alerts_resolved == 1
    alert = session.scalar(select(Alert))
    assert alert.resolved_at is not None
    assert alert.resolved_by == "auto"


def test_missing_metric_does_not_close_alert(session, report_payload) -> None:
    bad = [{"key": "disk.used_percent", "value": 93.0, "unit": "%", "dimension": "D:"}]
    # 第二次采集没拿到磁盘指标（读取失败），不能判定为已恢复
    unrelated = [{"key": "cpu.load_percent", "value": 12.0, "unit": "%"}]

    _ingest(session, report_payload(report_id="report-0001", metrics=bad))
    session.commit()
    result = _ingest(session, report_payload(report_id="report-0002", metrics=unrelated))
    session.commit()

    assert result.alerts_resolved == 0
    alert = session.scalar(select(Alert))
    assert alert.resolved_at is None


def test_last_seen_uses_latest_observation(session, report_payload) -> None:
    """补发历史队列时，设备不应因为采集时间早而被判定为离线。"""
    old_time = datetime.now(timezone.utc) - timedelta(days=3)
    payload = report_payload(collected_at=old_time)
    _ingest(session, payload, seen_at=datetime.now(timezone.utc).replace(tzinfo=None))
    session.commit()

    device = session.scalar(select(Device))
    assert device.status == "online"


def test_deleting_device_cascades_to_reports_and_metrics(session, report_payload) -> None:
    """删除设备时，它的巡检记录和指标一起清理，不留孤儿数据。"""
    _ingest(session, report_payload())
    session.commit()
    assert _count(session, Report) == 1
    assert _count(session, Metric) == 4

    device = session.scalar(select(Device))
    session.delete(device)
    session.commit()

    assert _count(session, Device) == 0
    assert _count(session, Report) == 0
    assert _count(session, Metric) == 0
