"""规则引擎单元测试。

规则引擎是最容易被追问的部分，这里覆盖边界值、模板渲染和配置校验。
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.rules import MetricPoint, evaluate, format_message, load_rules, parse_rules


def test_default_rules_are_loadable() -> None:
    rules = load_rules(settings.rules_file)
    ids = {rule.id for rule in rules}
    assert "disk_used_high" in ids
    assert "firewall_disabled" in ids
    assert len(rules) >= 8


def test_disk_rule_renders_dimension_into_message() -> None:
    rules = load_rules(settings.rules_file)
    findings = evaluate(
        [MetricPoint(key="disk.used_percent", value=91.4, unit="%", dimension="D:")],
        rules,
    )
    disk_findings = [item for item in findings if item.rule_id == "disk_used_high"]
    assert len(disk_findings) == 1
    assert "D:" in disk_findings[0].message
    assert "91.4" in disk_findings[0].message


def test_inclusive_operator_matches_equal_value() -> None:
    rules = parse_rules(
        {
            "rules": [
                {
                    "id": "r",
                    "metric": "m",
                    "op": ">=",
                    "value": 85,
                    "level": "warning",
                    "message": "x",
                }
            ]
        }
    )
    assert evaluate([MetricPoint(key="m", value=85.0)], rules)


def test_exclusive_operator_ignores_equal_value() -> None:
    rules = parse_rules(
        {
            "rules": [
                {
                    "id": "r",
                    "metric": "m",
                    "op": ">",
                    "value": 85,
                    "level": "warning",
                    "message": "x",
                }
            ]
        }
    )
    assert not evaluate([MetricPoint(key="m", value=85.0)], rules)
    assert evaluate([MetricPoint(key="m", value=85.1)], rules)


def test_disabled_rule_is_skipped() -> None:
    rules = parse_rules(
        {
            "rules": [
                {
                    "id": "r",
                    "metric": "m",
                    "op": ">",
                    "value": 1,
                    "level": "warning",
                    "message": "x",
                    "enabled": False,
                }
            ]
        }
    )
    assert evaluate([MetricPoint(key="m", value=99.0)], rules) == []


def test_unrelated_metric_is_ignored() -> None:
    rules = parse_rules(
        {
            "rules": [
                {
                    "id": "r",
                    "metric": "m",
                    "op": ">",
                    "value": 1,
                    "level": "warning",
                    "message": "x",
                }
            ]
        }
    )
    assert evaluate([MetricPoint(key="other", value=99.0)], rules) == []


def test_dimensions_are_evaluated_independently() -> None:
    rules = parse_rules(
        {
            "rules": [
                {
                    "id": "disk",
                    "metric": "disk.used_percent",
                    "op": ">=",
                    "value": 85,
                    "level": "warning",
                    "message": "{dimension} 盘告警",
                }
            ]
        }
    )
    findings = evaluate(
        [
            MetricPoint(key="disk.used_percent", value=90.0, dimension="C:"),
            MetricPoint(key="disk.used_percent", value=50.0, dimension="D:"),
        ],
        rules,
    )
    assert len(findings) == 1
    assert findings[0].dimension == "C:"


def test_message_template_keeps_unknown_placeholder() -> None:
    rendered = format_message("值 {value:.1f} 单位 {unit}", {"value": 1.234})
    assert rendered == "值 1.2 单位 {unit}"


def test_unknown_message_variable_does_not_raise() -> None:
    assert format_message("{nothing}", {}) == "{nothing}"


def test_invalid_operator_is_rejected() -> None:
    with pytest.raises(ValueError):
        parse_rules(
            {
                "rules": [
                    {
                        "id": "r",
                        "metric": "m",
                        "op": "=<",
                        "value": 1,
                        "level": "warning",
                        "message": "x",
                    }
                ]
            }
        )


def test_invalid_level_is_rejected() -> None:
    with pytest.raises(ValueError):
        parse_rules(
            {
                "rules": [
                    {
                        "id": "r",
                        "metric": "m",
                        "op": ">",
                        "value": 1,
                        "level": "urgent",
                        "message": "x",
                    }
                ]
            }
        )
