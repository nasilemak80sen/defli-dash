from pathlib import Path

import pytest
import yaml

from src.policy import PolicyError, load_policy, pool_quota_for_period, require_policy_approved

CONFIG = Path(__file__).parents[1] / "config" / "policy.yaml"


def test_current_policy_remains_proposed_until_owner_signoff():
    policy = load_policy(CONFIG)
    assert policy["status"] == "proposed"
    assert policy["pools"]["enterprise"]["quota_hours"] == 211200
    assert policy["pools"]["searah"]["quota_hours"] == 15000
    with pytest.raises(PolicyError, match="source-owner-approved policy"):
        require_policy_approved(policy)


def test_policy_searah_effective_date_is_respected():
    policy = load_policy(CONFIG)
    assert pool_quota_for_period(policy, "searah", "2026-06") is None
    assert pool_quota_for_period(policy, "searah", "2026-07") == 15000
    assert pool_quota_for_period(policy, "enterprise", "2026-01") == 211200


def test_approved_policy_requires_approval_metadata(tmp_path):
    policy = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    policy["status"] = "approved"
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(policy), encoding="utf-8")
    with pytest.raises(PolicyError, match="approval evidence"):
        load_policy(path)


def test_approved_policy_with_evidence_passes(tmp_path):
    policy = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    policy["status"] = "approved"
    policy["approval"] = {
        "approved_by": "Source Owner",
        "approved_role": "Platform Owner",
        "approved_at": "2026-10-30",
        "approval_reference": "CHG-123",
    }
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(policy), encoding="utf-8")
    loaded = load_policy(path)
    require_policy_approved(loaded)


def test_policy_rejects_invalid_effective_date(tmp_path):
    policy = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    policy["pools"]["searah"]["effective_to"] = "2026-01-01"
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(policy), encoding="utf-8")
    with pytest.raises(PolicyError, match="precedes"):
        load_policy(path)
