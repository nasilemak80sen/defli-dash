"""Versioned unit-conversion rules for normalised simulation hours."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import csv
import math
from typing import Iterable

import numpy as np
import pandas as pd


class UnitConversionError(ValueError):
    """Raised when a usage row cannot be converted under an approved rule."""


@dataclass(frozen=True)
class UnitConversionRule:
    unit: str
    numerator: float
    denominator: float
    effective_from: date
    rule_version: str
    status: str
    source: str
    approved_by: str | None = None
    notes: str = ""

    @property
    def factor(self) -> float:
        if self.denominator == 0:
            raise UnitConversionError(f"Conversion rule for {self.unit!r} has a zero denominator.")
        return self.numerator / self.denominator


def load_conversion_rules(path: str | Path) -> list[UnitConversionRule]:
    rules: list[UnitConversionRule] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            try:
                rules.append(UnitConversionRule(
                    unit=row["unit"].strip(), numerator=float(row["numerator"]),
                    denominator=float(row["denominator"]),
                    effective_from=date.fromisoformat(row["effective_from"]),
                    rule_version=row["rule_version"].strip(), status=row["status"].strip().casefold(),
                    source=row["source"].strip(), approved_by=row.get("approved_by", "").strip() or None,
                    notes=row.get("notes", "").strip(),
                ))
            except (KeyError, TypeError, ValueError) as exc:
                raise UnitConversionError(f"Invalid conversion-rule row: {row!r}: {exc}") from exc
    if not rules:
        raise UnitConversionError("No unit conversion rules were found.")
    keys = [(rule.unit.casefold(), rule.effective_from) for rule in rules]
    if len(keys) != len(set(keys)):
        raise UnitConversionError("Duplicate conversion rules exist for the same unit and effective date.")
    for rule in rules:
        _ = rule.factor
        if (not math.isfinite(rule.numerator) or not math.isfinite(rule.denominator)
                or rule.numerator < 0 or rule.denominator <= 0):
            raise UnitConversionError(f"Invalid non-negative factor definition for unit {rule.unit!r}.")
        if not rule.unit.strip() or not rule.rule_version.strip() or rule.status not in {"proposed", "approved", "retired"}:
            raise UnitConversionError("Conversion rules require a unit, version and valid approval status.")
        if rule.status == "approved" and not rule.approved_by:
            raise UnitConversionError(f"Approved conversion rule {rule.rule_version!r} must name an approver.")
    return rules


def _rule_for(unit: str, period: str, rules: Iterable[UnitConversionRule]) -> UnitConversionRule:
    try:
        effective_date = pd.to_datetime(period, format="%b'%y", errors="raise").date().replace(day=1)
    except (ValueError, TypeError) as exc:
        raise UnitConversionError(f"Invalid usage month {period!r} for unit {unit!r}.") from exc
    candidates = [r for r in rules if r.unit.casefold() == unit.casefold() and r.effective_from <= effective_date]
    if not candidates:
        raise UnitConversionError(f"No conversion rule for unit {unit!r} effective on {effective_date}.")
    return max(candidates, key=lambda rule: rule.effective_from)


def convert_simulation_hours(frame: pd.DataFrame, rules: Iterable[UnitConversionRule], *,
                             require_approved: bool = True) -> pd.DataFrame:
    """Calculate normalised hours using effective-dated rules.

    Proposed/unapproved rules are blocked by default. The explicit override is
    intended only for sensitivity analysis and must never feed published ledgers.
    """
    required = ("Unit", "Month", "Hours")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise UnitConversionError(f"Simulation data is missing conversion inputs: {missing}.")
    rule_list = list(rules)
    result = frame.copy()
    converted: list[float] = []
    versions: list[str] = []
    for idx, row in result.iterrows():
        rule = _rule_for(str(row["Unit"]).strip(), str(row["Month"]).strip(), rule_list)
        if require_approved and rule.status != "approved":
            raise UnitConversionError(
                f"Rule {rule.rule_version} for {rule.unit!r} is {rule.status!r}; approved conversion is required."
            )
        raw_hours = pd.to_numeric(pd.Series([row["Hours"]]), errors="coerce").iloc[0]
        if pd.isna(raw_hours) or not np.isfinite(float(raw_hours)) or raw_hours < 0:
            raise UnitConversionError(f"Invalid raw Hours value at row {idx!r}: {row['Hours']!r}.")
        if rule.factor == 0 and raw_hours != 0:
            raise UnitConversionError(
                f"Rule {rule.rule_version} maps {rule.unit!r} to zero, but row {idx!r} has non-zero raw Hours."
            )
        converted.append(float(raw_hours) * rule.factor)
        versions.append(rule.rule_version)
    result["Calculated Normalised Hours"] = converted
    result["Rule Version"] = versions
    return result


def compare_to_source_normalised(frame: pd.DataFrame, rules: Iterable[UnitConversionRule],
                                 tolerance: float = 0.1) -> pd.DataFrame:
    """Diagnostic comparison only; allows proposed rules but marks their approval state."""
    if "Hours per User" not in frame.columns:
        raise UnitConversionError("Source-normalised comparison requires 'Hours per User'.")
    rule_list = list(rules)
    calculated = convert_simulation_hours(frame, rule_list, require_approved=False)
    lookup = {(rule.unit.casefold(), rule.rule_version): rule for rule in rule_list}
    statuses = []
    for unit, version in zip(calculated["Unit"], calculated["Rule Version"]):
        statuses.append(lookup[(str(unit).casefold(), version)].status)
    calculated["Source Normalised Hours"] = pd.to_numeric(calculated["Hours per User"], errors="coerce")
    if calculated["Source Normalised Hours"].isna().any() or not np.isfinite(
        calculated["Source Normalised Hours"].to_numpy(dtype=float)
    ).all():
        raise UnitConversionError("Source Hours per User contains missing or non-finite values.")
    calculated["Difference"] = calculated["Calculated Normalised Hours"] - calculated["Source Normalised Hours"]
    calculated["Matches Source"] = calculated["Difference"].abs() <= tolerance
    calculated["Rule Status"] = statuses
    return calculated
