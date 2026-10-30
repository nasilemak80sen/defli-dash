from pathlib import Path
import sys
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from src.data_loader import load_workbook
from src.analytics import monthly_simulation, department_simulation, user_simulation, vm_monthly, profile_summary, department_vm, data_quality

st.set_page_config(page_title="DELFI Utilisation Intelligence",page_icon="◈",layout="wide",initial_sidebar_state="expanded")
st.markdown("""
<style>
:root{--ink:#14283f;--muted:#64748b;--teal:#00a6a6;--gold:#f4b942}
.block-container{padding-top:1.5rem;padding-bottom:3rem;max-width:1500px}
.hero{padding:1.35rem 1.5rem;border-radius:18px;background:linear-gradient(115deg,#102a43 0%,#174a63 60%,#087e8b 100%);color:white;margin-bottom:1.1rem}
.hero h1{font-size:2rem;margin:0 0 .35rem 0;color:white}
.hero p{margin:0;color:#d9edf2}
.kpi{background:#fff;border:1px solid #e4eaf0;border-radius:14px;padding:1rem 1.1rem;min-height:105px}
.kpi .label{color:#64748b;font-size:.82rem}
.kpi .value{font-size:1.65rem;font-weight:750;color:#14283f;line-height:1.4}
.kpi .hint{color:#64748b;font-size:.75rem}
.section-note{color:#64748b;font-size:.9rem}
</style>
""",unsafe_allow_html=True)

DEFAULT=ROOT/"data"/"raw"/"DelfiPTS_Sep2026_Profile_Storage_SimHrs_ConsolidatedReport_forStudy.xlsx"
st.sidebar.title("DELFI Intelligence")
st.sidebar.caption("Platform utilisation awareness")
uploaded=st.sidebar.file_uploader("Upload updated Excel report",type=["xlsx"])
path=None
if uploaded:
    temp=ROOT/"data"/"uploaded_report.xlsx"
    temp.parent.mkdir(exist_ok=True)
    temp.write_bytes(uploaded.getvalue())
    path=temp
elif DEFAULT.exists():
    path=DEFAULT
else:
    st.warning("No source workbook found. Place the report in data/raw/ or upload it using the sidebar.")
    st.stop()

try:
    data=load_workbook(path)
except Exception as e:
    st.error(f"Could not read workbook: {e}")
    st.stop()

sim=data["sim"]; searah=data["searah"]; vm=data["vm"]; profiles=data["profiles"]
alloc=data["allocation"]; ent=data["enterprise"]
months=monthly_simulation(sim)
searah_months=monthly_simulation(searah)
dept_sim=department_simulation(sim)
user_sim=user_simulation(sim)
vm_m=vm_monthly(vm)
profile=profile_summary(profiles)
dept_vm=department_vm(vm)

st.markdown("""
<div class="hero">
  <h1>DELFI Utilisation Intelligence</h1>
  <p>Make every hour, profile and platform resource visible. Understand usage, spot pressure early, and make better allocation decisions.</p>
</div>
""",unsafe_allow_html=True)

with st.sidebar:
    st.divider()
    page=st.radio("Explore",["Executive Overview","Simulation Hours","VM Activity","Access & Rejections","Profiles & Access","Storage & Capacity","Data Quality & Notes"])
    st.divider()
    st.caption("Reporting period: Jan–Sep 2026")
    st.caption("Source: "+data["source_file"])

def kpi(label,value,hint=""):
    st.markdown(f'<div class="kpi"><div class="label">{label}</div><div class="value">{value}</div><div class="hint">{hint}</div></div>',unsafe_allow_html=True)

def fmt(v):
    return f"{v:,.0f}" if pd.notna(v) else "—"

if page=="Executive Overview":
    total_sim=float(months["Hours"].sum()) if not months.empty else 0
    quota=ent.get("Quota (Hrs)")
    balance=ent.get("Balance (Hrs)")
    sim_users=int(sim["User"].nunique()) if not sim.empty else 0
    searah_consumed=data.get("searah_summary",{}).get("Consumed (Hrs)")
    cols=st.columns(4)
    with cols[0]: kpi("Simulation hours",fmt(total_sim),"Normalised Hours per User")
    with cols[1]: kpi("Enterprise quota",fmt(quota) if pd.notna(quota) else "Not parsed","Annual package quota")
    with cols[2]: kpi("Simulation users",fmt(sim_users),"Distinct users in simulation detail")
    with cols[3]: kpi("Searah dedicated hours",fmt(searah_consumed) if pd.notna(searah_consumed) else "Not parsed","Separate 15,000-hour allocation")
    st.markdown("### The utilisation story")
    st.markdown("This view is designed to answer three questions: **where are resources going, who is driving consumption, and where should we act?**")
    c1,c2=st.columns([1.35,1])
    with c1:
        st.subheader("Simulation consumption by month")
        fig=go.Figure()
        fig.add_trace(go.Bar(x=months["Month"].astype(str),y=months["Hours"],name="Enterprise package",marker_color="#078b91"))
        if not searah_months.empty:
            fig.add_trace(go.Scatter(x=searah_months["Month"].astype(str),y=searah_months["Hours"],name="Searah dedicated",mode="lines+markers",line=dict(color="#e0a52b",width=3)))
        fig.update_layout(height=340,margin=dict(l=10,r=10,t=20,b=10),yaxis_title="Normalised hours",xaxis_title="",legend=dict(orientation="h",y=1.12))
        st.plotly_chart(fig,use_container_width=True)
    with c2:
        st.subheader("Simulation consumption by department")
        fig=px.bar(dept_sim.head(8).sort_values("Hours"),x="Hours",y="Department",orientation="h",color_discrete_sequence=["#e0a52b"])
        fig.update_layout(height=340,margin=dict(l=10,r=10,t=20,b=10),xaxis_title="Normalised hours",yaxis_title="")
        st.plotly_chart(fig,use_container_width=True)
    c3,c4=st.columns(2)
    with c3:
        st.subheader("VM activity: duration by month")
        if not vm_m.empty:
            fig=px.line(vm_m,x="Month",y="Duration Hours",markers=True,color_discrete_sequence=["#315a9b"])
            fig.update_layout(height=300,margin=dict(l=10,r=10,t=15,b=10),yaxis_title="Recorded duration hours",xaxis_title="")
            st.plotly_chart(fig,use_container_width=True)
        else: st.info("VM activity data not available.")
    with c4:
        st.subheader("Top simulation consumers")
        fig=px.bar(user_sim.head(10).sort_values("Hours"),x="Hours",y="User",orientation="h",color_discrete_sequence=["#078b91"])
        fig.update_layout(height=300,margin=dict(l=10,r=10,t=15,b=10),xaxis_title="Normalised hours",yaxis_title="")
        st.plotly_chart(fig,use_container_width=True)
    st.info("Interpretation guardrail: VM duration, simulation hours, profile events and storage are different measures. They must not be added together or described as one universal utilisation score.")
    st.subheader("Management prompts")
    st.markdown("- Which teams account for the largest share of simulation consumption?\n- Are allocations aligned with actual demand and business priorities?\n- Are high-consumption users aware of their usage pattern?\n- Are VM duration and rejected sessions signalling access or capacity friction?")

elif page=="Simulation Hours":
    st.markdown("## Simulation hours")
    st.caption("Normalised consumption uses the workbook's **Hours per User** field. Raw Hours across different CPU-hour units should not be summed without a documented conversion.")
    dept_opts=sorted(dept_sim["Department"].dropna().astype(str).unique()) if not dept_sim.empty else []
    selected=st.multiselect("Department filter",dept_opts,default=dept_opts)
    filt=sim[sim["Updated Department"].astype(str).isin(selected)] if not sim.empty else sim
    c1,c2=st.columns(2)
    with c1:
        m=monthly_simulation(filt)
        fig=px.area(m,x="Month",y="Hours",markers=True,color_discrete_sequence=["#078b91"])
        fig.update_layout(height=360,yaxis_title="Normalised hours",xaxis_title="")
        st.plotly_chart(fig,use_container_width=True)
    with c2:
        d=department_simulation(filt)
        fig=px.bar(d.head(12).sort_values("Hours"),x="Hours",y="Department",orientation="h",color="Hours",color_continuous_scale="Teal")
        fig.update_layout(height=360,yaxis_title="",xaxis_title="Normalised hours",coloraxis_showscale=False)
        st.plotly_chart(fig,use_container_width=True)
    if not searah.empty:
        st.subheader("Searah dedicated allocation (reported separately)")
        ss=data.get("searah_summary",{})
        s1,s2=st.columns(2)
        with s1: kpi("Searah quota",fmt(ss.get("Quota (Hrs)")),"Dedicated allocation")
        with s2: kpi("Searah consumed",fmt(ss.get("Consumed (Hrs)")),"Do not combine with enterprise quota")
        sm=monthly_simulation(searah)
        fig=px.bar(sm,x="Month",y="Hours",color_discrete_sequence=["#e0a52b"])
        fig.update_layout(height=260,yaxis_title="Normalised hours",xaxis_title="")
        st.plotly_chart(fig,use_container_width=True)
    st.subheader("Highest individual consumption")
    u=user_simulation(filt)
    st.dataframe(u.head(30),use_container_width=True,hide_index=True)
    if not alloc.empty:
        st.subheader("Allocation and balance")
        a=alloc.copy()
        if "Balance (Hrs)" in a:
            a["Status"]=a["Balance (Hrs)"].apply(lambda x:"Over allocation" if pd.notna(x) and x<0 else "Within balance")
        st.dataframe(a,use_container_width=True,hide_index=True)
        st.caption("Allocation table is sourced from the formatted monthly simulation pivot. Validate adjustment rules with the package owner before treating balances as chargeable facts.")

elif page=="VM Activity":
    st.markdown("## VM activity")
    st.caption("VM duration indicates recorded session duration, not simulation consumption or billable compute hours.")
    if vm.empty:
        st.warning("No VM daily data was loaded.")
    else:
        dep=sorted(vm["Department_"].dropna().astype(str).unique()) if "Department_" in vm else []
        chosen=st.multiselect("Department",dep,default=dep)
        v=vm[vm["Department_"].astype(str).isin(chosen)] if chosen else vm
        c1,c2,c3=st.columns(3)
        with c1: kpi("VM users",fmt(v["User"].nunique()),"Distinct users in selected scope")
        with c2: kpi("Recorded duration",fmt(v["Sum of Duration Hours"].sum()),"Duration hours")
        with c3: kpi("Activity records",fmt(len(v)),"Daily user records")
        daily=v.groupby("Date").agg(**{"Active users":("User","nunique"),"Duration hours":("Sum of Duration Hours","sum")}).reset_index()
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=daily["Date"],y=daily["Active users"],name="Active users",mode="lines"))
        fig.update_layout(height=350,yaxis_title="Distinct users per day",xaxis_title="",margin=dict(l=10,r=10,t=20,b=10))
        st.plotly_chart(fig,use_container_width=True)
        c1,c2=st.columns(2)
        with c1:
            fig=px.bar(dept_vm.head(12).sort_values("Duration Hours"),x="Duration Hours",y="Department",orientation="h",color_discrete_sequence=["#315a9b"])
            fig.update_layout(height=360,yaxis_title="",xaxis_title="Duration hours")
            st.plotly_chart(fig,use_container_width=True)
        with c2:
            top=v.groupby("User")["Sum of Duration Hours"].sum().sort_values(ascending=False).head(15).reset_index()
            fig=px.bar(top.sort_values("Sum of Duration Hours"),x="Sum of Duration Hours",y="User",orientation="h",color_discrete_sequence=["#e0a52b"])
            fig.update_layout(height=360,yaxis_title="",xaxis_title="Duration hours")
            st.plotly_chart(fig,use_container_width=True)
        st.dataframe(daily.sort_values("Date",ascending=False),use_container_width=True,hide_index=True)

elif page=="Access & Rejections":
    st.markdown("## Access and rejected sessions")
    st.caption("Rejected-session counts can help reveal access friction, but the supplied date fields need reconciliation before time-series analysis.")
    rejected=data["rejected"]
    if rejected.empty:
        st.warning("No rejected-session records were loaded.")
    else:
        c1,c2,c3=st.columns(3)
        with c1: kpi("Rejected records",fmt(len(rejected)),"Rows in rejected users data")
        with c2: kpi("Affected users",fmt(rejected["User"].nunique()),"Distinct user accounts")
        with c3: kpi("Departments",fmt(rejected["Department_"].nunique()),"Mapped department labels")
        st.warning("The rejected-session sheet has misaligned date/session headers. This page intentionally avoids monthly or daily trend claims until the source mapping is verified.")
        if "Department_" in rejected:
            rd=rejected.groupby("Department_",dropna=False)["count"].sum().reset_index(name="Rejected records").sort_values("Rejected records",ascending=False)
            fig=px.bar(rd.head(15).sort_values("Rejected records"),x="Rejected records",y="Department_",orientation="h",color_discrete_sequence=["#d18a32"])
            fig.update_layout(height=380,yaxis_title="",xaxis_title="Rejected records")
            st.plotly_chart(fig,use_container_width=True)
        top_rej=rejected.groupby("User")["count"].sum().sort_values(ascending=False).head(25).reset_index(name="Rejected records")
        st.subheader("Users with the most rejected records")
        st.dataframe(top_rej,use_container_width=True,hide_index=True)
        st.caption("User-level information is identifiable. Keep this view within approved company access controls.")

elif page=="Storage & Capacity":
    st.markdown("## Storage and capacity")
    st.caption("Storage is a key part of DELFI utilisation, but the supplied workbook does not contain readable storage measurements.")
    st.warning("Storage analytics are not populated because the Storage worksheet contains section headings only, without usable tabular values.")
    st.markdown("""
**Data needed to activate this page**
- Tenant / environment
- Folder or storage domain
- Department or owning team
- Used capacity (GB or TB)
- Allocated capacity / quota
- Snapshot or reporting date
- Optional: last modified date and owner

Once those fields are available, this page can show capacity consumption, department share, largest folders, growth over time, and potential cleanup opportunities.
""")
    st.info("No storage consumption percentage or capacity KPI is estimated from the current file.")

elif page=="Profiles & Access":
    st.markdown("## Profiles and access")
    st.caption("Profile records represent observed profile activity in the source extract. They are not necessarily a complete inventory of purchased licences.")
    if profiles.empty:
        st.warning("No profile activity dataset was loaded.")
    else:
        c1,c2,c3=st.columns(3)
        with c1: kpi("Profile events",fmt(len(profiles)),"Rows in Data_profiles")
        with c2: kpi("Observed users",fmt(profiles["User"].nunique()),"Distinct users")
        with c3:
            dates=profiles["Date"].dropna()
            kpi("Date coverage",f"{dates.min():%b %Y}" if len(dates) else "Unknown",f"Through {dates.max():%b %Y}" if len(dates) else "No valid dates")
        ps=profile_summary(profiles)
        fig=px.bar(ps.head(15).sort_values("Events"),x="Events",y="Profile",orientation="h",color_discrete_sequence=["#078b91"])
        fig.update_layout(height=480,yaxis_title="",xaxis_title="Observed profile events")
        st.plotly_chart(fig,use_container_width=True)
        st.subheader("Profile detail")
        st.dataframe(ps,use_container_width=True,hide_index=True)
        if not data["users"].empty:
            st.subheader("User reference list")
            st.caption("Contains work email addresses. Keep this dashboard and its source files within approved company storage.")
            st.dataframe(data["users"].head(100),use_container_width=True,hide_index=True)

else:
    st.markdown("## Data quality and interpretation notes")
    st.write("The dashboard deliberately exposes source limitations rather than silently filling gaps or inventing metrics.")
    st.dataframe(pd.DataFrame(data_quality(data)),use_container_width=True,hide_index=True)
    st.markdown("""
**Known limitations to validate before management reporting**
- The workbook's `2026 Package Info` and `Domain Profiles` sheets are empty in the supplied file.
- The `Storage` sheet contains section labels but no readable tabular storage values. Storage KPIs and charts are therefore intentionally not fabricated.
- `Data_profiles` appears to have a limited date window in this extract. Confirm whether it is a snapshot or a complete activity history.
- The rejected-session detail sheet has a header/data alignment issue in its date-related columns. Treat counts as provisional and do not trend by date until reconciled.
- Simulation consumption uses `Hours per User` for normalised aggregation. Confirm the unit conversion logic with the DELFI platform owner.
- User-level fields include corporate email addresses. Do not commit the source workbook or identifiable exports to a public GitHub repository.
""")
    st.subheader("Loaded dataset sizes")
    st.json({k:len(data[k]) for k in ["sim","searah","vm","profiles","top","rejected","users","allocation","user_monthly"]})

st.divider()
st.caption("DELFI Utilisation Intelligence • Prototype • Validate source definitions before using figures for charging, procurement or contractual decisions.")
