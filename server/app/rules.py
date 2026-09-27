"""阈值规则引擎。

规则放在 JSON 配置文件里而不是数据库：规则属于配置，进 Git、可评审、
改完重启即生效，也不需要额外做一套管理界面。
"""

from __future__ import annotations

import json
import operator
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

OPERATORS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}

LEVELS = ("critical", "warning", "notice", "info")


@dataclass(frozen=True)
class Rule:
    id: str
    metric: str
    op: str
    value: float
    level: str
    message: str
    description: str = ""
    enabled: bool = True

    def compare(self, actual: float) -> bool:
        func = OPERATORS[self.op]
        return bool(func(actual, self.value))


@dataclass(frozen=True)
class MetricPoint:
    key: str
    value: float
    unit: str | None = None
    dimension: str | None = None


@dataclass(frozen=True)
class Finding:
    rule_id: str
    level: str
    message: str
    metric_key: str
    metric_value: float
    threshold_op: str
    threshold_value: float
    dimension: str | None = None


class _SafeFormatter(string.Formatter):
    """模板里引用不到的变量保持原样，格式说明符出错时退回原字符串。"""

    def get_value(self, key: Any, args: Any, kwargs: Any) -> Any:
        if isinstance(key, str):
            return kwargs.get(key, "{" + key + "}")
        return super().get_value(key, args, kwargs)

    def format_field(self, value: Any, format_spec: str) -> str:
        if isinstance(value, str) and format_spec:
            return value
        return super().format_field(value, format_spec)


_FORMATTER = _SafeFormatter()


def format_message(template: str, context: dict[str, Any]) -> str:
    try:
        return _FORMATTER.vformat(template, (), context)
    except Exception:
        return template


def parse_rules(document: dict[str, Any]) -> list[Rule]:
    rules: list[Rule] = []
    for raw in document.get("rules", []):
        op = str(raw.get("op", ""))
        if op not in OPERATORS:
            raise ValueError(f"规则 {raw.get('id')} 使用了不支持的操作符: {op!r}")
        level = str(raw.get("level", "notice"))
        if level not in LEVELS:
            raise ValueError(f"规则 {raw.get('id')} 使用了未知等级: {level!r}")
        rules.append(
            Rule(
                id=str(raw["id"]),
                metric=str(raw["metric"]),
                op=op,
                value=float(raw["value"]),
                level=level,
                message=str(raw.get("message", raw["id"])),
                description=str(raw.get("description", "")),
                enabled=bool(raw.get("enabled", True)),
            )
        )
    return rules


def load_rules(path: str | Path) -> list[Rule]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_rules(document)


_CACHE: dict[str, tuple[float, list[Rule]]] = {}


def load_rules_cached(path: str | Path) -> list[Rule]:
    """带 mtime 校验的缓存：改了规则文件不用重启也能生效。"""
    target = Path(path)
    try:
        mtime = target.stat().st_mtime
    except OSError:
        return []

    key = str(target)
    cached = _CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    rules = load_rules(target)
    _CACHE[key] = (mtime, rules)
    return rules


def clear_rule_cache() -> None:
    _CACHE.clear()


def evaluate(points: Iterable[MetricPoint], rules: Iterable[Rule]) -> list[Finding]:
    """逐条规则匹配指标点，返回命中结果。

    同一个指标可能带多个 dimension（例如每个磁盘分区一个点），
    因此这里按点逐个判定，不做聚合。
    """
    by_key: dict[str, list[MetricPoint]] = {}
    for point in points:
        by_key.setdefault(point.key, []).append(point)

    findings: list[Finding] = []
    for rule in rules:
        if not rule.enabled:
            continue
        for point in by_key.get(rule.metric, ()):
            if point.value is None:
                continue
            if not rule.compare(point.value):
                continue
            context = {
                "value": point.value,
                "threshold": rule.value,
                "dimension": point.dimension or "",
                "unit": point.unit or "",
                "metric": rule.metric,
            }
            findings.append(
                Finding(
                    rule_id=rule.id,
                    level=rule.level,
                    message=format_message(rule.message, context),
                    metric_key=rule.metric,
                    metric_value=float(point.value),
                    threshold_op=rule.op,
                    threshold_value=rule.value,
                    dimension=point.dimension,
                )
            )
    return findings
