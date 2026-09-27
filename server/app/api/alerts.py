"""告警接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_session
from ..models import Alert, Device, utcnow
from ..schemas import AlertOut, AlertPage, ResolveIn
from ..security import require_read_token

router = APIRouter(
    prefix="/alerts",
    tags=["alerts"],
    dependencies=[Depends(require_read_token)],
)


@router.get("", response_model=AlertPage, summary="告警列表")
def list_alerts(
    level: str | None = None,
    state: str = Query(default="open", pattern="^(open|resolved|all)$"),
    device_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    session: Session = Depends(get_session),
) -> AlertPage:
    conditions = []
    if level:
        conditions.append(Alert.level == level)
    if state == "open":
        conditions.append(Alert.resolved_at.is_(None))
    elif state == "resolved":
        conditions.append(Alert.resolved_at.is_not(None))
    if device_id:
        conditions.append(Alert.device_id == device_id)

    stmt = select(Alert, Device.hostname).join(Device, Alert.device_id == Device.id)
    count_stmt = select(func.count()).select_from(Alert).join(Device, Alert.device_id == Device.id)
    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = session.scalar(count_stmt) or 0
    rows = session.execute(
        stmt.order_by(Alert.last_seen.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items: list[AlertOut] = []
    for alert, hostname in rows:
        data = AlertOut.model_validate(alert)
        data.hostname = hostname
        items.append(data)

    return AlertPage(items=items, total=total, page=page, page_size=page_size)


@router.patch("/{alert_id}/resolve", response_model=AlertOut, summary="标记告警已处理")
def resolve_alert(
    alert_id: int,
    payload: ResolveIn,
    session: Session = Depends(get_session),
) -> AlertOut:
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="告警不存在")
    if alert.resolved_at is None:
        alert.resolved_at = utcnow()
        alert.resolved_by = "manual"
    if payload.note is not None:
        alert.note = payload.note
    session.commit()
    session.refresh(alert)

    hostname = session.scalar(select(Device.hostname).where(Device.id == alert.device_id))
    data = AlertOut.model_validate(alert)
    data.hostname = hostname
    return data
