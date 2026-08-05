from __future__ import annotations

from perf_analyzer.config import build_settings_config, validate_config
from perf_analyzer.rules import RiskRules, default_risk_rules, risk_rules_from_config, risk_rules_to_dict


def test_build_settings_contains_risk_rules():
    config = build_settings_config({}, 2.0, 0.0, [], {}, {})
    assert "risk_rules" in config["analysis"]
    assert config["analysis"]["risk_rules"]["response_ms_critical"] == 1000.0


def test_risk_rules_roundtrip():
    rules = default_risk_rules()
    data = risk_rules_to_dict(rules)
    imported = risk_rules_from_config({"analysis": {"risk_rules": data}})
    assert imported == rules


def test_risk_rules_partial_override():
    rules = risk_rules_from_config({"analysis": {"risk_rules": {"response_ms_critical": 2000.0}}})
    assert rules.response_ms_critical == 2000.0
    assert rules.fps_warning == 45.0


def test_risk_rules_ignores_unknown_and_invalid():
    rules = risk_rules_from_config(
        {"analysis": {"risk_rules": {"not_a_rule": 1.0, "leak_score": "abc", "fps_critical": 20.0}}}
    )
    assert rules.fps_critical == 20.0
    assert rules.leak_score == 3.0


def test_validate_config_warns_bad_rule_value():
    errors, warnings = validate_config({"analysis": {"risk_rules": {"response_ms_critical": "abc"}}})
    assert errors == []
    assert any("response_ms_critical" in warning for warning in warnings)


def test_validate_config_warns_unknown_rule_field():
    errors, warnings = validate_config({"analysis": {"risk_rules": {"mystery": 1.0}}})
    assert errors == []
    assert any("mystery" in warning for warning in warnings)


def test_validate_config_risk_rules_not_dict():
    errors, warnings = validate_config({"analysis": {"risk_rules": "nope"}})
    assert errors == []
    assert any("risk_rules" in warning for warning in warnings)


def test_risk_rules_all_fields_present():
    rules = default_risk_rules()
    data = risk_rules_to_dict(rules)
    expected = {
        "alert_ratio_warning",
        "alert_ratio_critical",
        "alert_minutes_warning",
        "alert_minutes_critical",
        "failure_rate_warning",
        "failure_rate_critical",
        "error_per_thousand_warning",
        "error_per_thousand_critical",
        "response_ms_warning",
        "response_ms_critical",
        "fps_warning",
        "fps_critical",
        "leak_score",
        "minor_leak_score",
    }
    assert set(data) == expected
    assert len(data) == 14
