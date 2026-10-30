"""Optional standalone Dash companion. Streamlit remains the primary application."""
from pathlib import Path
import sys
import pandas as pd
from dash import Dash, dcc, html, Input, Output
import plotly.express as px

ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from src.data_loader import load_workbook
from src.analytics import monthly_simulation, department_simulation

FILE=ROOT/"data"/"raw"/"DelfiPTS_Sep2026_Profile_Storage_SimHrs_ConsolidatedReport_forStudy.xlsx"
data=load_workbook(FILE)
sim=data["sim"]; searah=data["searah"]
dept=department_simulation(sim,searah)
app=Dash(__name__)
app.title="DELFI Simulation Explorer"
app.layout=html.Div([
    html.H1("DELFI Simulation Explorer"),
    html.P("Optional Dash companion for deeper, callback-driven exploration."),
    html.Label("Department"),
    dcc.Dropdown(id="department",options=[{"label":str(x),"value":str(x)} for x in sorted(dept["Department"].dropna().unique())],multi=True),
    dcc.Graph(id="monthly"),
    dcc.Graph(id="department"),
],style={"fontFamily":"Arial","maxWidth":"1200px","margin":"30px auto"})
@app.callback(Output("monthly","figure"),Output("department","figure"),Input("department","value"))
def update(selected):
    s=sim.copy(); sr=searah.copy()
    if selected:
        s=s[s["Updated Department"].astype(str).isin(selected)]
        sr=sr[sr["Updated Department"].astype(str).isin(selected)] if not sr.empty else sr
    m=monthly_simulation(s)
    d=department_simulation(s)
    return (px.area(m,x="Month",y="Hours",title="Monthly normalised simulation hours"),
            px.bar(d,x="Hours",y="Department",orientation="h",title="Department consumption"))
if __name__=="__main__":
    app.run(debug=False,host="127.0.0.1",port=8050)
