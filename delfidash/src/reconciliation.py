"""Small orchestration helpers for publishing a validated utilisation period."""
from __future__ import annotations

from typing import Any
import pandas as pd

from .analytics import reconcile_allocations


class ReconciliationBlocked(RuntimeError):
    """Raised when mandatory reconciliation checks fail."""


def build_reconciliation_report(data: dict[str, Any], *, expected_enterprise_quota: float = 211_200.0,
                                expected_enterprise_consumption: float | None = None) -> pd.DataFrame:
    """Run Enterprise-only allocation checks and return auditable check rows."""
    allocation = data.get("allocation", pd.DataFrame())
    if allocation.empty:
        raise ReconciliationBlocked("Enterprise department allocation table is unavailable; period cannot be reconciled.")
    return reconcile_allocations(allocation, data["sim"], expected_enterprise_quota,
                                 expected_enterprise_consumption)


def require_reconciliation_passed(report: pd.DataFrame) -> None:
    acceptable = {"PASS", "NOT APPLICABLE"}
    if report.empty:
        raise ReconciliationBlocked("Reconciliation report is empty; publishing is blocked.")
    status = report["Status"] if "Status" in report.columns else pd.Series("MISSING", index=report.index)
    if not status.isin(acceptable).all():
        failed = report.loc[~status.isin(acceptable)].to_dict("records")
        raise ReconciliationBlocked(f"Reconciliation failed; publishing is blocked. Failed checks: {failed[:10]!r}")
