import json

import pytest

from src.marts import PublishedMartNotFound, load_published_period


def test_parquet_file_hash_is_checked_before_reading(approved_build_inputs):
    inputs = approved_build_inputs
    from jobs.build_period import build_period
    manifest_path = build_period(inputs["source"], policy_path=inputs["policy"],
                                 rules_path=inputs["rules"], output_root=inputs["output"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mart_file = manifest_path.parent / manifest["datasets"]["sim"]["file"]
    mart_file.write_bytes(mart_file.read_bytes() + b"tampered")
    with pytest.raises(PublishedMartNotFound, match="SHA-256 mismatch"):
        load_published_period(inputs["output"], "2026-01")
