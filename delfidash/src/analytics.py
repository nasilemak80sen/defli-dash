from __future__ import annotations
import pandas as pd
import numpy as np

MONTH_ORDER = ["Jan'26", "Feb'26", "Mar'26", "Apr'26", "May'26", "Jun'26", "Jul'26", "Aug'26", "Sep'26"]

def monthly_simulation(sim: pd.DataFrame, searah: pd.DataFrame | None = None) -> pd.DataFrame:
    frames = [x for x in [sim, searah] if x is not None and not x.empty]
    if not frames: return pd.DataFrame(columns=["Month", "Hours"])
    d = pd.concat(frames, ignore_index=True)
    d = d[d["Month"].astype("string").isin(MONTH_ORDER)]
    out = d.groupby("Month", observed=False)["Hours per User"].sum().reindex(MONTH_ORDER, fill_value=0).reset_index()
    return out.rename(columns={"Hours per User":"Hours"})

def department_simulation(sim: pd.DataFrame, searah: pd.DataFrame | None = None) -> pd.DataFrame:
    frames = [x for x in [sim, searah] if x is not None and not x.empty]
    if not frames: return pd.DataFrame(columns=["Department","Hours"])
    d = pd.concat(frames, ignore_index=True)
    if "Month" in d.columns:
        d = d[d["Month"].astype("string").isin(MONTH_ORDER)]
    dept = "Updated Department" if "Updated Department" in d else "Department"
    return d.groupby(dept, dropna=False)["Hours per User"].sum().reset_index(name="Hours").rename(columns={dept:"Department"}).sort_values("Hours", ascending=False)

def user_simulation(sim: pd.DataFrame, searah: pd.DataFrame | None = None) -> pd.DataFrame:
    frames = [x for x in [sim, searah] if x is not None and not x.empty]
    if not frames: return pd.DataFrame(columns=["User","Hours"])
    d = pd.concat(frames, ignore_index=True)
    if "Month" in d.columns:
        d = d[d["Month"].astype("string").isin(MONTH_ORDER)]
    return d.groupby("User", dropna=False)["Hours per User"].sum().reset_index(name="Hours").sort_values("Hours", ascending=False)

def vm_monthly(vm: pd.DataFrame) -> pd.DataFrame:
    if vm.empty: return pd.DataFrame(columns=["Month","Duration Hours","Active Users"])
    d=vm.copy()
    d["Month"]=d["Date"].dt.to_period("M").dt.to_timestamp()
    return d.groupby("Month").agg(**{"Duration Hours":("Sum of Duration Hours","sum"),"Active Users":("User","nunique")}).reset_index()

def profile_summary(profiles: pd.DataFrame) -> pd.DataFrame:
    if profiles.empty: return pd.DataFrame(columns=["Profile","Events","Users"])
    return profiles.groupby("Profile", dropna=False).agg(Events=("User","size"),Users=("User","nunique")).reset_index().sort_values("Events",ascending=False)

def department_vm(vm: pd.DataFrame) -> pd.DataFrame:
    if vm.empty: return pd.DataFrame(columns=["Department","Duration Hours","Users"])
    c="Department_" if "Department_" in vm else "Department"
    return vm.groupby(c,dropna=False).agg(**{"Duration Hours":("Sum of Duration Hours","sum"),"Users":("User","nunique")}).reset_index().rename(columns={c:"Department"}).sort_values("Duration Hours",ascending=False)

def data_quality(data: dict) -> list[dict]:
    out=[]
    for key,label in [("sim","Simulation detail"),("vm","VM daily activity"),("profiles","Profile activity"),("rejected","Rejected sessions")]:
        d=data.get(key,pd.DataFrame())
        out.append({"Dataset":label,"Rows":len(d),"Status":"Loaded" if len(d) else "Missing / empty"})
    p=data.get("profiles",pd.DataFrame())
    if not p.empty and "Date" in p:
        dates=p["Date"].dropna()
        out.append({"Dataset":"Profile date coverage","Rows":len(dates),"Status":f"{dates.min():%d %b %Y} to {dates.max():%d %b %Y}" if len(dates) else "No valid dates"})
    r=data.get("rejected",pd.DataFrame())
    out.append({"Dataset":"Rejected-session date reliability","Rows":len(r),"Status":"Needs source-header validation before trend analysis"})
    return out
