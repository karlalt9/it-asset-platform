"""数据模型。

设计要点：

* devices 用 fingerprint 唯一标识一台机器，机器改名不会产生新设备。
* reports 保留每次巡检的原始数据，用于回溯。
* metrics 用长表存指标，方便按指标名做时间序列查询。
* alerts 对未处理告警做合并，避免同一条规则反复刷屏。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    """统一使用朴素 UTC 时间入库，避免本地时区和 UTC 混用。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hostname: Mapped[str] = mapped_column(String(128), index=True)
    os_name: Mapped[str | None] = mapped_column(String(160), default=None)
    architecture: Mapped[str | None] = mapped_column(String(32), default=None)
    cpu_model: Mapped[str | None] = mapped_column(String(160), default=None)
    cpu_cores: Mapped[int | None] = mapped_column(Integer, default=None)
    cpu_threads: Mapped[int | None] = mapped_column(Integer, default=None)
    ram_total_gb: Mapped[float | None] = mapped_column(Float, default=None)
    ssd_count: Mapped[int | None] = mapped_column(Integer, default=None)

    # 以下几项属于人工维护的资产信息，巡检不会覆盖
    owner: Mapped[str | None] = mapped_column(String(64), default=None)
    department: Mapped[str | None] = mapped_column(String(64), default=None)
    location: Mapped[str | None] = mapped_column(String(64), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)

    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    reports: Mapped[list["Report"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )

    @property
    def status(self) -> str:
        """根据最近一次上报时间判断在线状态。"""
        from .config import settings

        deadline = utcnow() - timedelta(minutes=settings.offline_after_minutes)
        return "online" if self.last_seen >= deadline else "offline"


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        # 幂等的关键：同一台设备的同一次采集只允许入库一次
        UniqueConstraint("device_id", "report_id", name="uq_reports_device_report"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    report_id: Mapped[str] = mapped_column(String(64))
    collected_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    summary: Mapped[str | None] = mapped_column(String(255), default=None)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    notice_count: Mapped[int] = mapped_column(Integer, default=0)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")

    device: Mapped[Device] = relationship(back_populates="reports")
    metrics: Mapped[list["Metric"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )


class Metric(Base):
    __tablename__ = "metrics"
    __table_args__ = (
        Index("ix_metrics_lookup", "device_id", "metric_key", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    report_pk: Mapped[int] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), index=True
    )
    metric_key: Mapped[str] = mapped_column(String(64))
    dimension: Mapped[str | None] = mapped_column(String(64), default=None)
    metric_value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(16), default=None)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    report: Mapped[Report] = relationship(back_populates="metrics")


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_open", "device_id", "rule_id", "dimension", "resolved_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[str] = mapped_column(String(64), index=True)
    level: Mapped[str] = mapped_column(String(16), index=True)
    metric_key: Mapped[str] = mapped_column(String(64))
    dimension: Mapped[str | None] = mapped_column(String(64), default=None)
    metric_value: Mapped[float | None] = mapped_column(Float, default=None)
    threshold_op: Mapped[str | None] = mapped_column(String(8), default=None)
    threshold_value: Mapped[float | None] = mapped_column(Float, default=None)
    message: Mapped[str] = mapped_column(String(255))

    # 同一条规则持续命中时合并成一条告警，只累加次数
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, index=True)
    resolved_by: Mapped[str | None] = mapped_column(String(16), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)

    device: Mapped[Device] = relationship(back_populates="alerts")
