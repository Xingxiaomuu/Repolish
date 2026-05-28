"""Phase 5H: Unified path contract — the single source of truth for all file paths and storage keys.

Every path and storage key MUST be generated through the functions in this module.
Manual string concatenation of paths/keys is forbidden.

Two domains:
  - Local temp paths: /tmp/htmlppt-jobs/{job_id}/{filename}  (worker scratch space)
  - Storage keys:     jobs/{job_id}/{filename}               (S3/R2 object keys)
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Literal

# ── Artifact type enum ───────────────────────────────────────────────────

ArtifactType = Literal[
    "index_html",
    "standalone_html",
    "zip",
    "logs",
    "quality_report",
    "deck_plan",
    "packed_context",
    "generation_prompt",
    "input_cleaned",
    "prompt",
    "path_check",
]

ALL_ARTIFACT_TYPES: list[ArtifactType] = [
    "index_html", "standalone_html", "zip", "logs", "quality_report",
    "deck_plan", "packed_context", "generation_prompt", "input_cleaned",
    "prompt", "path_check",
]

# Maps artifact_type → filename on disk
_ARTIFACT_FILENAMES: dict[ArtifactType, str] = {
    "index_html": "index.html",
    "standalone_html": "standalone.html",
    "zip": "{job_id}.zip",
    "logs": "logs.txt",
    "quality_report": "quality_report.json",
    "deck_plan": "deck_plan.json",
    "packed_context": "packed_context.json",
    "generation_prompt": "generation_prompt.txt",
    "input_cleaned": "input_cleaned.json",
    "prompt": "prompt.txt",
    "path_check": "path_check.json",
}

# Maps filename (as seen on disk / in storage) → artifact_type
_FILENAME_TO_ARTIFACT: dict[str, ArtifactType] = {
    "index.html": "index_html",
    "standalone.html": "standalone_html",
    "logs.txt": "logs",
    "quality_report.json": "quality_report",
    "deck_plan.json": "deck_plan",
    "packed_context.json": "packed_context",
    "generation_prompt.txt": "generation_prompt",
    "input_cleaned.json": "input_cleaned",
    "prompt.txt": "prompt",
    "path_check.json": "path_check",
}

# Maps Job model storage-key attribute → artifact_type
_STORAGE_KEY_ATTRS: dict[str, ArtifactType] = {
    "index_html_key": "index_html",
    "standalone_html_key": "standalone_html",
    "zip_key": "zip",
    "logs_key": "logs",
    "quality_report_key": "quality_report",
    "deck_plan_key": "deck_plan",
    "packed_context_key": "packed_context",
    "generation_prompt_key": "generation_prompt",
    "input_cleaned_key": "input_cleaned",
}

# Required artifacts for a success job
REQUIRED_SUCCESS_ARTIFACTS: list[ArtifactType] = [
    "index_html", "standalone_html", "zip", "quality_report"
]


# ── Local temp paths (worker scratch space) ──────────────────────────────

def _tmp_root() -> Path:
    return Path(tempfile.gettempdir()) / "htmlppt-jobs"


def get_job_tmp_dir(job_id: str) -> Path:
    """Worker temp directory for a job: /tmp/htmlppt-jobs/{job_id}/"""
    return _tmp_root() / job_id


def get_local_path(job_id: str, artifact_type: ArtifactType) -> Path:
    """Local path for an artifact within the job temp dir."""
    filename = _ARTIFACT_FILENAMES[artifact_type]
    if artifact_type == "zip":
        # Zip lives in parent of job dir
        return get_job_tmp_dir(job_id).parent / filename.format(job_id=job_id)
    return get_job_tmp_dir(job_id) / filename


# ── Convenience accessors for local temp paths ───────────────────────────

def get_local_index_html(job_id: str) -> Path:
    return get_local_path(job_id, "index_html")

def get_local_standalone_html(job_id: str) -> Path:
    return get_local_path(job_id, "standalone_html")

def get_local_zip(job_id: str) -> Path:
    return get_local_path(job_id, "zip")

def get_local_logs(job_id: str) -> Path:
    return get_local_path(job_id, "logs")

def get_local_quality_report(job_id: str) -> Path:
    return get_local_path(job_id, "quality_report")

def get_local_deck_plan(job_id: str) -> Path:
    return get_local_path(job_id, "deck_plan")

def get_local_packed_context(job_id: str) -> Path:
    return get_local_path(job_id, "packed_context")

def get_local_generation_prompt(job_id: str) -> Path:
    return get_local_path(job_id, "generation_prompt")


# ── Storage keys (S3/R2 object keys) ─────────────────────────────────────

def get_storage_key(job_id: str, artifact_type: ArtifactType) -> str:
    """Generate the canonical S3 object key for a job artifact.

    All keys follow the pattern: jobs/{job_id}/{filename}
    """
    if artifact_type not in _ARTIFACT_FILENAMES:
        raise ValueError(f"Unknown artifact_type: {artifact_type}")
    filename = _ARTIFACT_FILENAMES[artifact_type].format(job_id=job_id)
    return f"jobs/{job_id}/{filename}"


# ── Helpers for mapping between filenames and artifact types ─────────────

def filename_to_artifact_type(filename: str) -> ArtifactType | None:
    """Convert a filename (e.g. 'index.html') to its ArtifactType."""
    # Handle zip specially — pattern is {job_id}.zip
    if filename.endswith(".zip"):
        return "zip"
    return _FILENAME_TO_ARTIFACT.get(filename)


def storage_key_attr_to_artifact_type(attr_name: str) -> ArtifactType | None:
    """Map a Job model storage-key attribute name to ArtifactType."""
    return _STORAGE_KEY_ATTRS.get(attr_name)


def artifact_filename(artifact_type: ArtifactType, job_id: str = "") -> str:
    """Return the canonical filename for an artifact type."""
    return _ARTIFACT_FILENAMES[artifact_type].format(job_id=job_id)


# ── All storage keys for a job ──────────────────────────────────────────

def all_storage_keys(job_id: str) -> dict[ArtifactType, str]:
    """Return the full set of storage keys for a job."""
    return {at: get_storage_key(job_id, at) for at in ALL_ARTIFACT_TYPES}
