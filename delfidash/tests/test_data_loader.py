import pandas as pd
import pytest

from src.data_loader import WorkbookDataError, WorkbookSchemaError, _prepare_usage, _resolve_sheet


def valid_usage():
    return pd.DataFrame({
        "User": ["a", None], "Unit": ["hour", None], "Hours": [5, None],
        "Hours per User": [5, None], "Updated Department": ["DPE", None],
        "Updated Billing Dept": ["PE-RE", None], "Month": ["Oct'26", None],
    })


def test_sheet_alias_resolution_ignores_trailing_whitespace():
    assert _resolve_sheet(["Data_sim hrs_SEARAH "], ("Data_sim hrs_SEARAH",), required=True) == "Data_sim hrs_SEARAH "


def test_missing_required_sheet_is_explicit():
    with pytest.raises(WorkbookSchemaError, match="Missing required worksheet"):
        _resolve_sheet(["SUMMARY"], ("Data_sim hrs",), required=True)


def test_ambiguous_aliases_fail_instead_of_choosing_arbitrarily():
    with pytest.raises(WorkbookSchemaError, match="Ambiguous worksheet"):
        _resolve_sheet(["Data_sim hrs_SEARAH", "Data_sim hrs_SEARAH "], ("Data_sim hrs_SEARAH",), required=True)


def test_usage_loader_drops_only_quota_helper_rows_and_keeps_future_month():
    result = _prepare_usage(valid_usage(), "Data_sim hrs")
    assert result["User"].tolist() == ["a"]
    assert result["Month"].tolist() == ["Oct'26"]
    assert result["Hours per User"].tolist() == [5]


def test_usage_loader_rejects_non_numeric_hours():
    data = valid_usage().iloc[[0]].copy()
    data["Hours per User"] = data["Hours per User"].astype("object")
    data.loc[data.index[0], "Hours per User"] = "not-a-number"
    with pytest.raises(WorkbookDataError, match="non-numeric values"):
        _prepare_usage(data, "Data_sim hrs")


def test_usage_loader_rejects_missing_month_on_usage_row():
    data = valid_usage().iloc[[0]].copy()
    data.loc[data.index[0], "Month"] = "not a month"
    with pytest.raises(WorkbookDataError, match="unrecognised reporting month"):
        _prepare_usage(data, "Data_sim hrs")
