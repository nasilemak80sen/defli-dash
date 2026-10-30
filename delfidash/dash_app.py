"""Optional standalone Dash companion. Streamlit remains the primary application.

The module is safe to import in tests: workbook I/O and Dash app construction happen
only when ``create_app`` is called. Enterprise and Searah are visualised separately.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd
import plotly.graph_objects as go

from src.analytics import department_simulation, monthly_simulation
from src.data_loader import load_workbook

ROOT = Path(__file__).parent
DEFAULT_WORKBOOK = ROOT / "data" / "raw" / "DelfiPTS_Sep2026_Profile_Storage_SimHrs_ConsolidatedReport_forStudy.xlsx"


def _filter_departments(frame: pd.DataFrame, selected: Iterable[str] | None) -> pd.DataFrame:
    if frame.empty or not selected:
        return frame.copy()
    column = "Updated Department" if "Updated Department" in frame.columns else "Department"
    if column not in frame.columns:
        raise ValueError(f"Cannot filter simulation frame: missing department column {column!r}.")
    return frame.loc[frame[column].astype("string").isin(list(selected))].copy()


def department_options(enterprise: pd.DataFrame, searah: pd.DataFrame) -> list[str]:
    values: set[str] = set()
    for frame in (enterprise, searah):
        if frame.empty:
            continue
        column = "Updated Department" if "Updated Department" in frame.columns else "Department"
        if column in frame.columns:
            values.update(frame[column].dropna().astype(str).str.strip())
    return sorted(value for value in values if value)


def build_figures(selected: list[str] | None, enterprise: pd.DataFrame,
                  searah: pd.DataFrame) -> tuple[go.Figure, go.Figure]:
    """Build pool-separated monthly and department figures for the Dash callback."""
    enterprise_filtered = _filter_departments(enterprise, selected)
    searah_filtered = _filter_departments(searah, selected)

    monthly_figure = go.Figure()
    for label, frame in (("Enterprise", enterprise_filtered), ("Searah", searah_filtered)):
        summary = monthly_simulation(frame)
        monthly_figure.add_trace(go.Bar(x=summary["Month"], y=summary["Hours"], name=label))
    monthly_figure.update_layout(
        title="Monthly normalised simulation hours by pool", barmode="group",
        xaxis_title="Reporting month", yaxis_title="Normalised hours",
    )

    department_figure = go.Figure()
    for label, frame in (("Enterprise", enterprise_filtered), ("Searah", searah_filtered)):
        summary = department_simulation(frame)
        department_figure.add_trace(go.Bar(
            x=summary["Hours"], y=summary["Department"], name=label, orientation="h",
        ))
    department_figure.update_layout(
        title="Department consumption by pool", barmode="group",
        xaxis_title="Normalised hours", yaxis_title="Department",
    )
    return monthly_figure, department_figure


def create_app(workbook_path: str | Path = DEFAULT_WORKBOOK):
    """Construct the optional Dash application using a validated workbook."""
    try:
        from dash import Dash, dcc, html, Input, Output
    except ImportError as exc:  # clearer than an opaque module import error
        raise RuntimeError("Dash is optional. Install the dash dependency to run this companion app.") from exc

    data = load_workbook(workbook_path)
    enterprise, searah = data["sim"], data["searah"]
    app = Dash(__name__)
    app.title = "DELFI Simulation Explorer"
    app.layout = html.Div([
        html.H1("DELFI Simulation Explorer"),
        html.P("Optional Dash companion. Enterprise and Searah are displayed as separate pools."),
        html.Label("Department"),
        dcc.Dropdown(
            id="department-filter",
            options=[{"label": value, "value": value} for value in department_options(enterprise, searah)],
            multi=True,
        ),
        dcc.Graph(id="monthly-simulation-chart"),
        dcc.Graph(id="department-simulation-chart"),
    ], style={"fontFamily": "Arial", "maxWidth": "1200px", "margin": "30px auto"})

    @app.callback(
        Output("monthly-simulation-chart", "figure"),
        Output("department-simulation-chart", "figure"),
        Input("department-filter", "value"),
    )
    def update(selected):
        return build_figures(selected, enterprise, searah)

    return app


if __name__ == "__main__":
    create_app().run(debug=False, host="127.0.0.1", port=8050)
