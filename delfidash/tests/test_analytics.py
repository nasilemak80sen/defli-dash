import pandas as pd
import pytest

from src.analytics import department_simulation, monthly_simulation, pool_summary, user_simulation


def usage(users, months, hours, departments=None):
    frame = pd.DataFrame({"User": users, "Month": months, "Hours per User": hours})
    if departments is not None:
        frame["Updated Department"] = departments
    return frame


def test_monthly_simulation_sums_normalised_hours_and_retains_unexpected_months():
    data = usage(["a", "a", "b"], ["Jan'26", "Feb'26", "Oct'26"], [10.0, 20.0, 5.0])
    result = monthly_simulation(data)
    assert result.to_dict("records") == [
        {"Month": "Jan'26", "Hours": 10.0},
        {"Month": "Feb'26", "Hours": 20.0},
        {"Month": "Oct'26", "Hours": 5.0},
    ]


def test_monthly_simulation_rejects_unknown_month_instead_of_dropping_it():
    with pytest.raises(ValueError, match="Unrecognised reporting month"):
        monthly_simulation(usage(["a"], ["Q4"], [1.0]))


def test_user_simulation_groups_users():
    result = user_simulation(usage(["a", "a", "b"], ["Jan'26"] * 3, [1.0, 2.0, 4.0]))
    assert result.iloc[0]["User"] == "b"
    assert result.iloc[1]["Hours"] == 3.0


def test_department_simulation_uses_department_at_time_of_use():
    result = department_simulation(usage(["a", "b"], ["Jan'26"] * 2, [5.0, 8.0], ["DPE", "DGS"]))
    assert result.to_dict("records") == [{"Department": "DGS", "Hours": 8.0}, {"Department": "DPE", "Hours": 5.0}]


def test_enterprise_and_searah_are_reported_as_separate_pools():
    enterprise = usage(["a"], ["Jan'26"], [100.0])
    searah = usage(["b"], ["Jan'26"], [25.0])
    result = pool_summary(enterprise, searah, 211_200, 15_000)
    assert result["Consumed (Hrs)"].tolist() == [100.0, 25.0]
    assert result["Balance (Hrs)"].tolist() == [211_100.0, 14_975.0]


def test_duplicate_usage_lines_are_not_silently_deduplicated():
    frame = usage(["a", "a"], ["Jan'26", "Jan'26"], [10.0, 10.0])
    result = monthly_simulation(frame)
    assert result.loc[0, "Hours"] == 20.0


def test_non_finite_normalised_hours_are_rejected():
    with pytest.raises(ValueError, match="non-finite"):
        monthly_simulation(usage(["a"], ["Jan'26"], [float("inf")]))
