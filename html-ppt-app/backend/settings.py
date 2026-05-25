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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
