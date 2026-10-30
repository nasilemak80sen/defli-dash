import pandas as pd

from dash_app import build_figures, department_options


def test_dash_department_options_include_both_pools_without_merging_them():
    enterprise = pd.DataFrame({"User": ["a"], "Month": ["Jan'26"], "Hours per User": [10.0], "Updated Department": ["DPE"]})
    searah = pd.DataFrame({"User": ["b"], "Month": ["Jan'26"], "Hours per User": [7.0], "Updated Department": ["Searah"]})
    assert department_options(enterprise, searah) == ["DPE", "Searah"]


def test_dash_figures_show_enterprise_and_searah_as_distinct_series():
    enterprise = pd.DataFrame({"User": ["a", "a"], "Month": ["Jan'26", "Feb'26"],
                               "Hours per User": [10.0, 5.0], "Updated Department": ["DPE", "DPE"]})
    searah = pd.DataFrame({"User": ["b"], "Month": ["Jan'26"],
                           "Hours per User": [7.0], "Updated Department": ["DPE"]})
    monthly, department = build_figures(["DPE"], enterprise, searah)
    assert [trace.name for trace in monthly.data] == ["Enterprise", "Searah"]
    assert [list(trace.y) for trace in monthly.data] == [[10.0, 5.0], [7.0]]
    assert [trace.name for trace in department.data] == ["Enterprise", "Searah"]
    assert [list(trace.x) for trace in department.data] == [[15.0], [7.0]]


def test_dash_department_filter_applies_to_both_pools():
    enterprise = pd.DataFrame({"User": ["a", "c"], "Month": ["Jan'26"] * 2,
                               "Hours per User": [10.0, 99.0], "Updated Department": ["DPE", "DGS"]})
    searah = pd.DataFrame({"User": ["b"], "Month": ["Jan'26"],
                           "Hours per User": [7.0], "Updated Department": ["DPE"]})
    monthly, _ = build_figures(["DPE"], enterprise, searah)
    assert [list(trace.y) for trace in monthly.data] == [[10.0], [7.0]]
