"""Build one immutable DELFI reporting period and publish Parquet marts.

Run from the delfidash directory:
    python jobs/build_period.py --source data/raw/<report>.xlsx

A failed or unavailable control writes a redacted quarantine report and never
updates the latest published pointer.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analytics import (  # noqa: E402
    department_simulation, monthly_simulation, pool_summary, user_simulation,
)
from src.data_loader import load_workbook  # noqa: E402
from src.marts import file_sha256, publish_marts  # noqa: E402
from src.policy import load_policy, pool_quota_for_period  # noqa: E402
from src.reconciliation import build_reconciliation_report, require_reconciliation_passed  # noqa: E402
from src.units import compare_to_source_normalised, load_conversion_rules  # noqa: E402


class BuildBlockedError(RuntimeError):
    """The period was validated but could not safely be published."""


def _latest_period(*frames: pd.DataFrame) -> str:
    values: list[pd.Timestamp] = []
    for frame in frames:
        if frame.empty or "Month" not in frame.columns:
            continue
        parsed = pd.to_datetime(frame["Month"].astype(str), format="%b'%y", errors="coerce").dropna()
        values.extend(parsed.tolist())
    if not values:
        raise ValueError("No valid reporting months were found in Enterprise or Searah usage.")
    latest = max(values)
    return latest.strftime("%Y-%m")


def _period_filter(frame: pd.DataFrame, period: str) -> pd.DataFrame:
    if frame.empty or "Month" not in frame.columns:
        return frame.copy()
    month_dates = pd.to_datetime(frame["Month"].astype(str), format="%b'%y", errors="coerce")
    cutoff = pd.Period(period, freq="M").end_time
    return frame.loc[month_dates <= cutoff].copy().reset_index(drop=True)


def _append_control(rows: list[dict[str, Any]], check: str, scope: str,
                    expected: float | None, actual: float | None, *, tolerance: float = 0.1,
                    status_override: str | None = None, detail: str = "") -> None:
    difference = None if expected is None or actual is None else float(actual) - float(expected)
    if status_override:
        status = status_override
    elif difference is None:
        status = "NOT AVAILABLE"
    else:
        status = "PASS" if abs(difference) <= tolerance else "FAIL"
    rows.append({
        "Check": check, "Scope": scope, "Expected": expected, "Actual": actual,
        "Difference": difference, "Status": status, "Detail": detail,
    })


def _conversion_audit(data: dict[str, Any], rules: list, tolerance: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    audits = []
    for pool_name in ("sim", "searah"):
        frame = data.get(pool_name, pd.DataFrame())
        if frame.empty:
            continue
        audit = compare_to_source_normalised(frame, rules, tolerance=tolerance)
        audit.insert(0, "Pool", "Enterprise" if pool_name == "sim" else "Searah")
        audits.append(audit)
    full = pd.concat(audits, ignore_index=True) if audits else pd.DataFrame()
    if full.empty:
        summary = pd.DataFrame(columns=[
            "Pool", "Unit", "Rule Version", "Rule Status", "Rows",
            "Raw Hours", "Calculated Normalised Hours", "Source Normalised Hours",
            "Absolute Difference",
        ])
    else:
        summary = (full.groupby(["Pool", "Unit", "Rule Version", "Rule Status"], dropna=False)
                   .agg(Rows=("Unit", "size"), Raw_Hours=("Hours", "sum"),
                        Calculated_Normalised_Hours=("Calculated Normalised Hours", "sum"),
                        Source_Normalised_Hours=("Source Normalised Hours", "sum"),
                        Absolute_Difference=("Difference", lambda values: float(values.abs().sum()))
                        ).reset_index()
                   .rename(columns={
                       "Raw_Hours": "Raw Hours",
                       "Calculated_Normalised_Hours": "Calculated Normalised Hours",
                       "Source_Normalised_Hours": "Source Normalised Hours",
                       "Absolute_Difference": "Absolute Difference",
                   }))
    return full, summary


def _build_id(source_sha: str, policy_sha: str, rules_sha: str, period: str) -> str:
    payload = "|".join((source_sha, policy_sha, rules_sha, period))
    return sha256(payload.encode("utf-8")).hexdigest()[:24]


def _quarantine(output_root: Path, period: str, build_id: str,
                report: pd.DataFrame, conversion_summary: pd.DataFrame,
                metadata: dict[str, Any]) -> Path:
    destination = output_root / "_quarantine" / period / build_id
    destination.mkdir(parents=True, exist_ok=True)
    report.to_csv(destination / "reconciliation.csv", index=False, encoding="utf-8")
    conversion_summary.to_csv(destination / "conversion_audit_summary.csv", index=False, encoding="utf-8")
    payload = {
        **metadata,
        "period": period,
        "build_id": build_id,
        "publication_status": "blocked",
        "blocked_at_utc": datetime.now(timezone.utc).isoformat(),
        "failed_or_unavailable_checks": int((~report["Status"].isin(["PASS", "NOT APPLICABLE"])).sum()),
        "check_count": int(len(report)),
    }
    (destination / "quarantine.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return destination


def build_period(source: str | Path, *, period: str | None = None,
                 policy_path: str | Path = ROOT / "config" / "policy.yaml",
                 rules_path: str | Path = ROOT / "config" / "unit_conversion.csv",
                 output_root: str | Path = ROOT / "data" / "processed",
                 tolerance: float = 0.1) -> Path:
    """Validate, reconcile and publish a single month-end snapshot.

    The source workbook is treated as immutable input. A snapshot-level allocation
    pivot is not used to manufacture historical months: the requested period must
    be the latest month in the extract.
    """
    source_path = Path(source).resolve()
    output = Path(output_root).resolve()
    policy = load_policy(policy_path)
    rules = load_conversion_rules(rules_path)
    data = load_workbook(source_path)

    inferred_period = _latest_period(data["sim"], data["searah"])
    selected_period = period or inferred_period
    if selected_period != inferred_period:
        raise ValueError(
            f"This workbook is a month-end snapshot for {inferred_period}; "
            f"cannot rebuild an earlier period {selected_period} from its current allocation pivots."
        )
    if len(selected_period) != 7 or selected_period[4] != "-":
        raise ValueError(f"Period must use YYYY-MM format, received {selected_period!r}.")
    if int(selected_period[:4]) != int(policy["period"]):
        raise ValueError(
            f"Reporting period {selected_period} does not match policy year {policy['period']}."
        )

    source_sha = data["source_sha256"]
    policy_sha = policy["_source_sha256"]
    rules_sha = file_sha256(rules_path)
    build_id = _build_id(source_sha, policy_sha, rules_sha, selected_period)

    data["sim"] = _period_filter(data["sim"], selected_period)
    data["searah"] = _period_filter(data["searah"], selected_period)
    conversion_audit, conversion_summary = _conversion_audit(data, rules, tolerance)

    reconciliation = build_reconciliation_report(data, policy, selected_period)
    rows = reconciliation.to_dict("records")

    # A conversion match is necessary but not approval. A rule needs a named
    # owner, role, approval date and evidence reference before publication.
    if conversion_audit.empty:
        _append_control(rows, "Unit conversion audit availability", "All pools", None, None,
                        status_override="NOT AVAILABLE", detail="No usage rows were available for conversion audit.")
    else:
        all_match = bool(conversion_audit["Matches Source"].all())
        _append_control(
            rows, "Calculated conversion vs workbook normalised hours", "Enterprise + Searah",
            int(len(conversion_audit)), int(conversion_audit["Matches Source"].sum()),
            status_override="PASS" if all_match else "FAIL",
            detail=f"Tolerance: {tolerance:g} normalised hours per source row.",
        )
        used_units = set(conversion_audit["Unit"].astype(str).str.casefold())
        used_rules = [rule for rule in rules if rule.unit.casefold() in used_units]
        fully_approved = bool(used_rules) and all(
            rule.status == "approved" and rule.approved_by and rule.approval_role
            and rule.approval_date and rule.approval_evidence
            for rule in used_rules
        )
        _append_control(
            rows, "Unit conversion owner approval", "Used conversion rules",
            len(used_rules), sum(1 for rule in used_rules if rule.status == "approved"
                                 and rule.approved_by and rule.approval_role
                                 and rule.approval_date and rule.approval_evidence),
            status_override="PASS" if fully_approved else "BLOCKED",
            detail="All used factors need recorded source-owner approval, role, date and evidence.",
        )

    policy_approved = policy.get("status") == "approved" and all(
        str(policy.get("approval", {}).get(key, "")).strip()
        for key in ("approved_by", "approved_role", "approved_at", "approval_reference")
    )
    _append_control(
        rows, "Policy approval", policy["policy_version"], 1,
        1 if policy_approved else 0,
        status_override="PASS" if policy_approved else "BLOCKED",
        detail="Policy thresholds and entitlements remain proposals until the accountable owner records approval.",
    )
    reconciliation = pd.DataFrame(rows)
    data["reconciliation"] = reconciliation

    metadata = {
        "source_file": source_path.name,
        "source_sha256": source_sha,
        "policy_version": policy["policy_version"],
        "policy_status": policy["status"],
        "policy_sha256": policy_sha,
        "conversion_rules_sha256": rules_sha,
    }
    try:
        require_reconciliation_passed(reconciliation)
    except Exception as exc:
        quarantine_dir = _quarantine(output, selected_period, build_id, reconciliation,
                                     conversion_summary, metadata)
        raise BuildBlockedError(
            f"Period {selected_period} was quarantined; no published mart or latest pointer was changed. "
            f"Review {quarantine_dir / 'reconciliation.csv'}. {exc}"
        ) from exc

    # Publication only uses the approved, calculated normalised values.
    for key in ("sim", "searah"):
        frame = data[key]
        if frame.empty:
            continue
        approved_audit = compare_to_source_normalised(frame, rules, tolerance=tolerance)
        frame = frame.copy()
        frame["Source Hours per User"] = frame["Hours per User"]
        frame["Hours per User"] = approved_audit["Calculated Normalised Hours"].to_numpy()
        frame["Rule Version"] = approved_audit["Rule Version"].to_numpy()
        frame["Rule Status"] = approved_audit["Rule Status"].to_numpy()
        data[key] = frame

    data["monthly"] = monthly_simulation(data["sim"])
    data["searah_monthly"] = monthly_simulation(data["searah"])
    data["user_ledger"] = user_simulation(data["sim"])
    data["department_ledger"] = department_simulation(data["sim"])

    department_ledger = data["allocation"].copy()
    department_ledger["Utilisation (%)"] = (
        pd.to_numeric(department_ledger["Consumed (Hrs) Final"], errors="coerce")
        / pd.to_numeric(department_ledger["Quota (Hrs)"], errors="coerce") * 100.0
    )
    alert_policy = policy["alerts"]["department_utilization"]
    amber = float(alert_policy["amber_percent"])
    red = float(alert_policy["red_percent"])
    department_ledger["Policy Status"] = department_ledger["Utilisation (%)"].apply(
        lambda value: "RED" if pd.notna(value) and value >= red
        else "AMBER" if pd.notna(value) and value >= amber
        else "WITHIN POLICY" if pd.notna(value) else "NO QUOTA"
    )
    data["department_ledger_derived"] = department_ledger

    searah_quota = pool_quota_for_period(policy, "searah", selected_period)
    data["pool_ledger"] = pool_summary(
        data["sim"], data["searah"],
        enterprise_quota=pool_quota_for_period(policy, "enterprise", selected_period),
        searah_quota=searah_quota,
    )
    data["conversion_audit"] = conversion_summary

    manifest_path = publish_marts(
        data, output, selected_period, build_id,
        {
            "source_file": source_path.name,
            "source_sha256": source_sha,
            "policy_version": policy["policy_version"],
            "policy_sha256": policy_sha,
            "conversion_rules_sha256": rules_sha,
            "enterprise_normalised_hours": float(data["sim"]["Hours per User"].sum()),
            "searah_normalised_hours": float(data["searah"]["Hours per User"].sum())
                if not data["searah"].empty else 0.0,
            "reconciliation_status": "PASS",
            "conversion_rule_versions": sorted(set(data["sim"].get("Rule Version", pd.Series(dtype=str)).dropna().astype(str))),
        },
    )
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and publish a DELFI monthly period to Parquet marts.")
    parser.add_argument("--source", required=True, help="Path to the confidential source workbook.")
    parser.add_argument("--period", help="Month-end period YYYY-MM. Defaults to the latest month in the workbook.")
    parser.add_argument("--policy", default=str(ROOT / "config" / "policy.yaml"))
    parser.add_argument("--rules", default=str(ROOT / "config" / "unit_conversion.csv"))
    parser.add_argument("--output", default=str(ROOT / "data" / "processed"))
    parser.add_argument("--tolerance", type=float, default=0.1)
    args = parser.parse_args(argv)
    try:
        manifest = build_period(
            args.source, period=args.period, policy_path=args.policy, rules_path=args.rules,
            output_root=args.output, tolerance=args.tolerance,
        )
    except BuildBlockedError as exc:
        print(f"BUILD BLOCKED: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"BUILD FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"PUBLISHED: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
