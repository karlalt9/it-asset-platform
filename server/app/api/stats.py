"""看板统计接口。"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_session
from ..models import Alert, Device, utcnow
from ..rules import LEVELS, load_rules_cached
from ..schemas import OverviewOut, TrendPoint
from ..security import require_read_token

router = APIRouter(
    prefix="/stats",
    tags=["stats"],
    dependencies=[Depends(require_read_token)],
)


@router.get("/overview", response_model=OverviewOut, summary="看板总览")
def overview(session: Session = Depends(get_session)) -> OverviewOut:
    now = utcnow()
    deadline = now - timedelta(minutes=settings.offline_after_minutes)

    device_total = session.scalar(select(func.count()).select_from(Device)) or 0
    device_online = (
        session.scalar(
            select(func.count()).select_from(Device).where(Device.last_seen >= deadline)
        )
        or 0
    )

    open_rows = session.execute(
        select(Alert.level, func.count())
        .where(Alert.resolved_at.is_(None))
        .group_by(Alert.level)
    ).all()
    open_by_level = {str(level): int(count) for level, count in open_rows}
    for level in LEVELS:
        open_by_level.setdefault(level, 0)
    alert_open = sum(open_by_level.values())

    # 近 7 天每日告警数：在 Python 里按日期归并，避免依赖特定数据库的日期函数
    start = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
    recent = session.execute(
        select(Alert.level, Alert.first_seen).where(Alert.first_seen >= start)
    ).all()

    buckets: dict[str, Counter] = {}
    for offset in range(7):
        day = (start + timedelta(days=offset)).date().isoformat()
        buckets[day] = Counter()
    for level, first_seen in recent:
        day = first_seen.date().isoformat()
        if day in buckets:
            buckets[day][str(level)] += 1

    trend = [
        TrendPoint(
            date=day,
            critical=counts.get("critical", 0),
            warning=counts.get("warning", 0),
            notice=counts.get("notice", 0),
            info=counts.get("info", 0),
        )
        for day, counts in sorted(buckets.items())
    ]

    return OverviewOut(
        device_total=device_total,
        device_online=device_online,
        device_offline=device_total - device_online,
        alert_open=alert_open,
        alert_open_by_level=open_by_level,
        alert_trend=trend,
        rule_count=len([rule for rule in load_rules_cached(settings.rules_file) if rule.enabled]),
        generated_at=now,
    )
