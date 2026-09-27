"""Agent 上报接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_session
from ..ingest import ingest_report
from ..schemas import ReportAccepted, ReportIn
from ..security import require_agent_token

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/report", response_model=ReportAccepted, summary="接收一次巡检上报")
def submit_report(
    payload: ReportIn,
    session: Session = Depends(get_session),
    _: None = Depends(require_agent_token),
) -> ReportAccepted:
    result = ingest_report(session, payload, settings.rules_file)
    session.commit()
    return ReportAccepted(
        status=result.status,
        device_id=result.device_id,
        report_id=result.report_id,
        alerts_created=result.alerts_created,
        alerts_updated=result.alerts_updated,
        alerts_resolved=result.alerts_resolved,
    )
