"""Validated ingestion for the monthly DELFI utilisation workbook.

Raw workbooks are treated as source evidence: malformed sheets and invalid usage
rows fail loudly instead of being silently converted to empty or zero-valued data.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from openpyxl import load_workbook as load_xlsx_workbook

MONTHS = ["Jan'26", "Feb'26", "Mar'26", "Apr'26", "May'26", "Jun'26", "Jul'26", "Aug'26", "Sep'26"]
USAGE_REQUIRED_COLUMNS = (
    "User", "Unit", "Hours", "Hours per User", "Updated Department",
    "Updated Billing Dept", "Month",
)

# Some workbook versions contain a trailing blank in the Searah fact-sheet name.
SHEET_ALIASES = {
    "sim": ("Data_sim hrs",),
    "searah": ("Data_sim hrs_SEARAH", "Data_sim hrs_SEARAH "),
    "vm": ("VM daily_data",),
    "profiles": ("Data_profiles",),
    "top": ("top 220 data",),
    "rejected": ("rejected users data",),
    "users": ("User List",),
    "allocation_raw": ("monthly sim hrs",),
    "searah_allocation_raw": ("monthly sim hrs_SEARAH",),
}

# The two pivot summaries are formatted Excel pivots with merged headings. The
# current workbook layout is represented explicitly here and validated before use.
PIVOT_LAYOUT = {
    "header_row": 4,
    "user_start_col": 0,
    "user_end_col": 13,
    "allocation_start_col": 16,
    "allocation_end_col": 23,
    "enterprise_value_columns": {
        "Quota (Hrs)": 17,
        "Consumed (Hrs)": 18,
        "Adjustment (Hrs)": 19,
        "Consumed (Hrs) Final": 20,
        "Balance (Hrs)": 21,
    },
    "searah_value_columns": {"Quota (Hrs)": 21, "Consumed (Hrs)": 22},
}


class WorkbookLoadError(ValueError):
    """Base exception for workbook parsing and schema failures."""


class WorkbookSchemaError(WorkbookLoadError):
    """Raised when a required sheet or column is missing or ambiguous."""


class WorkbookDataError(WorkbookLoadError):
    """Raised when source rows violate the declared data contract."""


def _normalise_name(value: Any) -> str:
    return " ".join(str(value).replace("\u00a0", " ").split()).casefold()


def _resolve_sheet(sheet_names: list[str], aliases: tuple[str, ...], *, required: bool) -> str | None:
    wanted = {_normalise_name(name) for name in aliases}
    matches = [name for name in sheet_names if _normalise_name(name) in wanted]
    if len(matches) > 1:
        raise WorkbookSchemaError(f"Ambiguous worksheet aliases {aliases!r}: found {matches!r}.")
    if not matches:
        if required:
            raise WorkbookSchemaError(f"Missing required worksheet. Expected one of: {aliases!r}.")
        return None
    return matches[0]


def _read_sheet(workbook: Any, sheet: str, *, header: int | None = 0) -> pd.DataFrame:
    """Read a worksheet without deprecated ExcelFile.parse calls.

    Values are read from the cached workbook results, matching pandas/openpyxl's
    data_only behaviour. Blank trailing rows are discarded; the source cells are
    never changed.
    """
    try:
        worksheet = workbook[sheet]
        rows = [list(row) for row in worksheet.iter_rows(values_only=True)]
        if header is None:
            return pd.DataFrame(rows)
        if not rows or header >= len(rows):
            return pd.DataFrame()
        headers = rows[header]
        width = len(headers)
        names = []
        seen: dict[str, int] = {}
        for index, value in enumerate(headers):
            name = str(value).strip() if value is not None and str(value).strip() else f"Unnamed: {index}"
            count = seen.get(name, 0)
            seen[name] = count + 1
            names.append(name if count == 0 else f"{name}.{count}")
        records = []
        for row in rows[header + 1:]:
            values = (row + [None] * width)[:width]
            if any(value is not None for value in values):
                records.append(values)
        return pd.DataFrame(records, columns=names)
    except Exception as exc:  # preserve context; do not turn corrupt sheets into empty frames
        raise WorkbookLoadError(f"Failed reading worksheet {sheet!r}: {exc}") from exc


def _clean_text(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.replace("\u00a0", " ", regex=False).str.strip()
    return values.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "<NA>": pd.NA})


def _coerce_numeric_strict(frame: pd.DataFrame, column: str, sheet: str) -> None:
    original = frame[column]
    converted = pd.to_numeric(original, errors="coerce")
    invalid = original.notna() & converted.isna()
    if invalid.any():
        rows = (frame.index[invalid] + 2).tolist()[:10]
        raise WorkbookDataError(
            f"Worksheet {sheet!r}: column {column!r} contains non-numeric values at Excel rows {rows}."
        )
    non_finite = converted.notna() & ~np.isfinite(converted.fillna(0).astype(float))
    if non_finite.any():
        rows = (frame.index[non_finite] + 2).tolist()[:10]
        raise WorkbookDataError(
            f"Worksheet {sheet!r}: column {column!r} contains non-finite values at Excel rows {rows}."
        )
    frame[column] = converted


def _parse_month(value: Any) -> str | None:
    if pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp,)):
        parsed = value
    else:
        text = str(value).strip()
        parsed = pd.NaT
        for fmt in ("%b'%y", "%b-%y", "%b %Y", "%Y-%m", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                parsed = pd.to_datetime(text, format=fmt, errors="raise")
                break
            except (ValueError, TypeError):
                continue
        if pd.isna(parsed):
            parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.strftime("%b'%y")


def _prepare_usage(frame: pd.DataFrame, sheet: str) -> pd.DataFrame:
    missing = [column for column in USAGE_REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise WorkbookSchemaError(f"Worksheet {sheet!r} is missing required columns: {missing}.")

    data = frame.copy()
    for column in ("User", "Unit", "Updated Department", "Updated Billing Dept"):
        data[column] = _clean_text(data[column])
    # Fact sheets also contain quota/helper rows. Only rows with a user are usage facts.
    data = data.loc[data["User"].notna()].copy()
    for column in ("Hours", "Hours per User"):
        _coerce_numeric_strict(data, column, sheet)
        bad = data[column].isna()
        if bad.any():
            rows = (data.index[bad] + 2).tolist()[:10]
            raise WorkbookDataError(
                f"Worksheet {sheet!r}: usage rows have missing {column!r} values at Excel rows {rows}."
            )
        if (data[column] < 0).any():
            rows = (data.index[data[column] < 0] + 2).tolist()[:10]
            raise WorkbookDataError(
                f"Worksheet {sheet!r}: negative {column!r} values at Excel rows {rows}."
            )

    missing_unit = data["Unit"].isna()
    missing_month = data["Month"].isna()
    if missing_unit.any() or missing_month.any():
        rows = (data.index[missing_unit | missing_month] + 2).tolist()[:10]
        raise WorkbookDataError(
            f"Worksheet {sheet!r}: usage rows require Unit and Month; invalid Excel rows {rows}."
        )
    parsed_months = data["Month"].map(_parse_month)
    invalid_month = parsed_months.isna()
    if invalid_month.any():
        rows = (data.index[invalid_month] + 2).tolist()[:10]
        values = data.loc[invalid_month, "Month"].astype(str).head(5).tolist()
        raise WorkbookDataError(
            f"Worksheet {sheet!r}: unrecognised reporting month values {values!r} at Excel rows {rows}."
        )
    data["Month"] = parsed_months.astype("string")
    return data.reset_index(drop=True)


def _parse_optional_sheet(workbook: Any, sheet_names: list[str], key: str,
                          *, header: int | None = 0) -> tuple[pd.DataFrame, str | None]:
    sheet = _resolve_sheet(sheet_names, SHEET_ALIASES[key], required=False)
    if sheet is None:
        return pd.DataFrame(), None
    return _read_sheet(workbook, sheet, header=header), sheet


def _parse_monthly_pivot(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    layout = PIVOT_LAYOUT
    required_rows = layout["header_row"] + 1
    if len(raw) < required_rows or raw.shape[1] < layout["allocation_end_col"]:
        raise WorkbookSchemaError(
            "Worksheet 'monthly sim hrs' does not match the expected pivot layout "
            f"(at least {required_rows} rows and {layout['allocation_end_col']} columns required; "
            f"found {len(raw)} rows and {raw.shape[1]} columns)."
        )

    user_block = raw.iloc[layout["header_row"]:, layout["user_start_col"]:layout["user_end_col"]].copy()
    user_cols = ["Updated Department", "Updated Billing Dept", "User", *MONTHS, "2026 capped"]
    if user_block.shape[1] != len(user_cols):
        raise WorkbookSchemaError("User/month pivot width changed; review the workbook layout contract.")
    user_block.columns = user_cols
    user_labels = user_block["User"].astype("string").str.strip()
    user_monthly = user_block.loc[user_labels.notna() & ~user_labels.str.casefold().isin({"total", "grand total", "enterprise (total)"})].copy()
    for column in MONTHS + ["2026 capped"]:
        _coerce_numeric_strict(user_monthly, column, "monthly sim hrs (user pivot)")

    allocation_block = raw.iloc[layout["header_row"]:, layout["allocation_start_col"]:layout["allocation_end_col"]].copy()
    allocation_cols = ["Department", "Quota (Hrs)", "Consumed (Hrs)", "Adjustment (Hrs)",
                       "Consumed (Hrs) Final", "Balance (Hrs)", "Remarks"]
    if allocation_block.shape[1] != len(allocation_cols):
        raise WorkbookSchemaError("Department allocation pivot width changed; review the workbook layout contract.")
    allocation_block.columns = allocation_cols
    department_labels = allocation_block["Department"].astype("string").str.strip()
    aggregate_labels = {"total", "grand total", "enterprise (total)"}
    keep_rows = department_labels.notna() & department_labels.ne("") & ~department_labels.str.casefold().isin(aggregate_labels)
    allocation_block = allocation_block.loc[keep_rows].copy()
    for column in allocation_cols[1:-1]:
        _coerce_numeric_strict(allocation_block, column, "monthly sim hrs (department allocation)")
    allocation = allocation_block.reset_index(drop=True)

    enterprise: dict[str, Any] = {}
    for _, row in raw.iloc[layout["header_row"]:].iterrows():
        values = row.tolist()
        if any(isinstance(value, str) and "Enterprise (Total)" in value for value in values):
            enterprise = {
                name: values[index] if len(values) > index else None
                for name, index in layout["enterprise_value_columns"].items()
            }
            break
    return user_monthly.reset_index(drop=True), allocation, enterprise


def _parse_searah_summary(raw: pd.DataFrame) -> dict[str, Any]:
    layout = PIVOT_LAYOUT["searah_value_columns"]
    required_width = max(layout.values()) + 1
    if raw.shape[1] < required_width:
        raise WorkbookSchemaError(
            "Worksheet 'monthly sim hrs_SEARAH' does not match the expected summary layout "
            f"(at least {required_width} columns required; found {raw.shape[1]})."
        )
    for _, row in raw.iterrows():
        values = row.tolist()
        if any(isinstance(value, str) and value.strip().casefold() == "searah" for value in values):
            return {name: values[index] if len(values) > index else None for name, index in layout.items()}
    return {}


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...], sheet: str) -> None:
    if frame.empty:
        return
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise WorkbookSchemaError(f"Worksheet {sheet!r} is missing required columns: {missing}.")


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_workbook(path: str | Path) -> dict[str, Any]:
    """Load and validate the DELFI workbook, returning explicit source metadata.

    Enterprise and Searah facts remain separate. Optional supporting sheets are
    reported as missing rather than treated as indistinguishable empty datasets.
    """
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Workbook not found: {source}")
    try:
        workbook = load_xlsx_workbook(source, read_only=True, data_only=True)
    except Exception as exc:
        raise WorkbookLoadError(f"Could not open Excel workbook {source.name!r}: {exc}") from exc

    try:
        sim_sheet = _resolve_sheet(workbook.sheetnames, SHEET_ALIASES["sim"], required=True)
        sim_raw = _read_sheet(workbook, sim_sheet)
        sim = _prepare_usage(sim_raw, sim_sheet)
        duplicate_enterprise_rows = int(sim.duplicated(keep=False).sum())

        searah_sheet = _resolve_sheet(workbook.sheet_names, SHEET_ALIASES["searah"], required=False)
        if searah_sheet:
            searah = _prepare_usage(_read_sheet(workbook, searah_sheet), searah_sheet)
        else:
            searah = pd.DataFrame(columns=USAGE_REQUIRED_COLUMNS)

        loaded: dict[str, pd.DataFrame] = {}
        missing_optional: list[str] = []
        if searah_sheet is None:
            missing_optional.append("searah")
        for key in ("vm", "profiles", "top", "rejected", "users"):
            frame, sheet = _parse_optional_sheet(workbook, workbook.sheet_names, key)
            loaded[key] = frame
            if sheet is None:
                missing_optional.append(key)

        vm = loaded["vm"]
        _require_columns(vm, ("Date", "User", "Department_"), "VM daily_data")
        if not vm.empty:
            if "Date" in vm.columns:
                vm["Date"] = pd.to_datetime(vm["Date"], errors="coerce")
            for column in ("User", "Department", "Department_", "Billing Department"):
                if column in vm:
                    vm[column] = _clean_text(vm[column])
            # F7 in the source proposal: duration values are unreliable. Do not
            # coerce, aggregate or publish them until the source query is validated.
            if "Active Unique Users" in vm:
                _coerce_numeric_strict(vm, "Active Unique Users", "VM daily_data")

        profiles = loaded["profiles"]
        _require_columns(profiles, ("Date", "Profile", "User"), "Data_profiles")
        if not profiles.empty:
            if "Date" in profiles.columns:
                profiles["Date"] = pd.to_datetime(profiles["Date"], errors="coerce")
            for column in ("Profile", "User", "Updated Department", "Updated Billing Dept"):
                if column in profiles:
                    profiles[column] = _clean_text(profiles[column])
            if "Count of Merged" in profiles:
                _coerce_numeric_strict(profiles, "Count of Merged", "Data_profiles")

        top = loaded["top"]
        if not top.empty:
            if "Date" in top.columns:
                top["Date"] = pd.to_datetime(top["Date"], errors="coerce")
            for column in ("User", "Department_", "Billing Department"):
                if column in top:
                    top[column] = _clean_text(top[column])
            # Top-220 duration is explicitly excluded: it is not a reliable measure.

        rejected = loaded["rejected"]
        _require_columns(rejected, ("User", "Department_", "count"), "rejected users data")
        if not rejected.empty:
            for column in ("User", "Department_", "Billing Department"):
                if column in rejected:
                    rejected[column] = _clean_text(rejected[column])
            if "count" in rejected:
                _coerce_numeric_strict(rejected, "count", "rejected users data")

        users = loaded["users"]
        _require_columns(users, ("Email Address",), "User List")
        if not users.empty and "Email Address" in users.columns:
            users["Email Address"] = _clean_text(users["Email Address"])
            users = users.dropna(subset=["Email Address"])

        allocation_sheet = _resolve_sheet(workbook.sheet_names, SHEET_ALIASES["allocation_raw"], required=False)
        if allocation_sheet:
            alloc_raw = _read_sheet(workbook, allocation_sheet, header=None)
            user_monthly, allocation, enterprise = _parse_monthly_pivot(alloc_raw)
        else:
            user_monthly, allocation, enterprise = pd.DataFrame(), pd.DataFrame(), {}
            missing_optional.append("allocation_raw")

        searah_allocation_sheet = _resolve_sheet(
            workbook.sheet_names, SHEET_ALIASES["searah_allocation_raw"], required=False
        )
        if searah_allocation_sheet:
            searah_raw = _read_sheet(workbook, searah_allocation_sheet, header=None)
            searah_summary = _parse_searah_summary(searah_raw)
        else:
            searah_summary = {}
            missing_optional.append("searah_allocation_raw")

        return {
            "sim": sim,
            "searah": searah,
            "vm": vm,
            "profiles": profiles,
            "top": top,
            "rejected": rejected,
            "users": users,
            "allocation": allocation,
            "user_monthly": user_monthly,
            "enterprise": enterprise,
            "searah_summary": searah_summary,
            "source_file": source.name,
            "source_sha256": _sha256(source),
            "missing_optional_sheets": sorted(set(missing_optional)),
            "duplicate_enterprise_rows": duplicate_enterprise_rows,
            "duplicate_searah_rows": int(searah.duplicated(keep=False).sum()) if not searah.empty else 0,
            "sheet_names": list(workbook.sheet_names),
        }
    finally:
        workbook.close()
