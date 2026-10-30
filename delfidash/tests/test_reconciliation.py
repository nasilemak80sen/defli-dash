import pandas as pd
import pytest

from src.analytics import reconcile_allocations
from src.reconciliation import ReconciliationBlocked, require_reconciliation_passed


def allocation_frame():
    return pd.DataFrame([
        {"Department": "DPE", "Quota (Hrs)": 100.0, "Consumed (Hrs)": 60.0,
         "Adjustment (Hrs)": -5.0, "Consumed (Hrs) Final": 55.0, "Balance (Hrs)": 45.0},
        {"Department": "DGS", "Quota (Hrs)": 100.0, "Consumed (Hrs)": 40.0,
         "Adjustment (Hrs)": 5.0, "Consumed (Hrs) Final": 45.0, "Balance (Hrs)": 55.0},
    ])


def test_allocation_reconciliation_passes_and_checks_arithmetic():
    usage = pd.DataFrame({"User": ["a", "b"], "Month": ["Jan'26", "Jan'26"],
                          "Hours per User": [60.0, 40.0], "Updated Department": ["DPE", "DGS"]})
    report = reconcile_allocations(allocation_frame(), usage, expected_enterprise_quota=200.0,
                                   expected_enterprise_consumption=100.0, tolerance=0.1)
    assert report["Status"].eq("PASS").all()


def test_allocation_reconciliation_detects_department_mismatch():
    usage = pd.DataFrame({"User": ["a"], "Month": ["Jan'26"], "Hours per User": [59.0], "Updated Department": ["DPE"]})
    report = reconcile_allocations(allocation_frame(), usage, expected_enterprise_quota=200.0, tolerance=0.1)
    mismatch = report[(report["Check"] == "Department usage tie-out") & (report["Scope"] == "DPE")]
    assert mismatch.iloc[0]["Status"] == "FAIL"


def test_publish_gate_rejects_failed_reconciliation():
    with pytest.raises(ReconciliationBlocked, match="publishing is blocked"):
        require_reconciliation_passed(pd.DataFrame([{"Status": "FAIL"}]))


def test_searah_is_not_added_to_enterprise_reconciliation():
    enterprise = pd.DataFrame({"User": ["a"], "Month": ["Jan'26"], "Hours per User": [100.0], "Updated Department": ["DPE"]})
    report = reconcile_allocations(allocation_frame(), enterprise, expected_enterprise_quota=200.0,
                                   expected_enterprise_consumption=100.0, tolerance=0.1)
    assert report.loc[report["Check"] == "Enterprise consumption control", "Actual"].iloc[0] == 100.0


def test_department_without_quota_is_marked_not_applicable_for_balance():
    allocation = allocation_frame()
    allocation.loc[len(allocation)] = ["Vestigo", float("nan"), 0.0, 0.0, 0.0, float("nan")]
    usage = pd.DataFrame({"User": ["a", "b"], "Month": ["Jan'26", "Jan'26"],
                          "Hours per User": [60.0, 40.0], "Updated Department": ["DPE", "DGS"]})
    report = reconcile_allocations(allocation, usage, expected_enterprise_quota=200.0, tolerance=0.1)
    vestigo = report[(report["Check"] == "Department balance arithmetic") & (report["Scope"] == "Vestigo")]
    assert vestigo.iloc[0]["Status"] == "NOT APPLICABLE"


def test_publish_gate_accepts_explicit_not_applicable_checks():
    require_reconciliation_passed(pd.DataFrame([{"Status": "PASS"}, {"Status": "NOT APPLICABLE"}]))


def test_usage_department_without_allocation_is_detected():
    usage = pd.DataFrame({"User": ["a", "x"], "Month": ["Jan'26", "Jan'26"],
                          "Hours per User": [60.0, 12.0], "Updated Department": ["DPE", "Unknown"]})
    report = reconcile_allocations(allocation_frame(), usage, expected_enterprise_quota=200.0, tolerance=0.1)
    unmatched = report[report["Check"] == "Unallocated department usage"]
    assert unmatched.iloc[0]["Status"] == "FAIL"
    assert unmatched.iloc[0]["Actual"] == 12.0


def test_publish_gate_fails_when_status_column_is_missing():
    with pytest.raises(ReconciliationBlocked, match="publishing is blocked"):
        require_reconciliation_passed(pd.DataFrame([{"Check": "no status"}]))
