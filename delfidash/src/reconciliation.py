"""Policy-driven reconciliation and hard publication gates."""
from __future__ import annotations

from typing import Any

import pandas as pd

from .analytics import monthly_simulation, reconcile_allocations
from .policy import pool_quota_for_period


class ReconciliationBlocked(RuntimeError):
    """Raised when mandatory reconciliation checks fail or are unavailable."""


def _control(check: str, scope: str, expected: float | None, actual: float | None,
             *, tolerance: float = 0.1, unavailable_reason: str | None = None) -> dict[str, Any]:
    if expected is None or actual is None:
        status = "NOT AVAILABLE"
        difference = None
    else:
        difference = float(actual) - float(expected)
        status = "PASS" if abs(difference) <= tolerance else "FAIL"
    return {
        "Check": check, "Scope": scope, "Expected": expected, "Actual": actual,
        "Difference": difference, "Status": status,
        "Detail": unavailable_reason or "",
    }


def build_reconciliation_report(data: dict[str, Any], policy: dict[str, Any], period: str) -> pd.DataFrame:
    """Reconcile source pivots to normalized facts using policy-supplied quotas.

    Enterprise and Searah remain separate. Searah summary differences are not
    silently treated as ordinary usage: the workbook's free-text transfer notes
    are not an approved structured adjustment ledger.
    """
    enterprise_quota = pool_quota_for_period(policy, "enterprise", period)
    searah_quota = pool_quota_for_period(policy, "searah", period)
    if enterprise_quota is None:
        raise ReconciliationBlocked(f"Enterprise entitlement is not effective for reporting period {period}.")

    enterprise = data.get("sim", pd.DataFrame()).copy()
    searah = data.get("searah", pd.DataFrame()).copy()
    allocation = data.get("allocation", pd.DataFrame())
    if enterprise.empty:
        raise ReconciliationBlocked("Enterprise simulation fact sheet is empty.")
    if allocation.empty:
        raise ReconciliationBlocked("Enterprise department allocation pivot is unavailable.")

    report = reconcile_allocations(
        allocation,
        enterprise,
        expected_enterprise_quota=enterprise_quota,
        expected_enterprise_consumption=data.get("enterprise", {}).get("Consumed (Hrs)"),
    )
    rows = report.to_dict("records")

    enterprise_summary = data.get("enterprise", {})
    rows.append(_control(
        "Enterprise summary quota vs policy", "Enterprise", enterprise_quota,
        enterprise_summary.get("Quota (Hrs)"),
        unavailable_reason="Enterprise summary row was not parsed." if enterprise_summary.get("Quota (Hrs)") is None else None,
    ).copy())
    if enterprise_summary.get("Consumed (Hrs)") is None:
        rows.append(_control(
            "Enterprise summary consumption", "Enterprise", None, None,
            unavailable_reason="Enterprise summary consumed total was not parsed.",
        ))

    # Reconcile each monthly user pivot total to the raw Enterprise facts.
    user_monthly = data.get("user_monthly", pd.DataFrame())
    if user_monthly.empty:
        rows.append(_control(
            "Monthly user pivot tie-out", period, None, None,
            unavailable_reason="Monthly user pivot is unavailable.",
        ))
    else:
        fact_monthly = monthly_simulation(enterprise).set_index("Month")["Hours"].to_dict()
        month_cols = [c for c in user_monthly.columns if c.endswith("'26")]
        months_checked = 0
        for month in month_cols:
            try:
                month_date = pd.to_datetime(month, format="%b'%y")
            except ValueError:
                continue
            if month_date.strftime("%Y-%m") > period:
                continue
            pivot_total = pd.to_numeric(user_monthly[month], errors="coerce").sum(min_count=1)
            fact_total = fact_monthly.get(month)
            rows.append(_control("Monthly user pivot tie-out", month,
                                 float(pivot_total) if pd.notna(pivot_total) else None,
                                 float(fact_total) if fact_total is not None else None))
            months_checked += 1
        if months_checked == 0:
            rows.append(_control(
                "Monthly user pivot tie-out", period, None, None,
                unavailable_reason="No monthly pivot months were available for the selected period.",
            ))

    duplicate_count = int(data.get("duplicate_enterprise_rows", 0))
    rows.append({
        "Check": "Duplicate Enterprise fact rows", "Scope": "Enterprise",
        "Expected": 0, "Actual": duplicate_count, "Difference": duplicate_count,
        "Status": "PASS" if duplicate_count == 0 else "FAIL",
        "Detail": "Exact duplicate source rows are preserved and block publication pending review.",
    })

    # The dedicated Searah entitlement starts in July 2026. Before then it is
    # explicitly out of scope, rather than shown as a zero-consumption pool.
    if searah_quota is None:
        rows.append({
            "Check": "Searah policy effective date", "Scope": period,
            "Expected": None, "Actual": None, "Difference": None,
            "Status": "NOT APPLICABLE",
            "Detail": "The Searah allocation is not effective in this reporting period.",
        })
    else:
        summary = data.get("searah_summary", {})
        if searah.empty:
            rows.append(_control(
                "Searah source fact availability", "Searah", 0.0, None,
                unavailable_reason="Searah is effective in this period but its source fact sheet is missing.",
            ))
        else:
            raw_searah_total = float(pd.to_numeric(searah["Hours per User"], errors="raise").sum())
            searah_summary_total = summary.get("Consumed (Hrs)")
            if searah_summary_total is None:
                rows.append(_control(
                    "Searah summary tie-out", "Searah", None, raw_searah_total,
                    unavailable_reason="Searah summary total was not parsed.",
                ))
            elif abs(float(searah_summary_total) - raw_searah_total) <= 0.1:
                rows.append(_control("Searah summary tie-out", "Searah",
                                     float(searah_summary_total), raw_searah_total))
            else:
                rows.append({
                    "Check": "Searah summary tie-out", "Scope": "Searah",
                    "Expected": float(searah_summary_total), "Actual": raw_searah_total,
                    "Difference": raw_searah_total - float(searah_summary_total),
                    "Status": "NOT AVAILABLE",
                    "Detail": "The summary may include transfers from Enterprise. The workbook records these in free text, not a structured, approved adjustment ledger; do not force a tie-out.",
                })
            rows.append(_control(
                "Searah summary quota vs policy", "Searah", searah_quota,
                summary.get("Quota (Hrs)"),
                unavailable_reason="Searah summary quota was not parsed." if summary.get("Quota (Hrs)") is None else None,
            ))
        duplicates = int(data.get("duplicate_searah_rows", 0))
        rows.append({
            "Check": "Duplicate Searah fact rows", "Scope": "Searah",
            "Expected": 0, "Actual": duplicates, "Difference": duplicates,
            "Status": "PASS" if duplicates == 0 else "FAIL",
            "Detail": "Exact duplicate source rows are preserved and block publication pending review.",
        })
    return pd.DataFrame(rows)


def require_reconciliation_passed(report: pd.DataFrame) -> None:
    acceptable = {"PASS", "NOT APPLICABLE"}
    if report.empty:
        raise ReconciliationBlocked("Reconciliation report is empty; publishing is blocked.")
    status = report["Status"] if "Status" in report.columns else pd.Series("MISSING", index=report.index)
    if not status.isin(acceptable).all():
        failed = report.loc[~status.isin(acceptable)].to_dict("records")
        raise ReconciliationBlocked(
            f"Reconciliation failed or contains unavailable controls; publishing is blocked. "
            f"Outstanding checks: {failed[:12]!r}"
        )
