"""Versioned policy loading and publication gates."""
from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml


class PolicyError(ValueError):
    """Invalid, incomplete or unapproved policy configuration."""


def load_policy(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise PolicyError(f"Policy file not found: {source}")
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PolicyError(f"Could not read policy file {source}: {exc}") from exc
    if not isinstance(raw, dict):
        raise PolicyError("Policy root must be a YAML mapping.")
    if raw.get("schema_version") != 1:
        raise PolicyError(f"Unsupported policy schema_version: {raw.get('schema_version')!r}.")
    if not str(raw.get("policy_version", "")).strip():
        raise PolicyError("Policy requires a non-empty policy_version.")
    if raw.get("status") not in {"proposed", "approved", "retired"}:
        raise PolicyError("Policy status must be proposed, approved or retired.")
    year = raw.get("period")
    if not isinstance(year, int) or not 2000 <= year <= 2100:
        raise PolicyError("Policy period must be a four-digit reporting year.")

    pools = raw.get("pools")
    if not isinstance(pools, dict) or "enterprise" not in pools or "searah" not in pools:
        raise PolicyError("Policy must define separate Enterprise and Searah pools.")
    for pool_name, pool in pools.items():
        if not isinstance(pool, dict):
            raise PolicyError(f"Pool {pool_name!r} must be a mapping.")
        quota = pool.get("quota_hours")
        if not isinstance(quota, (int, float)) or isinstance(quota, bool) or quota <= 0:
            raise PolicyError(f"Pool {pool_name!r} requires a positive quota_hours value.")
        if pool.get("unit") != "normalized_hours":
            raise PolicyError(f"Pool {pool_name!r} must use normalized_hours.")
        try:
            effective_from = date.fromisoformat(str(pool["effective_from"]))
            effective_to = date.fromisoformat(str(pool["effective_to"])) if pool.get("effective_to") else None
        except (KeyError, ValueError) as exc:
            raise PolicyError(f"Pool {pool_name!r} has an invalid effective date.") from exc
        if effective_to and effective_to < effective_from:
            raise PolicyError(f"Pool {pool_name!r} effective_to precedes effective_from.")

    alerts = raw.get("alerts")
    if not isinstance(alerts, dict):
        raise PolicyError("Policy requires an alerts mapping.")
    for rule_name, rule in alerts.items():
        if not isinstance(rule, dict):
            raise PolicyError(f"Alert rule {rule_name!r} must be a mapping.")
        for threshold in ("amber_percent", "red_percent", "threshold_percent"):
            if threshold in rule and not 0 <= float(rule[threshold]) <= 1000:
                raise PolicyError(f"Alert {rule_name!r} has invalid {threshold}.")

    approval = raw.get("approval") or {}
    if not isinstance(approval, dict):
        raise PolicyError("Policy approval must be a mapping.")
    if raw["status"] == "approved":
        required = ("approved_by", "approved_role", "approved_at", "approval_reference")
        missing = [key for key in required if not str(approval.get(key, "")).strip()]
        if missing:
            raise PolicyError(f"Approved policy is missing approval evidence: {missing}.")
        try:
            date.fromisoformat(str(approval["approved_at"])[:10])
        except ValueError as exc:
            raise PolicyError("Policy approval.approved_at must be an ISO date or timestamp.") from exc
    raw["_source_path"] = str(source.resolve())
    raw["_source_sha256"] = sha256(source.read_bytes()).hexdigest()
    return raw


def require_policy_approved(policy: dict[str, Any]) -> None:
    if policy.get("status") != "approved":
        raise PolicyError(
            f"Policy {policy.get('policy_version')!r} is {policy.get('status')!r}; "
            "a source-owner-approved policy is required to publish analytical marts."
        )
    approval = policy.get("approval") or {}
    required = ("approved_by", "approved_role", "approved_at", "approval_reference")
    missing = [key for key in required if not str(approval.get(key, "")).strip()]
    if missing:
        raise PolicyError(f"Policy approval evidence is incomplete: {missing}.")


def pool_quota_for_period(policy: dict[str, Any], pool_name: str, period: str) -> float | None:
    try:
        period_date = date.fromisoformat(period + "-01")
    except ValueError as exc:
        raise PolicyError(f"Period must be YYYY-MM, received {period!r}.") from exc
    pool = policy["pools"][pool_name]
    start = date.fromisoformat(str(pool["effective_from"]))
    end = date.fromisoformat(str(pool["effective_to"])) if pool.get("effective_to") else None
    if period_date < start or (end is not None and period_date > end):
        return None
    return float(pool["quota_hours"])
