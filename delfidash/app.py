"""Streamlit-only DELFI dashboard. The UI reads verified Parquet marts, never Excel."""
from __future__ import annotations

import os
from pathlib import Path
import sys

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analytics import data_quality  # noqa: E402
from src.marts import PublishedMartNotFound, load_published_period  # noqa: E402

st.set_page_config(
    page_title="DELFI Utilisation Intelligence",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.block-container{padding-top:1.4rem;padding-bottom:2.8rem;max-width:1450px}
.hero{padding:1.25rem 1.5rem;border-radius:16px;background:linear-gradient(115deg,#102a43 0%,#174a63 60%,#087e8b 100%);color:#fff;margin-bottom:1rem}
.hero h1{font-size:1.9rem;margin:0 0 .35rem 0;color:#fff}
.hero p{margin:0;color:#d9edf2}
.note{color:#64748b;font-size:.88rem}
</style>
""", unsafe_allow_html=True)

MART_ROOT = Path(os.environ.get("DELFI_MARTS_ROOT", ROOT / "data" / "processed"))


@st.cache_data(ttl=60, show_spinner=False)
def read_published_marts(root: str) -> dict:
    return load_published_period(root)


try:
    data = read_published_marts(str(MART_ROOT))
except PublishedMartNotFound as exc:
    st.title("DELFI Utilisation Intelligence")
    st.error("No verified reporting period is currently published.")
    st.write(str(exc))
    st.markdown("Run the monthly build after the source workbook and approval gates are ready:")
    st.code(
        'python jobs/build_period.py --source "data/raw/DelfiPTS_Sep2026_Profile_Storage_SimHrs_ConsolidatedReport_forStudy.xlsx"',
        language="powershell",
    )
    st.caption("The dashboard does not parse or upload Excel files. It reads only published, SHA-256-verified Parquet marts.")
    st.stop()

build = data["build_metadata"]
period = build["period"]
enterprise = data.get("sim", pd.DataFrame())
searah = data.get("searah", pd.DataFrame())
monthly = data.get("monthly", pd.DataFrame())
searah_monthly = data.get("searah_monthly", pd.DataFrame())
department_usage = data.get("department_usage", pd.DataFrame())
department_monthly = data.get("department_monthly", pd.DataFrame())
department_ledger = data.get("department_ledger", pd.DataFrame())
pool_ledger = data.get("pool_ledger", pd.DataFrame())
vm_monthly = data.get("vm_monthly", pd.DataFrame())
vm_department = data.get("vm_department", pd.DataFrame())
profile_ledger = data.get("profile_summary", pd.DataFrame())
rejection_summary = data.get("rejection_summary", pd.DataFrame())
reconciliation = data.get("reconciliation", pd.DataFrame())

st.sidebar.title("DELFI Intelligence")
st.sidebar.caption("Published, reconciled period")
st.sidebar.metric("Reporting period", period)
st.sidebar.caption(f"Policy: {build.get('policy_version', 'Unknown')}")
st.sidebar.caption(f"Source SHA-256: {str(build.get('source_sha256', ''))[:16]}…")
st.sidebar.divider()
page = st.sidebar.radio(
    "Explore",
    [
        "Executive Overview",
        "Simulation Hours",
        "VM Activity",
        "Access & Rejections",
        "Profiles & Access",
        "Storage & Capacity",
        "Data Quality & Reconciliation",
    ],
)
st.sidebar.divider()
st.sidebar.caption("Streamlit reads prebuilt Parquet marts. Excel ingestion runs separately.")

st.markdown(
    f'<div class="hero"><h1>DELFI Utilisation Intelligence</h1>'
    f'<p>Resource consumption, allocation and data quality for {period}.</p></div>',
    unsafe_allow_html=True,
)
st.caption(
    f"Published build {build.get('build_id')} · Built at {build.get('built_at_utc')} · "
    f"Source: {data.get('source_file', 'Unknown')}"
)


def fmt(value, digits: int = 0) -> str:
    try:
        if pd.isna(value):
            return "—"
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def pool_value(name: str, column: str):
    if pool_ledger.empty or "Pool" not in pool_ledger.columns:
        return None
    values = pool_ledger.loc[pool_ledger["Pool"] == name, column]
    return values.iloc[0] if not values.empty else None


def show_pool_kpis(name: str, columns):
    row = st.columns(len(columns))
    for index, (label, column, digits) in enumerate(columns):
        with row[index]:
            st.metric(label, fmt(pool_value(name, column), digits))


if page == "Executive Overview":
    st.subheader("Capacity and consumption")
    show_pool_kpis("Enterprise", [
        ("Enterprise quota (hours)", "Quota (Hrs)", 0),
        ("Enterprise consumed (hours)", "Consumed (Hrs)", 1),
        ("Enterprise balance (hours)", "Balance (Hrs)", 1),
        ("Enterprise utilisation", "Utilisation (%)", 1),
    ])
    if pool_value("Searah", "Quota (Hrs)") is not None:
        st.subheader("Dedicated Searah pool")
        show_pool_kpis("Searah", [
            ("Searah quota (hours)", "Quota (Hrs)", 0),
            ("Searah consumed (hours)", "Consumed (Hrs)", 1),
            ("Searah balance (hours)", "Balance (Hrs)", 1),
            ("Searah utilisation", "Utilisation (%)", 1),
        ])

    left, right = st.columns([1.2, 1])
    with left:
        st.markdown("**Enterprise monthly normalised consumption**")
        if not monthly.empty:
            figure = px.bar(monthly, x="Month", y="Hours", color_discrete_sequence=["#087e8b"])
            figure.update_layout(height=330, margin=dict(l=10, r=10, t=15, b=10), yaxis_title="Normalised hours", xaxis_title="")
            st.plotly_chart(figure, use_container_width=True)
        else:
            st.info("No Enterprise monthly mart was published.")
    with right:
        st.markdown("**Department consumption**")
        if not department_usage.empty:
            figure = px.bar(
                department_usage.sort_values("Hours"),
                x="Hours", y="Department", orientation="h",
                color_discrete_sequence=["#d19a36"],
            )
            figure.update_layout(height=330, margin=dict(l=10, r=10, t=15, b=10), xaxis_title="Normalised hours", yaxis_title="")
            st.plotly_chart(figure, use_container_width=True)
        else:
            st.info("No department usage mart was published.")

    st.info(
        "Interpretation guardrail: daily unique VM users are not concurrency; VM duration is excluded; "
        "profile events are not purchased licence inventory; storage is not estimated from screenshots."
    )

elif page == "Simulation Hours":
    st.subheader("Enterprise simulation ledger")
    st.caption("Normalised hours are calculated by the approved, effective-dated conversion-rule version.")
    if not monthly.empty:
        st.plotly_chart(
            px.line(monthly, x="Month", y="Hours", markers=True, color_discrete_sequence=["#087e8b"]),
            use_container_width=True,
        )
    if not department_monthly.empty:
        departments = sorted(department_monthly["Department"].dropna().astype(str).unique())
        selected = st.multiselect("Department filter", departments, default=departments)
        filtered = department_monthly[department_monthly["Department"].astype(str).isin(selected)]
        if not filtered.empty:
            chart = px.bar(
                filtered, x="Month", y="Hours", color="Department", barmode="stack",
                title="Monthly departmental normalised hours",
            )
            chart.update_layout(height=380, yaxis_title="Normalised hours", xaxis_title="")
            st.plotly_chart(chart, use_container_width=True)
    if not department_ledger.empty:
        st.markdown("**Department quota, consumption and balance**")
        preferred = [
            "Department", "Quota (Hrs)", "Consumed (Hrs)", "Adjustment (Hrs)",
            "Consumed (Hrs) Final", "Balance (Hrs)", "Utilisation (%)", "Policy Status",
        ]
        visible = [column for column in preferred if column in department_ledger.columns]
        st.dataframe(department_ledger[visible], use_container_width=True, hide_index=True)
    if not searah_monthly.empty:
        st.subheader("Searah dedicated pool, shown separately")
        st.plotly_chart(
            px.bar(searah_monthly, x="Month", y="Hours", color_discrete_sequence=["#d19a36"]),
            use_container_width=True,
        )
    st.caption("User-level extracts are retained in the local marts for authorised processing, not exposed in this unauthenticated prototype.")

elif page == "VM Activity":
    st.subheader("Daily VM activity")
    st.caption("Daily distinct users are an activity proxy. They do not measure simultaneous sessions or the 220-profile cap.")
    if vm_monthly.empty:
        st.warning("No VM activity mart was published for this source period.")
    else:
        st.plotly_chart(
            px.line(vm_monthly, x="Month", y="Active Users", markers=True, color_discrete_sequence=["#315a9b"]),
            use_container_width=True,
        )
    if not vm_department.empty:
        st.dataframe(vm_department, use_container_width=True, hide_index=True)
    st.info("Session-level concurrency and session hygiene require SLB session start/end telemetry. The unreliable duration field is excluded.")

elif page == "Access & Rejections":
    st.subheader("Rejected session events")
    rejected = data.get("rejected", pd.DataFrame())
    if rejected.empty:
        st.warning("No rejected-session fact mart was published.")
    else:
        total = pd.to_numeric(rejected.get("count", pd.Series(dtype=float)), errors="coerce").sum()
        users = rejected["User"].nunique() if "User" in rejected.columns else 0
        col1, col2 = st.columns(2)
        col1.metric("Rejected event count", fmt(total))
        col2.metric("Affected users", fmt(users))
    if not rejection_summary.empty:
        st.dataframe(rejection_summary, use_container_width=True, hide_index=True)
    st.caption("Counts are event-level signals. Do not interpret them as unique sessions when source session IDs are absent.")

elif page == "Profiles & Access":
    st.subheader("Observed profile activity")
    st.caption("This is usage activity, not purchased licence inventory or a complete concurrency measurement.")
    if profile_ledger.empty:
        st.warning("No profile activity mart was published.")
    else:
        st.dataframe(profile_ledger, use_container_width=True, hide_index=True)

elif page == "Storage & Capacity":
    st.subheader("Storage data readiness")
    st.warning("No structured storage export is available in the source workbook. Storage utilisation, ownership and growth are not published.")
    st.markdown(
        "A structured feed needs tenant, folder or storage domain, owner, department, used capacity, "
        "quota and snapshot date. Image-only charts are not used to manufacture precise storage KPIs."
    )

else:
    st.subheader("Data quality and reconciliation")
    quality = pd.DataFrame(data_quality(data))
    st.dataframe(quality, use_container_width=True, hide_index=True)
    st.markdown("**Reconciliation controls for this published period**")
    if reconciliation.empty:
        st.error("The published manifest contains no reconciliation rows.")
    else:
        failed = reconciliation[~reconciliation["Status"].isin(["PASS", "NOT APPLICABLE"])]
        if failed.empty:
            st.success("All mandatory controls passed.")
        else:
            st.error(f"{len(failed)} control(s) require attention.")
        st.dataframe(reconciliation, use_container_width=True, hide_index=True)
    st.markdown("**Lineage**")
    st.code(
        f"Source: {data.get('source_file')}\n"
        f"SHA-256: {data.get('source_sha256')}\n"
        f"Policy: {build.get('policy_version')}\n"
        f"Build: {build.get('build_id')}",
        language="text",
    )

st.divider()
st.caption(
    "DELFI Utilisation Intelligence · Streamlit · Published Parquet marts · "
    "Use only after source controls and approvals pass."
)
