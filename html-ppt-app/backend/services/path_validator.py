"""Phase 5H: Path validator — checks storage keys and local paths for correctness.

Two main entry points:
  - validate_job_paths(job) → dict    (checks DB columns, no I/O)
  - validate_storage_objects(job, storage_client) → dict  (checks S3/local existence)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, TYPE_CHECKING

from services.path_contract import (
    ArtifactType, ALL_ARTIFACT_TYPES,
    get_storage_key, artifact_filename,
    storage_key_attr_to_artifact_type,
    REQUIRED_SUCCESS_ARTIFACTS,
)

if TYPE_CHECKING:
    from models import Job
    from services.storage.storage_client import StorageClient


# ── Validation helpers ──────────────────────────────────────────────────

def _validate_key(key: str | None, job_id: str) -> list[str]:
    """Validate a single storage key. Returns list of error strings."""
    errors: list[str] = []
    if not key:
        return errors

    # 1. Must match jobs/{job_id}/... pattern
    prefix = f"jobs/{job_id}/"
    if not key.startswith(prefix):
        errors.append(f"Key does not start with '{prefix}': {key}")
        return errors

    # 2. No backslashes
    if "\\" in key:
        errors.append(f"Key contains backslash: {key}")

    # 3. No path traversal
    if ".." in key:
        errors.append(f"Key contains '..': {key}")

    # 4. Must not start with /
    if key.startswith("/"):
        errors.append(f"Key starts with '/': {key}")

    # 5. Must not contain http:// or https://
    if "http://" in key or "https://" in key:
        errors.append(f"Key contains URL: {key}")

    # 6. Must not contain /tmp/ or backend/outputs
    if "/tmp/" in key or "backend/outputs" in key:
        errors.append(f"Key contains local temp/output path: {key}")

    # 7. Job ID in key must match job.id
    # Extract job_id from key: jobs/{job_id}/filename
    match = re.match(r"^jobs/([^/]+)/.+$", key)
    if match:
        key_job_id = match.group(1)
        if key_job_id != job_id:
            errors.append(f"Key job_id '{key_job_id}' does not match job.id '{job_id}'")

    # 8. Filename must be a known artifact type
    filename = key.split("/")[-1]
    from services.path_contract import filename_to_artifact_type
    at = filename_to_artifact_type(filename)
    if at is None:
        errors.append(f"Key has unknown filename: {filename}")

    return errors


def _validate_local_path(path: str | None, job_id: str) -> list[str]:
    """Validate a local path stored in DB. Returns list of warning strings."""
    warnings: list[str] = []
    if not path:
        return warnings

    # Storage keys stored in local path columns → warning
    if path.startswith("jobs/"):
        warnings.append(f"Local path column contains storage key: {path}")

    # Backslashes on any platform → warning (should use forward slash)
    if "\\" in path:
        warnings.append(f"Path contains backslash: {path}")

    # Relative paths starting with ../../ → warning
    if path.startswith(".."):
        warnings.append(f"Path is relative (..): {path}")

    # URLs in path → error
    if "http://" in path or "https://" in path:
        warnings.append(f"Path contains URL: {path}")

    return warnings


# ── Main validation functions ───────────────────────────────────────────

def validate_job_paths(job: "Job") -> dict[str, Any]:
    """Validate all path-related fields on a Job.

    Returns: {
        "status": "pass" | "warning" | "fail",
        "errors": [str, ...],
        "warnings": [str, ...],
        "checks": {attr: "ok"|"missing"|"invalid", ...},
    }
    """
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, str] = {}

    jid = job.id

    # 1. Validate all storage key columns
    for attr_name, artifact_type in [
        ("index_html_key", "index_html"),
        ("standalone_html_key", "standalone_html"),
        ("zip_key", "zip"),
        ("logs_key", "logs"),
        ("quality_report_key", "quality_report"),
        ("deck_plan_key", "deck_plan"),
        ("packed_context_key", "packed_context"),
        ("generation_prompt_key", "generation_prompt"),
        ("input_cleaned_key", "input_cleaned"),
        ("path_check_key", "path_check"),
    ]:
        key_val = getattr(job, attr_name, None)
        if key_val:
            key_errors = _validate_key(key_val, jid)
            if key_errors:
                checks[attr_name] = "invalid"
                errors.extend(key_errors)
            else:
                checks[attr_name] = "ok"
        else:
            checks[attr_name] = "missing"

    # 2. Validate local path columns
    for path_attr in ["output_dir", "index_html_path", "standalone_html_path",
                       "zip_path", "logs_path"]:
        val = getattr(job, path_attr, None)
        if val:
            pw = _validate_local_path(val, jid)
            if pw:
                checks[path_attr] = "warning"
                warnings.extend(pw)
            else:
                checks[path_attr] = "ok"
        else:
            checks[path_attr] = "missing"

    # 3. Success job must have required artifact keys
    if job.status == "success":
        for at in REQUIRED_SUCCESS_ARTIFACTS:
            attr_name = _artifact_type_to_key_attr(at)
            if attr_name:
                val = getattr(job, attr_name, None)
                if not val:
                    errors.append(f"Success job missing required key: {attr_name}")

    # 4. Failed job: if logs_key exists, it must be valid (already checked above)

    # ── Determine overall status ───────────────────────────────────────
    if errors:
        status = "fail"
    elif warnings:
        status = "warning"
    else:
        status = "pass"

    return {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
    }


def validate_storage_objects(
    job: "Job",
    storage_client: "StorageClient",
) -> dict[str, Any]:
    """Check which storage objects actually exist. Returns existence map.

    Returns: {
        "objects": {attr_name: {"key": str, "exists": bool}, ...},
        "all_exist": bool,
    }
    """
    objects: dict[str, dict[str, Any]] = {}

    for attr_name in ["index_html_key", "standalone_html_key", "zip_key",
                       "logs_key", "quality_report_key", "deck_plan_key",
                       "packed_context_key", "generation_prompt_key",
                       "input_cleaned_key", "path_check_key"]:
        key = getattr(job, attr_name, None)
        if key:
            exists = storage_client.object_exists(key)
            objects[attr_name] = {"key": key, "exists": exists}
        else:
            objects[attr_name] = {"key": None, "exists": False}

    # For success jobs, check required objects exist
    all_exist = True
    if job.status == "success":
        for at in REQUIRED_SUCCESS_ARTIFACTS:
            attr_name = _artifact_type_to_key_attr(at)
            if attr_name and attr_name in objects:
                if not objects[attr_name]["exists"]:
                    all_exist = False

    return {"objects": objects, "all_exist": all_exist}


def _artifact_type_to_key_attr(artifact_type: ArtifactType) -> str | None:
    """Reverse mapping from artifact_type to Job model attribute name."""
    mapping: dict[ArtifactType, str] = {
        "index_html": "index_html_key",
        "standalone_html": "standalone_html_key",
        "zip": "zip_key",
        "logs": "logs_key",
        "quality_report": "quality_report_key",
        "deck_plan": "deck_plan_key",
        "packed_context": "packed_context_key",
        "generation_prompt": "generation_prompt_key",
        "input_cleaned": "input_cleaned_key",
        "path_check": "path_check_key",
    }
    return mapping.get(artifact_type)
