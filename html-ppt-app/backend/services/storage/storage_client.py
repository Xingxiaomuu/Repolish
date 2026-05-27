"""Storage abstraction layer — local filesystem or S3-compatible object storage.

Key convention: all objects stored under ``jobs/{job_id}/{filename}``.
"""

import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from settings import settings

# ── Base class ────────────────────────────────────────────────────────────


class StorageClient(ABC):
    @abstractmethod
    def upload_file(self, local_path: Path, key: str) -> str:
        """Upload a file from local_path to storage at key. Returns the key."""

    @abstractmethod
    def upload_text(self, text: str, key: str) -> str:
        """Upload text content to storage at key. Returns the key."""

    @abstractmethod
    def download_file(self, key: str, local_path: Path) -> Path:
        """Download object at key to local_path. Returns the local path."""

    @abstractmethod
    def generate_presigned_url(self, key: str, expires_in: int = 3600, download_filename: str | None = None) -> str:
        """Generate a time-limited download URL. If download_filename is set, the URL
        will include Content-Disposition: attachment headers to force download."""

    @abstractmethod
    def object_exists(self, key: str) -> bool:
        """Check whether an object exists at key."""

    @abstractmethod
    def delete_object(self, key: str) -> None:
        """Delete the object at key."""

    @abstractmethod
    def health_check(self) -> tuple[bool, str]:
        """Return (ok, message) for health check endpoint."""


# ── Local filesystem implementation ───────────────────────────────────────


class LocalStorageClient(StorageClient):
    """Passthrough storage using the local outputs directory.

    ``upload_file`` copies the file into the outputs directory.
    ``generate_presigned_url`` returns a relative URL path (relies on
    the /outputs static mount for serving).
    """

    def __init__(self) -> None:
        from services.file_manager import OUTPUTS_DIR

        self._root: Path = OUTPUTS_DIR
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        return self._root / key

    def upload_file(self, local_path: Path, key: str) -> str:
        dest = self._resolve(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_path, dest)
        return key

    def upload_text(self, text: str, key: str) -> str:
        dest = self._resolve(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        return key

    def download_file(self, key: str, local_path: Path) -> Path:
        src = self._resolve(key)
        if not src.is_file():
            raise FileNotFoundError(f"Local object not found: {key}")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, local_path)
        return local_path

    def generate_presigned_url(self, key: str, expires_in: int = 3600, download_filename: str | None = None) -> str:
        return f"/outputs/{key}"

    def object_exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    def delete_object(self, key: str) -> None:
        p = self._resolve(key)
        if p.is_file():
            p.unlink()

    def health_check(self) -> tuple[bool, str]:
        try:
            test_key = "_health_check_test"
            self.upload_text("health check", test_key)
            self.delete_object(test_key)
            return True, f"local ({self._root})"
        except Exception as exc:
            return False, f"local storage error: {exc}"


# ── S3-compatible implementation (Cloudflare R2, AWS S3, MinIO, etc.) ─────


class S3StorageClient(StorageClient):
    """S3-compatible object storage client.

    Configured via settings:
        S3_BUCKET, S3_ENDPOINT, S3_ACCESS_KEY_ID,
        S3_SECRET_ACCESS_KEY, S3_REGION
    """

    def __init__(self) -> None:
        import boto3

        self._bucket: str = settings.s3_bucket
        if not self._bucket:
            raise ValueError("S3_BUCKET is required when storage_provider=s3")

        session_kwargs: dict = {}
        if settings.s3_access_key_id:
            session_kwargs["aws_access_key_id"] = settings.s3_access_key_id
        if settings.s3_secret_access_key:
            session_kwargs["aws_secret_access_key"] = settings.s3_secret_access_key
        if settings.s3_region:
            session_kwargs["region_name"] = settings.s3_region

        self._client = boto3.client("s3", endpoint_url=settings.s3_endpoint or None, **session_kwargs)

    def upload_file(self, local_path: Path, key: str) -> str:
        self._client.upload_file(
            str(local_path),
            self._bucket,
            key,
            ExtraArgs={"ContentType": _guess_content_type(key)},
        )
        return key

    def upload_text(self, text: str, key: str) -> str:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=text.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
        )
        return key

    def download_file(self, key: str, local_path: Path) -> Path:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(self._bucket, key, str(local_path))
        return local_path

    def generate_presigned_url(self, key: str, expires_in: int = 3600, download_filename: str | None = None) -> str:
        params: dict = {"Bucket": self._bucket, "Key": key}
        if download_filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{download_filename}"'
        return self._client.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=expires_in,
        )

    def object_exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception:
            return False

    def delete_object(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def health_check(self) -> tuple[bool, str]:
        try:
            self._client.head_bucket(Bucket=self._bucket)
            return True, f"s3://{self._bucket}"
        except Exception as exc:
            return False, f"s3 error: {exc}"


# ── Content type helpers ───────────────────────────────────────────────────

_CONTENT_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json",
    ".zip": "application/zip",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}


def _guess_content_type(key: str) -> str:
    suffix = Path(key).suffix.lower()
    return _CONTENT_TYPES.get(suffix, "application/octet-stream")


# ── Factory ────────────────────────────────────────────────────────────────

_client: Optional[StorageClient] = None


def get_storage_client() -> StorageClient:
    """Return the configured storage client (singleton within the process)."""
    global _client
    if _client is not None:
        return _client

    provider = settings.storage_provider.lower()
    if provider == "s3":
        _client = S3StorageClient()
    else:
        _client = LocalStorageClient()
    return _client
