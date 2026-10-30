"""Versioned, evidence-gated unit conversion for normalised simulation hours."""
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
    """Raised when a usage row cannot be converted under a valid rule."""


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
    approval_date: date | None = None
    approval_evidence: str | None = None
    approval_role: str | None = None

    @property
    def factor(self) -> float:
        if self.denominator == 0:
            raise UnitConversionError(f"Conversion rule for {self.unit!r} has a zero denominator.")
        return self.numerator / self.denominator


def load_conversion_rules(path: str | Path) -> list[UnitConversionRule]:
    rules: list[UnitConversionRule] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"unit", "numerator", "denominator", "effective_from", "rule_version",
                    "status", "source", "approved_by", "notes", "approval_date",
                    "approval_evidence", "approval_role"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise UnitConversionError(f"Conversion rules are missing columns: {sorted(missing)}.")
        for row in reader:
            try:
                approval_date = date.fromisoformat(row["approval_date"]) if row["approval_date"].strip() else None
                rules.append(UnitConversionRule(
                    unit=row["unit"].strip(), numerator=float(row["numerator"]),
                    denominator=float(row["denominator"]),
                    effective_from=date.fromisoformat(row["effective_from"]),
                    rule_version=row["rule_version"].strip(), status=row["status"].strip().casefold(),
                    source=row["source"].strip(), approved_by=row["approved_by"].strip() or None,
                    notes=row["notes"].strip(), approval_date=approval_date,
                    approval_evidence=row["approval_evidence"].strip() or None,
                    approval_role=row["approval_role"].strip() or None,
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
        if not rule.unit or not rule.rule_version or not rule.source:
            raise UnitConversionError("Conversion rules require unit, version and source.")
        if rule.status not in {"proposed", "approved", "retired"}:
            raise UnitConversionError(f"Invalid status {rule.status!r} for {rule.unit!r}.")
        if rule.status == "approved":
            evidence = (rule.approved_by, rule.approval_role, rule.approval_date, rule.approval_evidence)
            if not all(evidence):
                raise UnitConversionError(
                    f"Approved rule {rule.rule_version!r} requires approver, role, date and evidence reference."
                )
    return rules


def _rule_for(unit: str, period: str, rules: Iterable[UnitConversionRule]) -> UnitConversionRule:
    try:
        effective_date = pd.to_datetime(period, format="%b'%y", errors="raise").date().replace(day=1)
    except (ValueError, TypeError) as exc:
        raise UnitConversionError(f"Invalid usage month {period!r} for unit {unit!r}.") from exc
    candidates = [r for r in rules if r.unit.casefold() == unit.casefold() and r.effective_from <= effective_date]
    if not candidates:
        raise UnitConversionError(f"No conversion rule for unit {unit!r} effective on {effective_date}.")
    selected = max(candidates, key=lambda rule: rule.effective_from)
    if selected.status == "retired":
        raise UnitConversionError(f"Rule {selected.rule_version!r} for {unit!r} is retired.")
    return selected


def convert_simulation_hours(frame: pd.DataFrame, rules: Iterable[UnitConversionRule], *,
                             require_approved: bool = True) -> pd.DataFrame:
    """Calculate normalised hours using effective-dated rules.

    The diagnostic override never grants approval. Published ledgers require a
    rule with recorded owner, role, date and evidence reference.
    """
    required = ("Unit", "Month", "Hours")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise UnitConversionError(f"Simulation data is missing conversion inputs: {missing}.")
    rule_list = list(rules)
    result = frame.copy()
    converted: list[float] = []
    versions: list[str] = []
    statuses: list[str] = []
    for idx, row in result.iterrows():
        rule = _rule_for(str(row["Unit"]).strip(), str(row["Month"]).strip(), rule_list)
        if require_approved and rule.status != "approved":
            raise UnitConversionError(
                f"Rule {rule.rule_version} for {rule.unit!r} is {rule.status!r}; approved conversion is required."
            )
        if require_approved and not all((rule.approved_by, rule.approval_role, rule.approval_date, rule.approval_evidence)):
            raise UnitConversionError(f"Rule {rule.rule_version!r} has incomplete approval evidence.")
        raw_hours = pd.to_numeric(pd.Series([row["Hours"]]), errors="coerce").iloc[0]
        if pd.isna(raw_hours) or not np.isfinite(float(raw_hours)) or raw_hours < 0:
            raise UnitConversionError(f"Invalid raw Hours value at row {idx!r}: {row['Hours']!r}.")
        if rule.factor == 0 and raw_hours != 0:
            raise UnitConversionError(
                f"Rule {rule.rule_version} maps {rule.unit!r} to zero, but row {idx!r} has non-zero raw Hours."
            )
        converted.append(float(raw_hours) * rule.factor)
        versions.append(rule.rule_version)
        statuses.append(rule.status)
    result["Calculated Normalised Hours"] = converted
    result["Rule Version"] = versions
    result["Rule Status"] = statuses
    return result


def compare_to_source_normalised(frame: pd.DataFrame, rules: Iterable[UnitConversionRule],
                                 tolerance: float = 0.1) -> pd.DataFrame:
    """Diagnostic comparison only; proposed factors can be tested but not published."""
    if "Hours per User" not in frame.columns:
        raise UnitConversionError("Source-normalised comparison requires 'Hours per User'.")
    calculated = convert_simulation_hours(frame, rules, require_approved=False)
    source = pd.to_numeric(calculated["Hours per User"], errors="coerce")
    values = source.to_numpy(dtype=float, na_value=float("nan"))
    if not np.isfinite(values).all():
        raise UnitConversionError("Source Hours per User contains missing or non-finite values.")
    calculated["Source Normalised Hours"] = source
    calculated["Difference"] = calculated["Calculated Normalised Hours"] - source
    calculated["Matches Source"] = calculated["Difference"].abs() <= tolerance
    return calculated
