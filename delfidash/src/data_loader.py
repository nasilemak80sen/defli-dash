from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np

MONTHS = ["Jan'26", "Feb'26", "Mar'26", "Apr'26", "May'26", "Jun'26", "Jul'26", "Aug'26", "Sep'26"]

def _read(path: Path, sheet: str, **kwargs) -> pd.DataFrame:
    try:
        return pd.read_excel(path, sheet_name=sheet, **kwargs)
    except Exception:
        return pd.DataFrame()

def _clean_text(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip().replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})

def load_workbook(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Workbook not found: {path}")

    sim = _read(path, "Data_sim hrs")
    if not sim.empty:
        for c in ["User", "Unit", "Updated Department", "Updated Billing Dept", "Month"]:
            if c in sim: sim[c] = _clean_text(sim[c])
        for c in ["Hours", "Hours per User"]:
            if c in sim: sim[c] = pd.to_numeric(sim[c], errors="coerce")
        sim["Month"] = pd.Categorical(sim["Month"], categories=MONTHS, ordered=True)
        sim["Hours per User"] = sim["Hours per User"].fillna(0)
        sim["Hours"] = sim["Hours"].fillna(0)

    searah = _read(path, "Data_sim hrs_SEARAH ")
    if not searah.empty:
        for c in ["User", "Unit", "Updated Department", "Updated Billing Dept", "Month"]:
            if c in searah: searah[c] = _clean_text(searah[c])
        for c in ["Hours", "Hours per User"]:
            if c in searah: searah[c] = pd.to_numeric(searah[c], errors="coerce")
        searah["Month"] = pd.Categorical(searah["Month"], categories=MONTHS, ordered=True)
        searah["Hours per User"] = searah["Hours per User"].fillna(0)
        searah["Hours"] = searah["Hours"].fillna(0)

    vm = _read(path, "VM daily_data")
    if not vm.empty:
        vm["Date"] = pd.to_datetime(vm.get("Date"), errors="coerce")
        for c in ["User", "Department", "Department_", "Billing Department"]:
            if c in vm: vm[c] = _clean_text(vm[c])
        for c in ["Sum of Duration Hours", "Active Unique Users"]:
            if c in vm: vm[c] = pd.to_numeric(vm[c], errors="coerce").fillna(0)
        vm = vm.dropna(subset=["Date"])

    profiles = _read(path, "Data_profiles")
    if not profiles.empty:
        profiles["Date"] = pd.to_datetime(profiles.get("Date"), errors="coerce")
        for c in ["Profile", "User", "Updated Department", "Updated Billing Dept"]:
            if c in profiles: profiles[c] = _clean_text(profiles[c])
        if "Count of Merged" in profiles:
            profiles["Count of Merged"] = pd.to_numeric(profiles["Count of Merged"], errors="coerce").fillna(0)

    top = _read(path, "top 220 data")
    if not top.empty:
        top["Date"] = pd.to_datetime(top.get("Date"), errors="coerce")
        for c in ["User", "Department_", "Billing Department"]:
            if c in top: top[c] = _clean_text(top[c])
        if "Total Dur. Hours" in top:
            top["Total Dur. Hours"] = pd.to_numeric(top["Total Dur. Hours"], errors="coerce").fillna(0)

    rejected = _read(path, "rejected users data")
    if not rejected.empty:
        # The source sheet has a known header/data alignment issue in its date-related fields.
        for c in ["User", "Department_", "Billing Department"]:
            if c in rejected: rejected[c] = _clean_text(rejected[c])
        if "count" in rejected:
            rejected["count"] = pd.to_numeric(rejected["count"], errors="coerce").fillna(0)

    user_list = _read(path, "User List")
    if not user_list.empty and "Email Address" in user_list:
        user_list["Email Address"] = _clean_text(user_list["Email Address"])
        user_list = user_list.dropna(subset=["Email Address"])

    # The monthly simulation sheet contains two side-by-side pivot tables.
    # Parse the user/month matrix and the department allocation summary separately.
    alloc_raw = _read(path, "monthly sim hrs", header=None)
    allocation = pd.DataFrame()
    user_monthly = pd.DataFrame()
    if len(alloc_raw) > 4:
        user_cols = ["Updated Department", "Updated Billing Dept", "User", *MONTHS, "2026 capped"]
        user_block = alloc_raw.iloc[4:, 0:13].copy()
        user_block.columns = user_cols
        user_monthly = user_block[user_block["User"].notna()].copy()
        for c in MONTHS + ["2026 capped"]:
            user_monthly[c] = pd.to_numeric(user_monthly[c], errors="coerce")

        dept_cols = ["Department", "Quota (Hrs)", "Consumed (Hrs)", "Adjustment (Hrs)",
                     "Consumed (Hrs) Final", "Balance (Hrs)", "Remarks"]
        dept_block = alloc_raw.iloc[4:, 16:23].copy()
        dept_block.columns = dept_cols
        dept_block = dept_block[dept_block["Department"].notna()].copy()
        for c in dept_cols[1:-1]:
            dept_block[c] = pd.to_numeric(dept_block[c], errors="coerce")
        allocation = dept_block.reset_index(drop=True)

    # Enterprise-level quota is a separate summary row in the allocation table.
    enterprise = {}
    if len(alloc_raw) > 4:
        # Enterprise summary label sits in column Q, not in the department field.
        for _, raw_row in alloc_raw.iloc[4:].iterrows():
            values = raw_row.tolist()
            if any(isinstance(v, str) and "Enterprise (Total)" in v for v in values):
                enterprise = {
                    "Quota (Hrs)": values[17] if len(values) > 17 else None,
                    "Consumed (Hrs)": values[18] if len(values) > 18 else None,
                    "Adjustment (Hrs)": values[19] if len(values) > 19 else None,
                    "Consumed (Hrs) Final": values[20] if len(values) > 20 else None,
                    "Balance (Hrs)": values[21] if len(values) > 21 else None,
                }
                break

    # Dedicated Searah allocation is maintained separately from the enterprise package.
    searah_raw = _read(path, "monthly sim hrs_SEARAH", header=None)
    searah_summary = {}
    if len(searah_raw) > 4:
        for _, raw_row in searah_raw.iloc[4:].iterrows():
            values = raw_row.tolist()
            if any(isinstance(v, str) and v.strip().lower() == "searah" for v in values):
                # Summary fields are in columns V and W in this workbook.
                searah_summary = {
                    "Quota (Hrs)": values[21] if len(values) > 21 else None,
                    "Consumed (Hrs)": values[22] if len(values) > 22 else None,
                }
                break

    return {
        "sim": sim, "searah": searah, "vm": vm, "profiles": profiles,
        "top": top, "rejected": rejected, "users": user_list,
        "allocation": allocation, "user_monthly": user_monthly,
        "enterprise": enterprise, "searah_summary": searah_summary,
        "source_file": path.name,
    }
