# DELFI Utilisation Intelligence

A Python prototype that turns the September 2026 DELFI consolidated report into an interactive utilisation-awareness dashboard.

## Recommended architecture

- **Streamlit is the primary application shell**: navigation, file upload, filters, KPI cards, explanatory messages and data-quality disclosures.
- **Plotly is the charting layer**: interactive charts work directly inside Streamlit and Dash.
- **Dash is an optional companion app**: included for callback-heavy analytical experiences that may later need more complex cross-filtering. Streamlit and Dash are separate web frameworks; they are not merged into one framework. Run Dash as a separate service/process when needed.
- **Pandas is the data layer**: workbook ingestion, normalisation, aggregation and validation are kept outside the UI.

For the first proof of concept, use Streamlit as the single entry point. Do not operate two frameworks just for the sake of it. Keep the Dash companion only if a specific interaction genuinely benefits from Dash.

## Features in this prototype

1. Executive Overview: consumption story, monthly simulation, departmental split, VM activity and top users.
2. Simulation Hours: department filter, monthly trend, departmental and user-level consumption, allocation/balance table.
3. VM Activity: daily active users, duration, department and user breakdown.
4. Access & Rejections: provisional rejected-session counts by department and user, without unreliable time trends.
5. Profiles & Access: observed profile events, unique users and profile mix.
6. Storage & Capacity: explicit data-readiness page with the fields needed to activate storage analytics.
7. Data Quality & Notes: dataset coverage and limitations made visible.

## Important source-data limitations

The supplied workbook has some gaps. This prototype does **not** invent values for missing data.

- `Storage` contains section headings but no readable tabular storage values in the supplied file. Storage analytics are not populated yet.
- `2026 Package Info` and `Domain Profiles` are empty.
- Profile activity appears limited to a narrow date range in this extract. Confirm whether it is a snapshot.
- The rejected-session detail sheet has a date/header alignment issue. Counts should be treated as provisional until source columns are reconciled.
- Simulation aggregation uses `Hours per User`, not raw `Hours`, because the raw data contains different CPU-hour units. Confirm the normalisation convention with the DELFI platform owner.

## Local setup (Windows PowerShell)

```powershell
cd path\to\delfi_utilisation_intelligence
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

Open the local URL shown by Streamlit, normally `http://localhost:8501`.

## Optional Dash companion

In a second PowerShell terminal:

```powershell
cd path\to\delfi_utilisation_intelligence
.\.venv\Scripts\Activate.ps1
python dash_app.py
```

Open `http://127.0.0.1:8050`.

If a future Streamlit page needs to embed the running Dash app, use:

```python
import streamlit.components.v1 as components
components.iframe("http://127.0.0.1:8050", height=900, scrolling=True)
```

This requires both processes to be running. For deployment, host Dash behind an approved reverse proxy/service and embed its trusted URL. Do not assume localhost embedding will work for remote users.

## Data refresh

- Replace the local workbook at `data/raw/DelfiPTS_Sep2026_Profile_Storage_SimHrs_ConsolidatedReport_forStudy.xlsx`, or upload a new `.xlsx` from the sidebar.
- The current parser expects the sheet names in the supplied workbook. If the reporting team changes sheet names or column definitions, update `src/data_loader.py`.
- Check the Data Quality & Notes page after every refresh.

## GitHub and confidentiality

**Do not publish the supplied workbook, user-level extracts, corporate email addresses, or identifiable utilisation records in a public repository.**

The workbook is included in this local ZIP so the prototype can run immediately, but it is excluded from Git by `.gitignore`. Before pushing:
1. Keep the repository private if it contains any company-specific logic or metadata.
2. Confirm PETRONAS data-handling and GitHub policies.
3. Do not force-add `data/raw/*.xlsx`.
4. Prefer a synthetic/anonymised demo dataset for public screenshots and CI.

## Project structure

```text
delfi_utilisation_intelligence/
├── app.py
├── dash_app.py
├── requirements.txt
├── README.md
├── .gitignore
├── data/
│   └── raw/
│       └── [local source workbook; gitignored]
├── src/
│   ├── __init__.py
│   ├── data_loader.py
│   └── analytics.py
└── tests/
```

## Roadmap

- Reconcile storage data source and add storage concentration / growth analysis.
- Confirm the meaning and conversion of each simulation unit.
- Validate allocation and adjustment rules against the package owner.
- Repair rejected-session date mapping and build concurrency indicators.
- Add tests for monthly totals, user aggregation, data-quality checks and workbook schema drift.
- Add role-based views and approved deployment/authentication only after the proof of concept is accepted.
