"""Atomic, hash-verified Parquet marts for Streamlit read-only access."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import uuid
from typing import Any

import pandas as pd


class PublishedMartNotFound(FileNotFoundError):
    """Raised when no verified published period exists."""


DATASET_FILES = {
    "sim": "enterprise_usage.parquet",
    "searah": "searah_usage.parquet",
    "vm": "vm_activity.parquet",
    "profiles": "profile_activity.parquet",
    "top": "top_user_activity.parquet",
    "rejected": "rejected_sessions.parquet",
    "users": "user_reference.parquet",
    "allocation": "department_ledger.parquet",
    "user_monthly": "user_monthly.parquet",
    "monthly": "enterprise_monthly.parquet",
    "searah_monthly": "searah_monthly.parquet",
    "user_ledger": "user_ledger.parquet",
    "department_usage": "department_usage.parquet",
    "conversion_audit": "conversion_audit_summary.parquet",
    "pool_ledger": "pool_ledger.parquet",
}


def file_sha256(path: str | Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def publish_marts(data: dict[str, Any], output_root: str | Path, period: str,
                  build_id: str, manifest_metadata: dict[str, Any]) -> Path:
    """Write all marts to a staging directory and atomically publish a manifest."""
    root = Path(output_root).resolve()
    period_root = root / period
    destination = period_root / build_id
    if destination.exists():
        manifest_path = destination / "manifest.json"
        if manifest_path.is_file():
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            if existing.get("build_id") == build_id and existing.get("publication_status") == "published":
                return manifest_path
        raise RuntimeError(f"Build destination already exists but is not a valid published build: {destination}")

    period_root.mkdir(parents=True, exist_ok=True)
    staging = period_root / f".staging-{uuid.uuid4().hex}"
    staging.mkdir()
    dataset_meta: dict[str, dict[str, Any]] = {}
    metadata = {
        key: data.get(key) for key in (
            "source_file", "source_sha256", "sheet_names", "missing_optional_sheets",
            "duplicate_enterprise_rows", "duplicate_searah_rows", "enterprise", "searah_summary",
        )
    }
    try:
        for key, filename in DATASET_FILES.items():
            frame = data.get(key)
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                continue
            target = staging / filename
            frame.to_parquet(target, index=False, engine="pyarrow")
            dataset_meta[key] = {
                "file": filename,
                "sha256": file_sha256(target),
                "rows": int(len(frame)),
                "columns": list(frame.columns),
            }

        metadata_path = staging / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
        reconciliation = data.get("reconciliation")
        if isinstance(reconciliation, pd.DataFrame):
            reconciliation.to_csv(staging / "reconciliation.csv", index=False, encoding="utf-8")

        manifest = {
            **manifest_metadata,
            "manifest_version": 1,
            "period": period,
            "build_id": build_id,
            "publication_status": "published",
            "built_at_utc": datetime.now(timezone.utc).isoformat(),
            "datasets": dataset_meta,
            "metadata_sha256": file_sha256(metadata_path),
            "reconciliation_sha256": file_sha256(staging / "reconciliation.csv")
                if (staging / "reconciliation.csv").exists() else None,
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
        os.replace(staging, destination)

        latest_tmp = period_root / f".latest-{uuid.uuid4().hex}.tmp"
        latest_tmp.write_text(json.dumps({"build_id": build_id}, indent=2), encoding="utf-8")
        os.replace(latest_tmp, period_root / "latest.json")
        return destination / "manifest.json"
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _resolve_build(root: Path, period: str | None) -> tuple[Path, dict[str, Any]]:
    if period is not None:
        periods = [period]
    else:
        periods = sorted(
            [p.name for p in root.iterdir() if p.is_dir() and (p / "latest.json").is_file()],
            reverse=True,
        ) if root.exists() else []
    for candidate in periods:
        latest_path = root / candidate / "latest.json"
        if not latest_path.is_file():
            continue
        try:
            pointer = json.loads(latest_path.read_text(encoding="utf-8"))
            build_id = str(pointer["build_id"])
            if not build_id or "/" in build_id or "\\" in build_id or build_id.startswith("."):
                raise ValueError("Invalid build id in latest pointer.")
            build_dir = (root / candidate / build_id).resolve()
            if not build_dir.is_relative_to(root.resolve()):
                raise ValueError("Published build path escapes the mart root.")
            manifest_path = build_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("publication_status") != "published":
                raise ValueError("Manifest is not published.")
            if manifest.get("build_id") != build_id or manifest.get("period") != candidate:
                raise ValueError("Latest pointer and manifest do not agree.")
            return build_dir, manifest
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
            raise PublishedMartNotFound(f"Published period {candidate!r} is invalid: {exc}") from exc
    raise PublishedMartNotFound(
        f"No published marts found under {root}. Run jobs/build_period.py after the data and approval gates pass."
    )


def load_published_period(output_root: str | Path, period: str | None = None) -> dict[str, Any]:
    """Load only a published manifest whose Parquet files pass SHA-256 verification."""
    root = Path(output_root).resolve()
    build_dir, manifest = _resolve_build(root, period)
    metadata_path = build_dir / "metadata.json"
    if file_sha256(metadata_path) != manifest.get("metadata_sha256"):
        raise PublishedMartNotFound("Published metadata SHA-256 does not match the manifest.")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    result: dict[str, Any] = {key: pd.DataFrame() for key in DATASET_FILES}
    for key, descriptor in manifest.get("datasets", {}).items():
        if key not in DATASET_FILES:
            raise PublishedMartNotFound(f"Manifest contains unknown dataset key {key!r}.")
        file_path = (build_dir / descriptor["file"]).resolve()
        if not file_path.is_relative_to(build_dir.resolve()) or not file_path.is_file():
            raise PublishedMartNotFound(f"Dataset file for {key!r} is missing or outside the build directory.")
        if file_sha256(file_path) != descriptor.get("sha256"):
            raise PublishedMartNotFound(f"Dataset SHA-256 mismatch for {key!r}.")
        frame = pd.read_parquet(file_path, engine="pyarrow")
        if len(frame) != descriptor.get("rows"):
            raise PublishedMartNotFound(f"Dataset row-count mismatch for {key!r}.")
        result[key] = frame
    result.update(metadata)
    result["build_metadata"] = manifest
    result["reconciliation"] = pd.read_csv(build_dir / "reconciliation.csv") if (build_dir / "reconciliation.csv").exists() else pd.DataFrame()
    return result
