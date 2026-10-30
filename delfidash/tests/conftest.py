from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest
import yaml


def create_source_workbook(path: Path, *, normalized_hours: float = 10.0, include_usage: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    usage = pd.DataFrame({
        "User": ["user-a"], "Unit": ["hour"], "Hours": [10.0],
        "Hours per User": [normalized_hours], "Updated Department": ["DPE"],
        "Updated Billing Dept": ["PE-RE"], "Month": ["Jan'26"],
    })
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        if include_usage:
            usage.to_excel(writer, sheet_name="Data_sim hrs", index=False)
        else:
            pd.DataFrame({"placeholder": [1]}).to_excel(writer, sheet_name="SUMMARY", index=False)

        pivot = pd.DataFrame([[None] * 23 for _ in range(6)], dtype=object)
        pivot.iloc[4, 0:13] = ["DPE", "PE-RE", "user-a", 10.0, None, None, None, None, None, None, None, None, 10.0]
        pivot.iloc[4, 16:23] = ["DPE", 211200.0, 10.0, 0.0, 10.0, 211190.0, None]
        pivot.iloc[5, 16:23] = ["Enterprise (Total)", 211200.0, 10.0, 0.0, 10.0, 211190.0, None]
        pivot.to_excel(writer, sheet_name="monthly sim hrs", header=False, index=False)
    return path


def create_approved_policy(source_policy: Path, target: Path) -> Path:
    policy = yaml.safe_load(source_policy.read_text(encoding="utf-8"))
    policy["status"] = "approved"
    policy["approval"] = {
        "approved_by": "Synthetic Test Owner",
        "approved_role": "Platform Owner",
        "approved_at": "2026-10-30",
        "approval_reference": "TEST-APPROVAL-001",
    }
    target.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")
    return target


def create_approved_rules(source_rules: Path, target: Path) -> Path:
    with source_rules.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames
        rows = list(reader)
    for row in rows:
        if row["unit"] == "hour":
            row.update({
                "status": "approved",
                "approved_by": "Synthetic Test Owner",
                "approval_date": "2026-10-30",
                "approval_evidence": "TEST-APPROVAL-001",
                "approval_role": "Platform Owner",
            })
    with target.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return target


@pytest.fixture
def approved_build_inputs(tmp_path):
    config_dir = Path(__file__).parents[1] / "config"
    source = create_source_workbook(tmp_path / "source" / "synthetic_delfi.xlsx")
    policy = create_approved_policy(config_dir / "policy.yaml", tmp_path / "policy.yaml")
    rules = create_approved_rules(config_dir / "unit_conversion.csv", tmp_path / "unit_conversion.csv")
    return {"source": source, "policy": policy, "rules": rules, "output": tmp_path / "processed"}
