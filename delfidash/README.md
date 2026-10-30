# DELFI Utilisation Intelligence

A Python prototype for understanding DELFI simulation, profile, VM and storage utilisation. Streamlit is the primary application; Dash remains an optional companion for callback-driven exploration.

## Architecture and data boundaries

- **Streamlit** is the primary application shell and presentation layer.
- **Dash** is a separate optional process. It shares the Python analytics layer; it is not merged with Streamlit.
- **Pandas / OpenPyXL** handle workbook ingestion and analysis.
- **Domain modules** contain unit conversion, aggregation and reconciliation logic outside UI callbacks.
- **Enterprise and Searah are separate pools.** Never add dedicated Searah usage to Enterprise entitlement or reconciliation totals.
- **Simulation reporting** uses the workbook's `Hours per User` normalised field until the platform owner formally approves conversion factors. Proposed factors are recorded in `config/unit_conversion.csv`; they are not approved billing rules.
- VM duration is not simulation hours. Profile activity is not purchased licence inventory. Storage must not be estimated from the image-only worksheet.

## Data integrity controls

`src/data_loader.py` validates the required Enterprise usage worksheet and required fact columns, resolves known trailing-whitespace sheet-name variants, validates numeric usage values and reporting-month labels, distinguishes missing optional sheets from unreadable sheets, and records a SHA-256 source-file hash. Invalid usage rows raise a contextual error rather than being silently converted to an empty frame or zero hours.

The monthly pivot worksheets use a documented layout contract in `PIVOT_LAYOUT`. These formatted pivots still require the source workbook to retain that layout; a changed row/column shape fails explicitly. The raw simulation facts remain the preferred source for usage calculations.

`src/units.py` loads effective-dated conversion rules. Rules marked `proposed` are blocked by default. An explicit override is available only for diagnostic sensitivity comparisons and must not be used to publish ledgers until approvals are recorded.

`src/analytics.py` aggregates one pool at a time, retains valid months not in the original Jan–Sep extract, and provides allocation reconciliation checks. `src/reconciliation.py` exposes a publish gate for failed or unavailable reconciliation.

## Local setup (Windows PowerShell)

```powershell
cd path\to\defli-dash\delfidash
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

Open the local URL shown by Streamlit, normally `http://localhost:8501`.

## Optional Dash companion

With the same environment active, place the source workbook at `data/raw/DelfiPTS_Sep2026_Profile_Storage_SimHrs_ConsolidatedReport_forStudy.xlsx` and run:

```powershell
python dash_app.py
```

Open `http://127.0.0.1:8050`. Dash loads the workbook only when the app is constructed, uses the same validated loader and presents Enterprise and Searah as separate chart series.

## Tests

From the `delfidash` directory:

```powershell
python -m compileall -q app.py dash_app.py src tests
python -m pytest -q
```

The tests use synthetic data and do not require the confidential September workbook. GitHub Actions runs compilation and tests on Python 3.11 and 3.12 for pushes to development branches and pull requests to `main`.

## Source-data confidentiality

Do not publish the source workbook, employee email addresses, user-level extracts or identifiable utilisation records in this public repository. Keep `data/raw/` excluded from Git. Use synthetic records for public screenshots and continuous integration, and follow PETRONAS data-handling requirements.

## Known items requiring source-owner confirmation

- Conversion factors, especially `realization.hour` (divide by two), `vCPU.hour` (multiply by two) and the zero factor for `CPU.hour`, remain proposed pending written approval.
- Allocation pivot offsets are isolated and validated in `PIVOT_LAYOUT` because the current Excel pivot uses formatted/merged headings. A changed workbook layout blocks parsing and must be reconciled before reporting.
- Session-level concurrency requires SLB session start/end telemetry. Daily unique users are not concurrency.
- Storage reporting requires a structured storage export; screenshot-derived estimates are not treated as precise facts.
- Allocation adjustments and remaining balances must be reconciled before any chargeback or contractual conclusions.
