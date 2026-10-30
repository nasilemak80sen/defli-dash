from pathlib import Path

import pandas as pd
import pytest

from src.data_loader import WorkbookDataError, WorkbookSchemaError, load_workbook

USAGE_COLUMNS = {
    "User": ["user-a"], "Unit": ["hour"], "Hours": [10.0], "Hours per User": [10.0],
    "Updated Department": ["DPE"], "Updated Billing Dept": ["PE-RE"], "Month": ["Jan'26"],
}


def create_workbook(path: Path, *, usage: pd.DataFrame | None = None, include_allocation: bool = True,
                    searah: bool = False, include_required: bool = True):
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        if not include_required and not searah and not include_allocation:
            pd.DataFrame({"note": ["placeholder"]}).to_excel(writer, sheet_name="SUMMARY", index=False)
        if include_required:
            (usage if usage is not None else pd.DataFrame(USAGE_COLUMNS)).to_excel(
                writer, sheet_name="Data_sim hrs", index=False
            )
        if searah:
            pd.DataFrame(USAGE_COLUMNS).to_excel(writer, sheet_name="Data_sim hrs_SEARAH ", index=False)
            searah_pivot = pd.DataFrame([[None] * 23 for _ in range(5)])
            searah_pivot.iloc[0, 22] = "layout-marker"
            searah_pivot.iloc[4, 0] = "Searah"
            searah_pivot.iloc[4, 21] = 15000
            searah_pivot.iloc[4, 22] = 100
            searah_pivot.to_excel(writer, sheet_name="monthly sim hrs_SEARAH", header=False, index=False)
        if include_allocation:
            pivot = pd.DataFrame([[None] * 23 for _ in range(6)])
            pivot.iloc[0, 22] = "layout-marker"
            pivot.iloc[4, 0:13] = ["DPE", "PE-RE", "user-a", 10, None, None, None, None, None, None, None, None, 10]
            pivot.iloc[4, 16:23] = ["DPE", 100, 10, 0, 10, 90, None]
            pivot.iloc[5, 16:23] = ["Enterprise (Total)", 100, 10, 0, 10, 90, None]
            pivot.to_excel(writer, sheet_name="monthly sim hrs", header=False, index=False)


def test_load_workbook_records_hash_and_reports_missing_optional_sheets(tmp_path):
    path = tmp_path / "delfi.xlsx"
    create_workbook(path, include_allocation=False)
    result = load_workbook(path)
    assert len(result["sim"]) == 1
    assert len(result["source_sha256"]) == 64
    assert "searah" in result["missing_optional_sheets"]
    assert "allocation_raw" in result["missing_optional_sheets"]


def test_load_workbook_fails_when_required_usage_columns_are_missing(tmp_path):
    path = tmp_path / "missing-column.xlsx"
    create_workbook(path, usage=pd.DataFrame({"User": ["user-a"], "Hours": [10]}), include_allocation=False)
    with pytest.raises(WorkbookSchemaError, match="missing required columns"):
        load_workbook(path)


def test_load_workbook_fails_on_non_numeric_usage_value(tmp_path):
    path = tmp_path / "bad-value.xlsx"
    usage = pd.DataFrame(USAGE_COLUMNS)
    usage["Hours"] = "ten"
    create_workbook(path, usage=usage, include_allocation=False)
    with pytest.raises(WorkbookDataError, match="non-numeric values"):
        load_workbook(path)


def test_load_workbook_parses_current_allocation_layout_and_enterprise_summary(tmp_path):
    path = tmp_path / "allocation.xlsx"
    create_workbook(path)
    result = load_workbook(path)
    assert result["allocation"].loc[0, "Department"] == "DPE"
    assert len(result["allocation"]) == 1
    assert result["enterprise"]["Quota (Hrs)"] == 100
    assert result["enterprise"]["Consumed (Hrs)"] == 10


def test_duplicate_usage_records_are_preserved_and_counted(tmp_path):
    path = tmp_path / "duplicates.xlsx"
    usage = pd.DataFrame({key: values * 2 for key, values in USAGE_COLUMNS.items()})
    create_workbook(path, usage=usage, include_allocation=False)
    result = load_workbook(path)
    assert len(result["sim"]) == 2
    assert result["duplicate_enterprise_rows"] == 2


def test_load_workbook_supports_searah_trailing_space_alias_and_keeps_pool_separate(tmp_path):
    path = tmp_path / "searah.xlsx"
    create_workbook(path, searah=True, include_allocation=False)
    result = load_workbook(path)
    assert len(result["sim"]) == 1
    assert len(result["searah"]) == 1
    assert result["searah_summary"] == {"Quota (Hrs)": 15000, "Consumed (Hrs)": 100}


def test_load_workbook_fails_when_enterprise_usage_sheet_is_missing(tmp_path):
    path = tmp_path / "missing-sheet.xlsx"
    create_workbook(path, include_required=False, include_allocation=False)
    with pytest.raises(WorkbookSchemaError, match="Missing required worksheet"):
        load_workbook(path)
