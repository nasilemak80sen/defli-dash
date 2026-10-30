from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.units import UnitConversionError, UnitConversionRule, compare_to_source_normalised, convert_simulation_hours, load_conversion_rules

CONFIG = Path(__file__).parents[1] / "config" / "unit_conversion.csv"


def rule(unit="16CPU.hour", factor=1 / 16, status="approved"):
    return UnitConversionRule(
        unit, factor, 1, date(2026, 1, 1), "test-v1", status, "test fixture",
        "Platform Owner" if status == "approved" else None, "fixture evidence",
        date(2026, 1, 2) if status == "approved" else None,
        "CHG-123" if status == "approved" else None,
        "Platform owner" if status == "approved" else None,
    )


def test_config_rules_load_as_proposed_not_approved():
    rules = load_conversion_rules(CONFIG)
    assert {r.status for r in rules} == {"proposed"}
    assert {r.unit for r in rules} >= {"16CPU.hour", "8CPU.hour", "realization.hour", "vCPU.hour", "hour", "CPU.hour"}


def test_conversion_applies_effective_dated_rule_with_approval_evidence():
    frame = pd.DataFrame({"Unit": ["16CPU.hour"], "Month": ["Jan'26"], "Hours": [160.0]})
    result = convert_simulation_hours(frame, [rule()])
    assert result.loc[0, "Calculated Normalised Hours"] == 10.0
    assert result.loc[0, "Rule Version"] == "test-v1"
    assert result.loc[0, "Rule Status"] == "approved"


def test_unapproved_rule_is_blocked_by_default():
    frame = pd.DataFrame({"Unit": ["16CPU.hour"], "Month": ["Jan'26"], "Hours": [160.0]})
    with pytest.raises(UnitConversionError, match="approved conversion is required"):
        convert_simulation_hours(frame, [rule(status="proposed")])


def test_zero_factor_rejects_nonzero_raw_value():
    frame = pd.DataFrame({"Unit": ["CPU.hour"], "Month": ["Jan'26"], "Hours": [1.0]})
    zero_rule = UnitConversionRule(
        "CPU.hour", 0, 1, date(2026, 1, 1), "zero-v1", "approved", "test",
        "Platform Owner", "", date(2026, 1, 2), "CHG-124", "Platform owner",
    )
    with pytest.raises(UnitConversionError, match="non-zero raw Hours"):
        convert_simulation_hours(frame, [zero_rule])


def test_conversion_diagnostic_compares_with_workbook_normalised_hours():
    frame = pd.DataFrame({"Unit": ["16CPU.hour"], "Month": ["Jan'26"], "Hours": [160.0], "Hours per User": [10.0]})
    result = compare_to_source_normalised(frame, [rule(status="proposed")])
    assert bool(result.loc[0, "Matches Source"])
    assert result.loc[0, "Rule Status"] == "proposed"


def test_unknown_unit_fails_closed():
    frame = pd.DataFrame({"Unit": ["mystery.hour"], "Month": ["Jan'26"], "Hours": [12.0]})
    with pytest.raises(UnitConversionError, match="No conversion rule"):
        convert_simulation_hours(frame, [rule()])


def test_invalid_conversion_rule_denominator_is_rejected(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text(
        "unit,numerator,denominator,effective_from,rule_version,status,source,approved_by,notes,approval_date,approval_evidence,approval_role\n"
        "hour,1,0,2026-01-01,v1,approved,test,Owner,,2026-01-02,CHG-1,Platform owner\n",
        encoding="utf-8",
    )
    with pytest.raises(UnitConversionError, match="zero denominator"):
        load_conversion_rules(path)


def test_approved_rule_without_full_evidence_is_rejected(tmp_path):
    path = tmp_path / "incomplete.csv"
    path.write_text(
        "unit,numerator,denominator,effective_from,rule_version,status,source,approved_by,notes,approval_date,approval_evidence,approval_role\n"
        "hour,1,1,2026-01-01,v1,approved,test,Owner,,,,\n",
        encoding="utf-8",
    )
    with pytest.raises(UnitConversionError, match="requires approver, role, date and evidence"):
        load_conversion_rules(path)



def test_latest_effective_rule_supersedes_older_proposed_rule():
    old_proposed = UnitConversionRule(
        "16CPU.hour", 1, 16, date(2025, 1, 1), "old-proposed-v1",
        "proposed", "old source"
    )
    current_approved = UnitConversionRule(
        "16CPU.hour", 1, 16, date(2026, 1, 1), "current-approved-v2",
        "approved", "owner confirmation", "Owner", "",
        date(2026, 1, 5), "CHG-2026-01", "Platform owner"
    )
    frame = pd.DataFrame({"Unit": ["16CPU.hour"], "Month": ["Apr'26"], "Hours": [160.0]})
    result = convert_simulation_hours(frame, [old_proposed, current_approved])
    assert result.loc[0, "Rule Version"] == "current-approved-v2"
    assert result.loc[0, "Calculated Normalised Hours"] == 10.0
