"""上报数据的入库流程。

单独放在这里而不是写在路由函数里，是为了让单元测试可以直接调用，
不必绕过 HTTP 层。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Alert, Device, Metric, Report, utcnow
from .rules import MetricPoint, evaluate, load_rules_cached
from .schemas import ReportIn


@dataclass
class IngestResult:
    status: str
    device_id: int
    report_id: str
    alerts_created: int = 0
    alerts_updated: int = 0
    alerts_resolved: int = 0


def to_utc_naive(value: datetime) -> datetime:
    """带时区的时间统一换算成朴素 UTC，和库里的存储口径保持一致。"""
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def ingest_report(
    session: Session,
    payload: ReportIn,
    rules_path: str | Path,
    seen_at: datetime | None = None,
) -> IngestResult:
    collected_at = to_utc_naive(payload.collected_at)
    observed_at = seen_at or utcnow()

    device = session.scalar(
        select(Device).where(Device.fingerprint == payload.device.fingerprint)
    )

    # 幂等：同一次采集重复提交直接返回，不产生任何副作用
    if device is not None:
        duplicate = session.scalar(
            select(Report).where(
                Report.device_id == device.id,
                Report.report_id == payload.report_id,
            )
        )
        if duplicate is not None:
            return IngestResult(
                status="duplicate",
                device_id=device.id,
                report_id=payload.report_id,
            )

    if device is None:
        device = Device(
            fingerprint=payload.device.fingerprint,
            hostname=payload.device.hostname,
            first_seen=observed_at,
            last_seen=observed_at,
        )
        session.add(device)
        session.flush()

    # 硬件概况每次巡检都刷新，人工维护的资产字段不动
    device.hostname = payload.device.hostname
    device.os_name = payload.device.os_name
    device.architecture = payload.device.architecture
    device.cpu_model = payload.device.cpu_model
    device.cpu_cores = payload.device.cpu_cores
    device.cpu_threads = payload.device.cpu_threads
    device.ram_total_gb = payload.device.ram_total_gb
    device.ssd_count = payload.device.ssd_count
    if observed_at > device.last_seen:
        device.last_seen = observed_at

    points = [
        MetricPoint(
            key=item.key,
            value=float(item.value),
            unit=item.unit,
            dimension=item.dimension,
        )
        for item in payload.metrics
    ]
    findings = evaluate(points, load_rules_cached(rules_path))

    warning_count = sum(1 for f in findings if f.level in ("critical", "warning"))
    notice_count = sum(1 for f in findings if f.level in ("notice", "info"))

    report = Report(
        device_id=device.id,
        report_id=payload.report_id,
        collected_at=collected_at,
        received_at=observed_at,
        summary=payload.summary,
        warning_count=warning_count,
        notice_count=notice_count,
        payload_json=payload.model_dump_json(),
    )
    session.add(report)
    session.flush()

    for point in points:
        session.add(
            Metric(
                device_id=device.id,
                report_pk=report.id,
                metric_key=point.key,
                dimension=point.dimension,
                metric_value=point.value,
                unit=point.unit,
                recorded_at=collected_at,
            )
        )

    created, updated, resolved = _sync_alerts(
        session=session,
        device=device,
        findings=findings,
        seen_keys={point.key for point in points},
        observed_at=observed_at,
    )

    session.flush()
    return IngestResult(
        status="stored",
        device_id=device.id,
        report_id=payload.report_id,
        alerts_created=created,
        alerts_updated=updated,
        alerts_resolved=resolved,
    )


def _sync_alerts(
    session: Session,
    device: Device,
    findings: list,
    seen_keys: set[str],
    observed_at: datetime,
) -> tuple[int, int, int]:
    """把本次评估结果同步到告警表。

    同一条规则持续命中只累加次数，不重复建告警；本次上报带回了该规则的
    指标但不再命中时，认为问题已恢复，自动关闭告警。
    """
    open_alerts = session.scalars(
        select(Alert).where(Alert.device_id == device.id, Alert.resolved_at.is_(None))
    ).all()
    open_map = {(alert.rule_id, alert.dimension): alert for alert in open_alerts}

    created = 0
    updated = 0
    resolved = 0
    matched: set[tuple[str, str | None]] = set()

    for finding in findings:
        key = (finding.rule_id, finding.dimension)
        matched.add(key)
        existing = open_map.get(key)
        if existing is not None:
            existing.occurrences += 1
            existing.last_seen = observed_at
            existing.metric_value = finding.metric_value
            existing.message = finding.message
            updated += 1
            continue

        session.add(
            Alert(
                device_id=device.id,
                rule_id=finding.rule_id,
                level=finding.level,
                metric_key=finding.metric_key,
                dimension=finding.dimension,
                metric_value=finding.metric_value,
                threshold_op=finding.threshold_op,
                threshold_value=finding.threshold_value,
                message=finding.message,
                occurrences=1,
                first_seen=observed_at,
                last_seen=observed_at,
            )
        )
        created += 1

    for key, alert in open_map.items():
        if key in matched:
            continue
        # 指标这次没上报（采集失败等），不能判定为恢复
        if alert.metric_key not in seen_keys:
            continue
        alert.resolved_at = observed_at
        alert.resolved_by = "auto"
        resolved += 1

    return created, updated, resolved
