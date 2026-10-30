import pandas as pd
from src.analytics import monthly_simulation, user_simulation

def test_monthly_simulation_sums_normalised_hours():
    d=pd.DataFrame({"Month":["Jan'26","Feb'26"],"Hours per User":[10.0,20.0]})
    out=monthly_simulation(d)
    assert out.loc[out["Month"]=="Jan'26","Hours"].iloc[0] == 10.0
    assert out.loc[out["Month"]=="Feb'26","Hours"].iloc[0] == 20.0

def test_user_simulation_groups_users():
    d=pd.DataFrame({"User":["a","a","b"],"Hours per User":[1.0,2.0,4.0]})
    out=user_simulation(d)
    assert out.iloc[0]["User"] == "b"
    assert out.iloc[1]["Hours"] == 3.0
