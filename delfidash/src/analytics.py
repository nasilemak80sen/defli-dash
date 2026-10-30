"""Pure analytical functions for DELFI utilisation facts and ledgers."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

USAGE_COLUMNS = ("User", "Month", "Hours per User")


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...], dataset: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{dataset} is missing required columns: {missing}.")


def _month_key(value: Any) -> datetime:
    parsed = pd.to_datetime(str(value), format="%b'%y", errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Unrecognised reporting month {value!r}; expected labels such as Sep'26.")
    return parsed.to_pydatetime()


def _normalised_usage(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, USAGE_COLUMNS, "Simulation usage")
    data = frame.copy()
    if data.empty:
        return data
    data["Hours per User"] = pd.to_numeric(data["Hours per User"], errors="coerce")
    values = data["Hours per User"].to_numpy(dtype=float, na_value=float("nan"))
    if not np.isfinite(values).all():
        raise ValueError("Simulation usage contains missing, non-numeric or non-finite normalised hours.")
    if (data["Hours per User"] < 0).any():
        raise ValueError("Simulation usage contains negative normalised hours.")
    data["Month"] = data["Month"].astype("string").str.strip()
    data["_month_sort"] = data["Month"].map(_month_key)
    return data


def monthly_simulation(sim: pd.DataFrame) -> pd.DataFrame:
    """Aggregate one pool's normalised hours by reporting month.

    Searah must be passed separately. This function intentionally accepts a
    single fact frame so the dedicated pool cannot be silently mixed into Enterprise.
    Unexpected but valid months are retained and sorted chronologically.
    """
    if sim.empty:
        return pd.DataFrame(columns=["Month", "Hours"])
    data = _normalised_usage(sim)
    out = data.groupby(["_month_sort", "Month"], as_index=False, observed=True)["Hours per User"].sum()
    return out.sort_values("_month_sort").drop(columns="_month_sort").rename(columns={"Hours per User": "Hours"}).reset_index(drop=True)


def department_simulation(sim: pd.DataFrame) -> pd.DataFrame:
    """Aggregate one pool by its department-at-time-of-use label."""
    if sim.empty:
        return pd.DataFrame(columns=["Department", "Hours"])
    data = _normalised_usage(sim)
    dept_col = "Updated Department" if "Updated Department" in data.columns else "Department"
    _require_columns(data, (dept_col,), "Simulation usage")
    data[dept_col] = data[dept_col].astype("string").fillna("Unknown").str.strip()
    result = data.groupby(dept_col, dropna=False)["Hours per User"].sum().reset_index(name="Hours")
    return result.rename(columns={dept_col: "Department"}).sort_values("Hours", ascending=False).reset_index(drop=True)


def user_simulation(sim: pd.DataFrame) -> pd.DataFrame:
    """Aggregate one pool by user identity as recorded in the source workbook."""
    if sim.empty:
        return pd.DataFrame(columns=["User", "Hours"])
    data = _normalised_usage(sim)
    return (data.groupby("User", dropna=False)["Hours per User"].sum()
            .reset_index(name="Hours").sort_values("Hours", ascending=False).reset_index(drop=True))


def pool_summary(enterprise: pd.DataFrame, searah: pd.DataFrame,
                 enterprise_quota: float | None = None,
                 searah_quota: float | None = None) -> pd.DataFrame:
    """Return separate pool balances; never aggregate dedicated Searah into Enterprise."""
    rows = []
    for name, frame, quota in (
        ("Enterprise", enterprise, enterprise_quota),
        ("Searah", searah, searah_quota),
    ):
        used = float(_normalised_usage(frame)["Hours per User"].sum()) if not frame.empty else 0.0
        quota_value = None if quota is None or pd.isna(quota) else float(quota)
        if quota_value is not None and quota_value <= 0:
            raise ValueError(f"{name} quota must be positive when provided.")
        rows.append({"Pool": name, "Quota (Hrs)": quota_value, "Consumed (Hrs)": used,
                     "Balance (Hrs)": None if quota_value is None else quota_value - used,
                     "Utilisation (%)": None if quota_value is None else used / quota_value * 100.0})
    return pd.DataFrame(rows)


def _canonical_department(value: Any) -> str:
    return " ".join(str(value).replace("\u00a0", " ").replace("‑", "-").replace("–", "-").split()).casefold()


def reconcile_allocations(allocation: pd.DataFrame, enterprise_usage: pd.DataFrame,
                          expected_enterprise_quota: float = 211_200.0,
                          expected_enterprise_consumption: float | None = None,
                          tolerance: float = 0.1) -> pd.DataFrame:
    """Reconcile source allocation pivots to Enterprise fact rows and arithmetic.

    The comparison uses the source 'Consumed (Hrs)' column, not adjusted final
    consumption. Searah facts are intentionally not accepted by this function.
    """
    required = ("Department", "Quota (Hrs)", "Consumed (Hrs)", "Adjustment (Hrs)",
                "Consumed (Hrs) Final", "Balance (Hrs)")
    _require_columns(allocation, required, "Department allocation")
    rows: list[dict[str, Any]] = []

    def add(check: str, scope: str, expected: float | None, actual: float | None,
            detail: str = "") -> None:
        diff = None if expected is None or actual is None else float(actual) - float(expected)
        passed = diff is not None and abs(diff) <= tolerance
        rows.append({"Check": check, "Scope": scope, "Expected": expected, "Actual": actual,
                     "Difference": diff, "Status": "PASS" if passed else "FAIL", "Detail": detail})

    numeric = allocation.copy()
    for column in required[1:]:
        numeric[column] = pd.to_numeric(numeric[column], errors="coerce")
    mandatory_values = ("Consumed (Hrs)", "Adjustment (Hrs)", "Consumed (Hrs) Final")
    if numeric[list(mandatory_values)].isna().any().any():
        raise ValueError("Allocation table contains missing or non-numeric consumption/adjustment values.")
    quota_values = numeric["Quota (Hrs)"].dropna()
    add("Enterprise quota control", "Enterprise", expected_enterprise_quota,
        float(quota_values.sum()), "Department quotas must sum to the enterprise entitlement; no-quota departments are excluded.")

    usage_by_dept = department_simulation(enterprise_usage)
    usage_map = {_canonical_department(row.Department): float(row.Hours)
                 for row in usage_by_dept.itertuples(index=False)}
    allocation_departments = {_canonical_department(value) for value in numeric["Department"].dropna()}
    for missing_department in sorted(set(usage_map) - allocation_departments):
        add("Unallocated department usage", missing_department, 0.0, usage_map[missing_department],
            "Enterprise usage exists for a department absent from the allocation table.")
    for _, row in numeric.iterrows():
        dept = str(row["Department"])
        consumed = float(row["Consumed (Hrs)"])
        adjustment = float(row["Adjustment (Hrs)"])
        consumed_final = float(row["Consumed (Hrs) Final"])
        quota = float(row["Quota (Hrs)"])
        balance = float(row["Balance (Hrs)"])
        actual = usage_map.get(_canonical_department(dept), 0.0)
        add("Department usage tie-out", dept, consumed, actual,
            "Raw Enterprise fact usage versus source allocation pivot; Searah excluded.")
        add("Adjusted consumption arithmetic", dept, consumed + adjustment,
            consumed_final, "Consumed plus net adjustment equals final consumed.")
        if pd.isna(row["Quota (Hrs)"]):
            rows.append({"Check": "Department balance arithmetic", "Scope": dept, "Expected": None,
                         "Actual": None, "Difference": None, "Status": "NOT APPLICABLE",
                         "Detail": "No department quota is recorded for this department."})
        elif pd.isna(row["Balance (Hrs)"]):
            rows.append({"Check": "Department balance arithmetic", "Scope": dept, "Expected": quota - consumed_final,
                         "Actual": None, "Difference": None, "Status": "NOT AVAILABLE",
                         "Detail": "A quota exists but the source balance is missing."})
        else:
            add("Department balance arithmetic", dept, quota - consumed_final,
                balance, "Quota minus adjusted final consumption equals balance.")

    if expected_enterprise_consumption is not None:
        actual_total = float(_normalised_usage(enterprise_usage)["Hours per User"].sum())
        add("Enterprise consumption control", "Enterprise", expected_enterprise_consumption,
            actual_total, "Searah dedicated-pool usage is excluded.")
    return pd.DataFrame(rows)


def vm_monthly(vm: pd.DataFrame) -> pd.DataFrame:
    """Return VM distinct-user activity by month, not duration-hour totals.

    The supplied workbook's duration field is known to be unreliable and must not
    be interpreted as session time or summed for utilisation reporting.
    """
    if vm.empty or "Date" not in vm.columns or "User" not in vm.columns:
        return pd.DataFrame(columns=["Month", "Active Users"])
    data = vm.copy()
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["Date"])
    data["Month"] = data["Date"].dt.to_period("M").dt.to_timestamp()
    return data.groupby("Month").agg(**{"Active Users": ("User", "nunique")}).reset_index()


def profile_summary(profiles: pd.DataFrame) -> pd.DataFrame:
    """Summarise observed profile activity; this is not purchased licence inventory."""
    if profiles.empty:
        return pd.DataFrame(columns=["Profile", "Events", "Users"])
    _require_columns(profiles, ("Profile", "User"), "Profile activity")
    return (profiles.groupby("Profile", dropna=False)
            .agg(Events=("User", "size"), Users=("User", "nunique"))
            .reset_index().sort_values("Events", ascending=False).reset_index(drop=True))


def department_vm(vm: pd.DataFrame) -> pd.DataFrame:
    """Summarise VM activity by department using distinct users, not durations."""
    if vm.empty:
        return pd.DataFrame(columns=["Department", "Active Users"])
    dept_col = "Department_" if "Department_" in vm.columns else "Department"
    _require_columns(vm, (dept_col, "User"), "VM activity")
    return (vm.groupby(dept_col, dropna=False).agg(**{"Active Users": ("User", "nunique")})
            .reset_index().rename(columns={dept_col: "Department"})
            .sort_values("Active Users", ascending=False).reset_index(drop=True))


def data_quality(data: dict) -> list[dict]:
    """Summarise loaded datasets and explicitly disclose optional missing sheets."""
    output = []
    for key, label in (("sim", "Enterprise simulation detail"), ("searah", "Searah simulation detail"),
                       ("vm", "VM daily activity"), ("profiles", "Profile activity"),
                       ("rejected", "Rejected sessions")):
        frame = data.get(key, pd.DataFrame())
        output.append({"Dataset": label, "Rows": len(frame),
                       "Status": "Loaded" if len(frame) else "Missing / empty"})
    duplicates = int(data.get("duplicate_enterprise_rows", 0)) + int(data.get("duplicate_searah_rows", 0))
    output.append({"Dataset": "Potential duplicate usage rows", "Rows": duplicates,
                   "Status": "Review required" if duplicates else "None detected"})
    output.append({"Dataset": "Source SHA-256", "Rows": 1,
                   "Status": data.get("source_sha256", "Not available")})
    missing = data.get("missing_optional_sheets", [])
    output.append({"Dataset": "Optional worksheets", "Rows": len(missing),
                   "Status": "All present" if not missing else "Missing: " + ", ".join(missing)})
    output.append({"Dataset": "VM duration reliability", "Rows": 0,
                   "Status": "Not usable; excluded from aggregates pending source-query validation"})
    return output
