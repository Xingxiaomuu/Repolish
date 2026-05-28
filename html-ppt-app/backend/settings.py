import os
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = f"sqlite:///{Path(__file__).resolve().parent / 'app.db'}"

    # Redis / RQ
    redis_url: str = "redis://localhost:6379"

    # Claude Code
    claude_code_command: str = "claude"
    claude_timeout: int = 1800

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Admin
    admin_password: str = ""  # Empty = no password required

    # Rate limiting (Phase 4F)
    free_generations_per_month: int = 3

    # Phase 5D: Invite code
    invite_code_required: bool = False
    test_invite_code: str = ""  # universal invite code (empty = disabled)

    # Phase 5D: Input size limits
    max_report_chars: int = 80000
    max_topic_chars: int = 200
    max_extra_requirements_chars: int = 2000

    # Phase 5D: Rate limiting (Redis)
    rate_limit_register_per_hour: int = 10
    rate_limit_login_per_10min: int = 20
    rate_limit_create_job_per_hour: int = 5

    # Worker (Phase 4B)
    worker_count: int = 2

    # Auth (Phase 4G)
    jwt_secret: str = "change-me"
    jwt_expire_days: int = 7

    # Deployment (Phase 5A)
    output_dir: str = ""  # Override output root; empty = use default (backend/outputs/)
    cors_origins: str = "*"  # comma-separated allowed origins
    public_backend_url: str = ""  # e.g. https://api.example.com
    frontend_url: str = ""  # e.g. https://example.com

    # Storage (Phase 5B) — "local" or "s3"
    storage_provider: str = "local"  # "local" = filesystem, "s3" = S3-compatible (R2)
    s3_bucket: str = ""
    s3_endpoint: str = ""  # e.g. https://<account>.r2.cloudflarestorage.com
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_region: str = "auto"  # "auto" for Cloudflare R2
    s3_public_base_url: str = ""  # e.g. https://pub-<hash>.r2.dev (fallback)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
