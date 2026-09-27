"""生成演示数据。

用法::

    python -m app.seed --reset

会造出一批仿真的设备与历史巡检记录，其中包含磁盘将满、内存吃紧、
缺少固态盘、安全设置未开启等典型情况，用来演示看板和告警流程。
"""

from __future__ import annotations

import argparse
import hashlib
import random
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, select

from .config import settings
from .database import SessionLocal, init_db
from .ingest import ingest_report
from .models import Alert, Device, Metric, Report, utcnow
from .schemas import DevicePayload, MetricIn, ReportIn

DEPARTMENTS = [
    ("生产一部", "PROD1"),
    ("生产二部", "PROD2"),
    ("品质部", "QC"),
    ("仓储部", "WH"),
    ("行政部", "ADMIN"),
    ("IT 部", "IT"),
]

LOCATIONS = ["一号厂房", "二号厂房", "综合办公楼", "质检中心", "成品仓库"]

OWNERS = [
    "张伟",
    "李娜",
    "王强",
    "刘洋",
    "陈静",
    "赵鹏",
    "周敏",
    "吴刚",
    "郑霞",
    "孙楠",
    "马超",
    "黄丽",
]

OS_POOL = [
    "Windows 10 Pro 22H2 (内部版本 19045)",
    "Windows 11 Home China 24H2 (内部版本 26100)",
    "Windows 11 Pro 23H2 (内部版本 22631)",
]

CPU_POOL = [
    ("13th Gen Intel(R) Core(TM) i5-13500H", 12, 16),
    ("Intel(R) Core(TM) i5-10400 CPU @ 2.90GHz", 6, 12),
    ("AMD Ryzen 5 5600G with Radeon Graphics", 6, 12),
    ("Intel(R) Core(TM) i3-10100 CPU @ 3.60GHz", 4, 8),
    ("12th Gen Intel(R) Core(TM) i7-12700", 12, 20),
]


@dataclass
class DemoDevice:
    index: int
    fingerprint: str
    hostname: str
    profile: str
    os_name: str
    cpu_model: str
    cpu_cores: int
    cpu_threads: int
    ram_total_gb: float
    ssd_count: int
    drives: list[tuple[str, float]]
    disk_base: dict[str, float]
    uptime_base: float
    signature_age: float
    owner: str
    department: str
    location: str
    online: bool


def _pick_profile(rng: random.Random) -> str:
    roll = rng.random()
    if roll < 0.50:
        return "normal"
    if roll < 0.72:
        return "disk_full"
    if roll < 0.84:
        return "memory_pressure"
    if roll < 0.94:
        return "hdd_only"
    return "risk"


def build_devices(count: int, rng: random.Random) -> list[DemoDevice]:
    devices: list[DemoDevice] = []
    for index in range(1, count + 1):
        profile = _pick_profile(rng)
        department, code = rng.choice(DEPARTMENTS)
        cpu_model, cores, threads = rng.choice(CPU_POOL)
        hostname = f"PC-{code}-{index:03d}"
        fingerprint = hashlib.sha256(f"demo-device-{index}".encode()).hexdigest()[:16]

        drives: list[tuple[str, float]] = [("C:", rng.choice([237.0, 476.0]))]
        if rng.random() < 0.65:
            drives.append(("D:", rng.choice([931.0, 465.0])))

        if profile == "disk_full":
            disk_base = {"C:": rng.uniform(76.0, 88.0)}
            for name, _ in drives[1:]:
                disk_base[name] = rng.uniform(91.0, 97.0)
        else:
            disk_base = {name: rng.uniform(48.0, 76.0) for name, _ in drives}

        devices.append(
            DemoDevice(
                index=index,
                fingerprint=fingerprint,
                hostname=hostname,
                profile=profile,
                os_name=rng.choice(OS_POOL),
                cpu_model=cpu_model,
                cpu_cores=cores,
                cpu_threads=threads,
                ram_total_gb=rng.choice([8.0, 16.0, 16.0, 32.0]),
                ssd_count=0 if profile == "hdd_only" else 1,
                drives=drives,
                disk_base=disk_base,
                uptime_base=rng.uniform(25.0, 60.0) if profile == "hdd_only" else rng.uniform(0.5, 20.0),
                signature_age=rng.uniform(8.0, 20.0) if profile == "risk" else rng.uniform(0.0, 5.0),
                owner=rng.choice(OWNERS),
                department=department,
                location=rng.choice(LOCATIONS),
                online=rng.random() > 0.15,
            )
        )
    return devices


def build_report(
    device: DemoDevice,
    rng: random.Random,
    collected_at,
    uptime_days: float,
) -> ReportIn:
    cpu_load = rng.uniform(6.0, 45.0)
    if device.profile == "memory_pressure":
        cpu_load = rng.uniform(25.0, 72.0)

    used_memory = (
        rng.uniform(87.0, 95.0)
        if device.profile == "memory_pressure"
        else rng.uniform(42.0, 72.0)
    )
    free_memory = device.ram_total_gb * (1 - used_memory / 100)

    firewall_off = rng.choice([1, 2, 3]) if device.profile == "risk" else 0
    realtime_off = 1 if device.profile == "risk" else 0
    pending_reboot = 1 if rng.random() < 0.08 else 0

    metrics: list[MetricIn] = [
        MetricIn(key="cpu.load_percent", value=round(cpu_load, 1), unit="%"),
        MetricIn(key="cpu.cores", value=float(device.cpu_cores), unit="个"),
        MetricIn(key="memory.used_percent", value=round(used_memory, 1), unit="%"),
        MetricIn(key="memory.total_gb", value=device.ram_total_gb, unit="GB"),
        MetricIn(key="memory.free_gb", value=round(free_memory, 1), unit="GB"),
        MetricIn(key="system.uptime_days", value=round(uptime_days, 1), unit="天"),
        MetricIn(key="system.pending_reboot", value=float(pending_reboot), unit="个"),
        MetricIn(key="hardware.ssd_count", value=float(device.ssd_count), unit="块"),
        MetricIn(
            key="security.firewall_disabled_profiles",
            value=float(firewall_off),
            unit="个",
        ),
        MetricIn(key="security.defender_realtime_off", value=float(realtime_off), unit="个"),
        MetricIn(
            key="security.defender_signature_age_days",
            value=round(device.signature_age, 1),
            unit="天",
        ),
    ]

    for name, total in device.drives:
        used = device.disk_base[name] + rng.uniform(-3.0, 5.0)
        used = min(max(used, 20.0), 98.0)
        metrics.append(
            MetricIn(key="disk.used_percent", value=round(used, 1), unit="%", dimension=name)
        )
        metrics.append(
            MetricIn(key="disk.total_gb", value=total, unit="GB", dimension=name)
        )
        metrics.append(
            MetricIn(
                key="disk.free_gb",
                value=round(total * (1 - used / 100), 1),
                unit="GB",
                dimension=name,
            )
        )

    report_id = hashlib.md5(
        f"{device.fingerprint}-{collected_at.isoformat()}".encode()
    ).hexdigest()

    return ReportIn(
        report_id=report_id,
        collected_at=collected_at,
        agent_version="2.0.0-demo",
        summary=f"{device.hostname} 巡检上报",
        device=DevicePayload(
            fingerprint=device.fingerprint,
            hostname=device.hostname,
            os_name=device.os_name,
            architecture="AMD64",
            cpu_model=device.cpu_model,
            cpu_cores=device.cpu_cores,
            cpu_threads=device.cpu_threads,
            ram_total_gb=device.ram_total_gb,
            ssd_count=device.ssd_count,
        ),
        metrics=metrics,
        findings=[],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="生成演示数据")
    parser.add_argument("--devices", type=int, default=14, help="设备数量")
    parser.add_argument("--days", type=int, default=14, help="历史天数")
    parser.add_argument("--interval-hours", type=int, default=6, help="上报间隔（小时）")
    parser.add_argument("--reset", action="store_true", help="先清空现有数据")
    parser.add_argument("--seed", type=int, default=20260927, help="随机种子")
    args = parser.parse_args()

    init_db()
    rng = random.Random(args.seed)
    now = utcnow().replace(microsecond=0)
    devices = build_devices(args.devices, rng)
    steps = max(1, int(args.days * 24 / max(1, args.interval_hours)))

    stored = 0
    created_alerts = 0

    with SessionLocal() as session:
        if args.reset:
            for model in (Alert, Metric, Report, Device):
                session.execute(delete(model))
            session.commit()

        for device in devices:
            last_step = 0 if device.online else 12
            for step in range(steps, last_step - 1, -1):
                collected_at = now - timedelta(hours=step * args.interval_hours)
                uptime_days = device.uptime_base + (steps - step) * args.interval_hours / 24
                payload = build_report(device, rng, collected_at, uptime_days)
                seen_at = (
                    max(collected_at, now - timedelta(minutes=rng.randint(1, 40)))
                    if device.online
                    else collected_at
                )
                result = ingest_report(
                    session,
                    payload,
                    settings.rules_file,
                    seen_at=seen_at,
                )
                if result.status == "stored":
                    stored += 1
                    created_alerts += result.alerts_created
            session.commit()

            # 补录资产信息。实际使用中这几项由 IT 人工维护,巡检上报不会覆盖,
            # 演示数据里直接用生成好的值填上。
            row = session.scalar(
                select(Device).where(Device.fingerprint == device.fingerprint)
            )
            if row is not None:
                row.owner = device.owner
                row.department = device.department
                row.location = device.location
            session.commit()

    print(f"已生成 {len(devices)} 台设备、{stored} 条巡检记录、{created_alerts} 条新告警")
    print("启动服务后访问 http://127.0.0.1:8000/docs 查看接口")


if __name__ == "__main__":
    main()
