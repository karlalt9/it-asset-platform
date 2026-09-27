"""设备资产接口。"""

from __future__ import annotations

import csv
import io
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_session
from ..models import Alert, Device, Metric, Report, utcnow
from ..schemas import (
    AlertOut,
    DeviceDetail,
    DeviceOut,
    DevicePage,
    DevicePatch,
    MetricPointOut,
    MetricSeriesOut,
    MetricSeriesResponse,
    ReportBrief,
)
from ..security import require_read_token

router = APIRouter(
    prefix="/devices",
    tags=["devices"],
    dependencies=[Depends(require_read_token)],
)


def _device_or_404(session: Session, device_id: int) -> Device:
    device = session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="设备不存在")
    return device


def _with_hostname(alert: Alert, hostname: str) -> AlertOut:
    data = AlertOut.model_validate(alert)
    data.hostname = hostname
    return data


@router.get("", response_model=DevicePage, summary="设备列表")
def list_devices(
    keyword: str | None = Query(default=None, description="匹配主机名、使用人、部门"),
    status_filter: str | None = Query(default=None, alias="status"),
    department: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    session: Session = Depends(get_session),
) -> DevicePage:
    conditions = []
    if keyword:
        pattern = f"%{keyword.strip()}%"
        conditions.append(
            or_(
                Device.hostname.ilike(pattern),
                Device.owner.ilike(pattern),
                Device.department.ilike(pattern),
                Device.location.ilike(pattern),
                Device.fingerprint.ilike(pattern),
            )
        )
    if department:
        conditions.append(Device.department == department)
    if status_filter in ("online", "offline"):
        deadline = utcnow() - timedelta(minutes=settings.offline_after_minutes)
        if status_filter == "online":
            conditions.append(Device.last_seen >= deadline)
        else:
            conditions.append(Device.last_seen < deadline)

    stmt = select(Device)
    count_stmt = select(func.count()).select_from(Device)
    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = session.scalar(count_stmt) or 0
    rows = session.scalars(
        stmt.order_by(Device.last_seen.desc(), Device.hostname)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return DevicePage(
        items=[DeviceOut.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/export/csv", summary="导出资产清单")
def export_devices(session: Session = Depends(get_session)) -> Response:
    rows = session.scalars(select(Device).order_by(Device.hostname)).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "主机名",
            "使用人",
            "部门",
            "位置",
            "操作系统",
            "CPU",
            "内存(GB)",
            "固态盘数量",
            "状态",
            "最近上报",
            "设备指纹",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.hostname,
                row.owner or "",
                row.department or "",
                row.location or "",
                row.os_name or "",
                row.cpu_model or "",
                row.ram_total_gb if row.ram_total_gb is not None else "",
                row.ssd_count if row.ssd_count is not None else "",
                "在线" if row.status == "online" else "离线",
                row.last_seen.strftime("%Y-%m-%d %H:%M:%S"),
                row.fingerprint,
            ]
        )

    # 带 BOM，Excel 打开时中文不会乱码
    content = "\ufeff" + buffer.getvalue()
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="devices.csv"'},
    )


@router.get("/{device_id}", response_model=DeviceDetail, summary="设备详情")
def get_device(device_id: int, session: Session = Depends(get_session)) -> DeviceDetail:
    device = _device_or_404(session, device_id)

    alerts = session.scalars(
        select(Alert)
        .where(Alert.device_id == device_id, Alert.resolved_at.is_(None))
        .order_by(Alert.last_seen.desc())
    ).all()

    reports = session.scalars(
        select(Report)
        .where(Report.device_id == device_id)
        .order_by(Report.collected_at.desc())
        .limit(10)
    ).all()

    return DeviceDetail(
        device=DeviceOut.model_validate(device),
        open_alerts=[_with_hostname(alert, device.hostname) for alert in alerts],
        recent_reports=[ReportBrief.model_validate(report) for report in reports],
    )


@router.patch("/{device_id}", response_model=DeviceOut, summary="补录资产信息")
def update_device(
    device_id: int,
    payload: DevicePatch,
    session: Session = Depends(get_session),
) -> DeviceOut:
    device = _device_or_404(session, device_id)
    for field in ("owner", "department", "location", "note"):
        value = getattr(payload, field)
        if value is not None:
            setattr(device, field, value)
    session.commit()
    session.refresh(device)
    return DeviceOut.model_validate(device)


@router.delete("/{device_id}", status_code=204, summary="删除设备及其全部历史记录")
def delete_device(device_id: int, session: Session = Depends(get_session)) -> Response:
    """删除一台设备，同时清理它的巡检记录、指标和告警。

    设备是通过 Agent 上报自动注册的，重新在这台机器上跑一次 Agent
    就会再次出现在列表里，所以这里删除的是台账记录和历史数据。
    """
    device = _device_or_404(session, device_id)
    session.delete(device)
    session.commit()
    return Response(status_code=204)


@router.get(
    "/{device_id}/metrics",
    response_model=MetricSeriesResponse,
    summary="指标时间序列",
)
def get_device_metrics(
    device_id: int,
    key: list[str] | None = Query(default=None, description="按指标名过滤，可重复传"),
    hours: int = Query(default=168, ge=1, le=24 * 90),
    session: Session = Depends(get_session),
) -> MetricSeriesResponse:
    _device_or_404(session, device_id)

    since = utcnow() - timedelta(hours=hours)
    stmt = (
        select(Metric)
        .where(Metric.device_id == device_id, Metric.recorded_at >= since)
        .order_by(Metric.recorded_at)
    )
    if key:
        stmt = stmt.where(Metric.metric_key.in_(key))

    groups: dict[tuple[str, str | None], MetricSeriesOut] = {}
    for row in session.scalars(stmt).all():
        group_key = (row.metric_key, row.dimension)
        series = groups.get(group_key)
        if series is None:
            series = MetricSeriesOut(
                key=row.metric_key,
                dimension=row.dimension,
                unit=row.unit,
                points=[],
            )
            groups[group_key] = series
        series.points.append(MetricPointOut(t=row.recorded_at, v=row.metric_value))

    return MetricSeriesResponse(series=list(groups.values()))
