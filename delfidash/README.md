# DELFI Utilisation Intelligence

A Streamlit-only utilisation and accountability prototype. The source workbook is ingested by a separate monthly build job; Streamlit reads only published, hash-verified Parquet marts.

## Architecture

- **Streamlit** is the only user interface.
- **Pandas and OpenPyXL** validate and transform the source workbook in the period build.
- **Parquet marts** are the published read model for the dashboard.
- **Policy YAML** controls pool quotas, thresholds and effective dates.
- **Versioned conversion rules** carry source-owner approval metadata.
- **Pytest and GitHub Actions** exercise the loaders, rules, reconciliation, publication and Streamlit runtime.

Dash has been removed from this prototype. Business rules remain in plain Python modules, outside the Streamlit presentation layer.

## Data and reporting safeguards

- Enterprise and Searah are separate pools. Searah has its own 15,000-hour allocation effective July–December 2026; it is never included in Enterprise totals.
- The 2026 Enterprise and Searah quotas, alert thresholds and numeric reconciliation tolerance are read from config/policy.yaml, not duplicated as code defaults.
- The policy is currently marked **proposed**. It cannot be published until the accountable owner records the approval metadata.
- Conversion factors are in config/unit_conversion.csv. Every used factor must have status **approved**, approver, role, date and evidence reference before the build can publish.
- Converted hours are compared row-by-row with the workbook's Hours per User column. A mismatch blocks publication.
- Allocation reconciliation uses the source Consumed (Hrs), adjustments, final consumption and balance fields. Unstructured Searah transfer notes do not become automatic ledger adjustments.
- Duplicate fact rows, missing totals, unavailable controls and any failed reconciliation block publication.
- VM duration values are excluded. Daily unique users are not concurrency.
- Storage is not estimated from the image-only worksheet.
- Source workbooks and generated marts contain identifiable company data. They are excluded from Git and must remain in approved local/company storage.

## 1. Set up the environment (Windows PowerShell)

From the delfidash directory:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Place the confidential workbook in data/raw/, for example:

```text
data/raw/DelfiPTS_Sep2026_Profile_Storage_SimHrs_ConsolidatedReport_forStudy.xlsx
```

Do not force-add this workbook or any user-level export to Git.

## 2. Build and publish a reporting period

Run the build explicitly:

```powershell
python jobs/build_period.py --source "data/raw/DelfiPTS_Sep2026_Profile_Storage_SimHrs_ConsolidatedReport_forStudy.xlsx"
```

The period is inferred from the latest month in the source. An optional --period YYYY-MM is accepted only when it matches that latest month; the snapshot allocation pivot cannot safely reconstruct earlier periods.

The job:

1. Opens the immutable workbook and records its SHA-256.
2. Validates required sheets, columns, values and pivot layout.
3. Applies the effective-dated conversion rules in diagnostic mode and compares every row with the source-normalised hours.
4. Reconciles the monthly user pivot, department allocation, Enterprise control total and Searah summary.
5. Checks policy and conversion-owner approval evidence.
6. Writes the period's Parquet marts and manifest atomically only when every mandatory control passes.

If any control fails or is unavailable, the job writes a redacted report under data/processed/_quarantine/<period>/<build_id>/, returns a non-zero exit code and leaves the previous latest.json pointer unchanged. It never publishes a partial ledger.

Builds are idempotent on source-file hash, policy hash, conversion-rule hash and period. Re-running the same inputs reuses the existing published build.

## 3. Source-owner approvals

Do not change a rule to approved simply to make the build pass.

For each unit used by the source period, the accountable owner must provide:
- The confirmed numerator/denominator or factor.
- Effective date and version.
- Approver name and role.
- Approval date.
- A traceable evidence reference (for example, an approved change record or written confirmation).

Populate the approval columns in config/unit_conversion.csv and update the rule version when the factor or effective date changes. The policy-level approval block in config/policy.yaml must also record the owner, role, approval date and reference. The current configuration intentionally remains proposed; no approval has been fabricated.

## 4. Run the Streamlit dashboard

Only after the build publishes successfully:

```powershell
streamlit run app.py
```

Streamlit reads data/processed/ and verifies the manifest, metadata and every Parquet file's SHA-256 before displaying any metrics. It does not load or parse Excel during page execution.

To point the dashboard at a different local mart directory:

```powershell
$env:DELFI_MARTS_ROOT = "D:\DELFI\processed"
streamlit run app.py
```

The prototype does not expose the user-level mart in its unauthenticated interface. Authentication and row-level authorisation remain enterprise-operationalisation work.

## 5. Schedule the monthly build (Windows Task Scheduler)

After the source workbook is delivered to a stable, approved local path, register the monthly task from PowerShell:

```powershell
.\jobs\register_monthly_task.ps1 -WorkbookPath "C:\ApprovedData\DelfiPTS_Sep2026_Profile_Storage_SimHrs_ConsolidatedReport_forStudy.xlsx" -ProjectRoot (Get-Location).Path -RunAt "02:00"
```

The task runs on the first day of each month and uses the latest reporting month found in the workbook. It does not upload the workbook or the marts to GitHub. Review the Task Scheduler history and the period quarantine directory after each run.

## 6. Tests and CI

From delfidash:

```powershell
python -m compileall -q app.py src jobs tests
python -m pytest -q
```

CI runs Python 3.11 and 3.12. Synthetic workbooks cover schema validation, conversion approval, reconciliation, quarantine, idempotent Parquet publication, mart integrity and the Streamlit AppTest runtime. CI deliberately does not need the confidential September workbook.

## Known data limitations

- The proposal's Storage worksheet is image-only; structured storage data is still required.
- Session start/end telemetry is required for true concurrency and session-hygiene metrics.
- The current source records Searah transfers in free-text notes rather than a structured approved adjustment ledger. A difference between Searah raw usage and the summary therefore blocks publication rather than being silently forced to tie out.
- Rejected-session rows without session IDs cannot be treated as uniquely traceable sessions.
- Person-level access controls must be implemented before the local user-level marts are exposed beyond an authorised chain of command.
- The real September workbook must be run through this build locally before calling its schema and totals validated. Public CI uses synthetic fixtures only.
