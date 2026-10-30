import pandas as pd

from src.analytics import department_vm, vm_monthly


def test_vm_monthly_does_not_aggregate_unreliable_duration_field():
    vm = pd.DataFrame({
        "Date": pd.to_datetime(["2026-01-01", "2026-01-01", "2026-02-01"]),
        "User": ["a", "b", "a"],
        "Department_": ["DPE", "DPE", "DGS"],
        "Sum of Duration Hours": [15798.0, 3765.0, 999999.0],
    })
    result = vm_monthly(vm)
    assert result.columns.tolist() == ["Month", "Active Users"]
    assert result["Active Users"].tolist() == [2, 1]


def test_vm_department_activity_uses_distinct_users_not_duration():
    vm = pd.DataFrame({
        "Date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
        "User": ["a", "a", "b"],
        "Department_": ["DPE", "DPE", "DGS"],
        "Sum of Duration Hours": [15798.0, 1.0, 50000.0],
    })
    result = department_vm(vm)
    assert result.columns.tolist() == ["Department", "Active Users"]
    assert result.sort_values("Department").to_dict("records") == [
        {"Department": "DGS", "Active Users": 1},
        {"Department": "DPE", "Active Users": 1},
    ]
