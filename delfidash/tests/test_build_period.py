from pathlib import Path

import pytest
import yaml

from jobs.build_period import BuildBlockedError, build_period
from src.marts import PublishedMartNotFound, load_published_period


def test_end_to_end_build_reconciles_and_publishes_parquet_marts(approved_build_inputs):
    inputs = approved_build_inputs
    manifest_path = build_period(
        inputs["source"], policy_path=inputs["policy"], rules_path=inputs["rules"],
        output_root=inputs["output"],
    )
    assert manifest_path.is_file()
    data = load_published_period(inputs["output"], "2026-01")
    assert data["build_metadata"]["publication_status"] == "published"
    assert data["sim"]["Hours per User"].tolist() == [10.0]
    assert data["monthly"].loc[0, "Hours"] == 10.0
    assert data["department_ledger"].loc[0, "Policy Status"] == "WITHIN POLICY"
    assert data["reconciliation"]["Status"].isin(["PASS", "NOT APPLICABLE"]).all()


def test_build_is_idempotent_for_same_source_period_and_policy(approved_build_inputs):
    inputs = approved_build_inputs
    first = build_period(inputs["source"], policy_path=inputs["policy"],
                         rules_path=inputs["rules"], output_root=inputs["output"])
    second = build_period(inputs["source"], policy_path=inputs["policy"],
                          rules_path=inputs["rules"], output_root=inputs["output"])
    assert first == second


def test_proposed_policy_quarantines_period_without_publishing(approved_build_inputs):
    inputs = approved_build_inputs
    policy_text = inputs["policy"].read_text(encoding="utf-8").replace("status: approved", "status: proposed")
    proposed = inputs["policy"].parent / "policy-proposed.yaml"
    proposed.write_text(policy_text, encoding="utf-8")
    with pytest.raises(BuildBlockedError, match="no published mart"):
        build_period(inputs["source"], policy_path=proposed,
                     rules_path=inputs["rules"], output_root=inputs["output"])
    with pytest.raises(PublishedMartNotFound):
        load_published_period(inputs["output"], "2026-01")
    assert list((inputs["output"] / "_quarantine" / "2026-01").glob("*/reconciliation.csv"))


def test_conversion_mismatch_blocks_publication(approved_build_inputs, tmp_path):
    inputs = approved_build_inputs
    from openpyxl import load_workbook as load_xlsx_workbook
    altered_source = tmp_path / "altered.xlsx"
    workbook = load_xlsx_workbook(inputs["source"])
    workbook["Data_sim hrs"]["D2"] = 9.0
    workbook.save(altered_source)
    workbook.close()
    with pytest.raises(BuildBlockedError, match="no published mart"):
        build_period(altered_source, policy_path=inputs["policy"],
                     rules_path=inputs["rules"], output_root=tmp_path / "mismatch-output")


def test_missing_source_workbook_fails_before_any_publication(approved_build_inputs):
    inputs = approved_build_inputs
    with pytest.raises(FileNotFoundError):
        build_period(inputs["source"].parent / "missing.xlsx", policy_path=inputs["policy"],
                     rules_path=inputs["rules"], output_root=inputs["output"])



def test_policy_alert_thresholds_drive_department_ledger(approved_build_inputs, tmp_path):
    inputs = approved_build_inputs
    policy = yaml.safe_load(inputs["policy"].read_text(encoding="utf-8"))
    policy["alerts"]["department_utilization"]["amber_percent"] = 0
    policy["alerts"]["department_utilization"]["red_percent"] = 100
    policy_path = tmp_path / "policy-custom-thresholds.yaml"
    policy_path.write_text(yaml.safe_dump(policy), encoding="utf-8")
    build_period(inputs["source"], policy_path=policy_path,
                 rules_path=inputs["rules"], output_root=tmp_path / "threshold-output")
    data = load_published_period(tmp_path / "threshold-output", "2026-01")
    assert data["department_ledger"].loc[0, "Policy Status"] == "AMBER"


def test_policy_quota_changes_are_used_by_reconciliation(approved_build_inputs, tmp_path):
    inputs = approved_build_inputs
    policy = yaml.safe_load(inputs["policy"].read_text(encoding="utf-8"))
    policy["pools"]["enterprise"]["quota_hours"] = 211201
    policy_path = tmp_path / "policy-custom-quota.yaml"
    policy_path.write_text(yaml.safe_dump(policy), encoding="utf-8")
    with pytest.raises(BuildBlockedError, match="quarantined"):
        build_period(inputs["source"], policy_path=policy_path,
                     rules_path=inputs["rules"], output_root=tmp_path / "quota-output")


def test_failure_does_not_replace_previous_published_period(approved_build_inputs, tmp_path):
    inputs = approved_build_inputs
    output = tmp_path / "same-output"
    first_manifest = build_period(inputs["source"], policy_path=inputs["policy"],
                                   rules_path=inputs["rules"], output_root=output)
    first_data = load_published_period(output, "2026-01")
    policy = yaml.safe_load(inputs["policy"].read_text(encoding="utf-8"))
    policy["pools"]["enterprise"]["quota_hours"] = 211201
    changed_policy = tmp_path / "changed-policy.yaml"
    changed_policy.write_text(yaml.safe_dump(policy), encoding="utf-8")
    with pytest.raises(BuildBlockedError):
        build_period(inputs["source"], policy_path=changed_policy,
                     rules_path=inputs["rules"], output_root=output)
    still_published = load_published_period(output, "2026-01")
    assert still_published["build_metadata"]["build_id"] == first_data["build_metadata"]["build_id"]
    assert first_manifest.exists()
