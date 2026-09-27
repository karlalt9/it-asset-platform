"""接口出入参模型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DevicePayload(BaseModel):
    """Agent 上报的设备标识与硬件概况。"""

    fingerprint: str = Field(min_length=4, max_length=64)
    hostname: str = Field(min_length=1, max_length=128)
    os_name: str | None = None
    architecture: str | None = None
    cpu_model: str | None = None
    cpu_cores: int | None = None
    cpu_threads: int | None = None
    ram_total_gb: float | None = None
    ssd_count: int | None = None


class MetricIn(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    value: float
    unit: str | None = None
    dimension: str | None = Field(default=None, max_length=64)


class FindingIn(BaseModel):
    """Agent 本地给出的初步判断，仅存档，服务端以自己的规则为准。"""

    level: str = "notice"
    message: str = ""


class ReportIn(BaseModel):
    report_id: str = Field(min_length=8, max_length=64)
    collected_at: datetime
    agent_version: str | None = None
    summary: str | None = None
    device: DevicePayload
    metrics: list[MetricIn] = Field(default_factory=list)
    findings: list[FindingIn] = Field(default_factory=list)


class ReportAccepted(BaseModel):
    status: str
    device_id: int
    report_id: str
    alerts_created: int = 0
    alerts_updated: int = 0
    alerts_resolved: int = 0


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fingerprint: str
    hostname: str
    os_name: str | None
    architecture: str | None
    cpu_model: str | None
    cpu_cores: int | None
    cpu_threads: int | None
    ram_total_gb: float | None
    ssd_count: int | None
    owner: str | None
    department: str | None
    location: str | None
    note: str | None
    status: str
    first_seen: datetime
    last_seen: datetime


class DevicePage(BaseModel):
    items: list[DeviceOut]
    total: int
    page: int
    page_size: int


class DevicePatch(BaseModel):
    owner: str | None = Field(default=None, max_length=64)
    department: str | None = Field(default=None, max_length=64)
    location: str | None = Field(default=None, max_length=64)
    note: str | None = None


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    rule_id: str
    level: str
    metric_key: str
    dimension: str | None
    metric_value: float | None
    threshold_op: str | None
    threshold_value: float | None
    message: str
    occurrences: int
    first_seen: datetime
    last_seen: datetime
    resolved_at: datetime | None
    resolved_by: str | None
    note: str | None
    hostname: str | None = None


class AlertPage(BaseModel):
    items: list[AlertOut]
    total: int
    page: int
    page_size: int


class ResolveIn(BaseModel):
    note: str | None = None


class MetricPointOut(BaseModel):
    t: datetime
    v: float


class MetricSeriesOut(BaseModel):
    key: str
    dimension: str | None
    unit: str | None
    points: list[MetricPointOut]


class MetricSeriesResponse(BaseModel):
    series: list[MetricSeriesOut]


class ReportBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    report_id: str
    collected_at: datetime
    received_at: datetime
    summary: str | None
    warning_count: int
    notice_count: int


class DeviceDetail(BaseModel):
    device: DeviceOut
    open_alerts: list[AlertOut]
    recent_reports: list[ReportBrief]


class TrendPoint(BaseModel):
    date: str
    critical: int = 0
    warning: int = 0
    notice: int = 0
    info: int = 0


class OverviewOut(BaseModel):
    device_total: int
    device_online: int
    device_offline: int
    alert_open: int
    alert_open_by_level: dict[str, int]
    alert_trend: list[TrendPoint]
    rule_count: int
    generated_at: datetime
