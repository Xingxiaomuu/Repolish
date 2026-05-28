import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey
from database import Base


# ── SQLAlchemy ORM models ──────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: str = Column(String, primary_key=True, default=lambda: uuid.uuid4().hex[:12])
    name: str = Column(String, default="")
    email: str = Column(String, unique=True, nullable=False, index=True)
    password_hash: str = Column(String, default="")
    is_admin: bool = Column(Integer, default=0)  # 1 = admin (unlimited generations)
    can_generate: bool = Column(Integer, default=1)  # 0 = blocked from generating
    last_login_at: Optional[DateTime] = Column(DateTime, nullable=True)
    created_at: DateTime = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: str = Column(String, primary_key=True, default=lambda: uuid.uuid4().hex[:12])
    user_id: str = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    month: str = Column(String, nullable=False)  # "YYYY-MM"
    generation_count: int = Column(Integer, default=0)


class Job(Base):
    __tablename__ = "jobs"

    id: str = Column(String, primary_key=True, default=lambda: uuid.uuid4().hex[:12])
    status: str = Column(String, default="queued", index=True)  # queued | running | success | failed

    # User association (Phase 4F)
    user_id: Optional[str] = Column(String, ForeignKey("users.id"), nullable=True, index=True)

    # Request fields (stored so the worker can reconstruct the prompt)
    topic: str = Column(String, default="")
    content: str = Column(Text, default="")
    language: Optional[str] = Column(String, nullable=True)
    style: Optional[str] = Column(String, nullable=True)
    audience: Optional[str] = Column(String, nullable=True)
    slide_count: Optional[int] = Column(Integer, nullable=True)
    extra_requirements: Optional[str] = Column(String, nullable=True)
    search_level: Optional[str] = Column(String, default="none")

    # Derived
    content_chars: int = Column(Integer, default=0)

    # Worker / queue tracking
    worker_name: Optional[str] = Column(String, nullable=True)
    queue_position: Optional[int] = Column(Integer, nullable=True)
    retry_count: int = Column(Integer, default=0)

    # Output paths
    output_dir: Optional[str] = Column(String, nullable=True)
    index_html_path: Optional[str] = Column(String, nullable=True)
    standalone_html_path: Optional[str] = Column(String, nullable=True)
    zip_path: Optional[str] = Column(String, nullable=True)
    error_message: Optional[str] = Column(Text, nullable=True)
    logs_path: Optional[str] = Column(String, nullable=True)

    # Timestamps
    created_at: DateTime = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at: Optional[DateTime] = Column(DateTime, nullable=True)
    finished_at: Optional[DateTime] = Column(DateTime, nullable=True)

    # Token estimation (Phase 4C)
    estimated_input_tokens: Optional[int] = Column(Integer, nullable=True)
    estimated_output_tokens: Optional[int] = Column(Integer, nullable=True)
    model_name: Optional[str] = Column(String, nullable=True)
    generation_prompt_chars: Optional[int] = Column(Integer, nullable=True)
    generated_html_chars: Optional[int] = Column(Integer, nullable=True)

    # Quality check (Phase 4E)
    quality_status: Optional[str] = Column(String, nullable=True)  # "pass" | "warning" | "fail"
    quality_score: Optional[int] = Column(Integer, nullable=True)  # 0-100
    quality_warnings_count: Optional[int] = Column(Integer, nullable=True)
    quality_errors_count: Optional[int] = Column(Integer, nullable=True)

    # Download token — allows auth-free download/preview via URL param
    download_token: Optional[str] = Column(String, nullable=True, index=True)

    # Storage keys (Phase 5B) — S3 object keys under s3://bucket/jobs/{job_id}/
    index_html_key: Optional[str] = Column(String, nullable=True)
    standalone_html_key: Optional[str] = Column(String, nullable=True)
    zip_key: Optional[str] = Column(String, nullable=True)
    logs_key: Optional[str] = Column(String, nullable=True)
    quality_report_key: Optional[str] = Column(String, nullable=True)
    deck_plan_key: Optional[str] = Column(String, nullable=True)
    packed_context_key: Optional[str] = Column(String, nullable=True)
    input_cleaned_key: Optional[str] = Column(String, nullable=True)
    generation_prompt_key: Optional[str] = Column(String, nullable=True)


# ── System settings table (Phase 4C) ────────────────────────────────────

class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: str = Column(String, primary_key=True)
    value: Optional[str] = Column(String, nullable=True)


# ── Invite Code table (Phase 5D) ────────────────────────────────────────

class InviteCode(Base):
    __tablename__ = "invite_codes"

    id: str = Column(String, primary_key=True, default=lambda: uuid.uuid4().hex[:12])
    code: str = Column(String, unique=True, nullable=False, index=True)
    created_by: Optional[str] = Column(String, nullable=True)  # admin user id
    bound_user_id: Optional[str] = Column(String, ForeignKey("users.id"), nullable=True)
    monthly_limit: int = Column(Integer, default=10)  # free generations per month for this user
    is_active: bool = Column(Integer, default=1)
    created_at: DateTime = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    bound_at: Optional[DateTime] = Column(DateTime, nullable=True)
    notes: Optional[str] = Column(String, nullable=True)


# ── Pydantic API models ───────────────────────────────────────────────

class GenerateRequest(BaseModel):
    topic: Optional[str] = ""
    content: Optional[str] = ""
    language: Optional[str] = "English"
    style: Optional[str] = "Professional, bright, clean, research-oriented"
    slide_count: Optional[int] = Field(default=12, ge=1, le=80)
    audience: Optional[str] = ""
    extra_requirements: Optional[str] = ""
    search_level: Optional[str] = "none"  # "none" | "light" | "deep"


class JobResponse(BaseModel):
    job_id: str
    status: str
    topic: Optional[str] = None
    language: Optional[str] = None
    style: Optional[str] = None
    slide_count: Optional[int] = None
    content_chars: Optional[int] = None
    error_message: Optional[str] = None
    # Output URLs (only present when status == "success")
    preview_url: Optional[str] = None
    preview_standalone_url: Optional[str] = None
    download_html_url: Optional[str] = None
    download_standalone_url: Optional[str] = None
    download_zip_url: Optional[str] = None
    logs_url: Optional[str] = None
    # Worker / queue info
    worker_name: Optional[str] = None
    queue_position: Optional[int] = None
    # Timestamps
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    # Quality check (Phase 4E)
    quality_status: Optional[str] = None  # "pass" | "warning" | "fail"
    quality_score: Optional[int] = None  # 0-100

    @classmethod
    def from_orm(cls, job: Job, base_url: str = "") -> "JobResponse":
        data = {
            "job_id": job.id,
            "status": job.status,
            "topic": job.topic,
            "language": job.language,
            "style": job.style,
            "slide_count": job.slide_count,
            "content_chars": job.content_chars,
            "error_message": job.error_message,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            "worker_name": job.worker_name,
            "queue_position": job.queue_position,
            "quality_status": job.quality_status,
            "quality_score": job.quality_score,
        }
        dt = job.download_token or ""
        if job.status == "success":
            job_id = job.id
            sep = "?" if dt else ""
            tok = f"?token={dt}" if dt else ""
            data.update({
                "preview_url": f"{base_url}/api/preview/{job_id}{tok}",
                "preview_standalone_url": f"{base_url}/api/preview/{job_id}?type=standalone{('&token=' + dt) if dt else ''}",
                "download_html_url": f"{base_url}/api/download/{job_id}/html{tok}",
                "download_standalone_url": f"{base_url}/api/download/{job_id}/standalone{tok}",
                "download_zip_url": f"{base_url}/api/download/{job_id}/zip{tok}",
            })
        if job.logs_path:
            data["logs_url"] = f"{base_url}/outputs/{job.id}/logs.txt" if base_url else f"/outputs/{job.id}/logs.txt"
        return cls(**data)


class JobListResponse(BaseModel):
    jobs: list[JobResponse]


class CreateJobResponse(BaseModel):
    job_id: str
    status: str
    remaining_generations: int = 0


# ── Auth API models (Phase 4G) ──────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str  # min 6 chars, hashed before storage
    invite_code: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    created_at: Optional[str] = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ── My jobs / usage models (Phase 4G) ──────────────────────────────────

class MyJobItem(BaseModel):
    job_id: str
    status: str
    topic: Optional[str] = None
    created_at: Optional[str] = None
    quality_status: Optional[str] = None
    quality_score: Optional[int] = None
    preview_url: Optional[str] = None
    download_html_url: Optional[str] = None
    download_standalone_url: Optional[str] = None
    download_zip_url: Optional[str] = None


class MyUsageResponse(BaseModel):
    month: str
    used: int
    limit: int
    remaining: int
    success_jobs: int
    failed_jobs: int


# ── Admin API models (Phase 4C) ─────────────────────────────────────────

class AdminSummaryResponse(BaseModel):
    total_jobs: int
    success_jobs: int
    failed_jobs: int
    running_jobs: int
    queued_jobs: int
    total_users: int
    total_content_chars: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    average_generation_seconds: float
    success_rate: float


class AdminJobItem(BaseModel):
    job_id: str
    status: str
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    topic: Optional[str] = None
    language: Optional[str] = None
    style: Optional[str] = None
    audience: Optional[str] = None
    slide_count: Optional[int] = None
    content_chars: Optional[int] = None
    estimated_input_tokens: Optional[int] = None
    estimated_output_tokens: Optional[int] = None
    quality_status: Optional[str] = None
    quality_score: Optional[int] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error_message: Optional[str] = None


class AdminJobListResponse(BaseModel):
    jobs: list[AdminJobItem]
    total: int
    limit: int
    offset: int


class AdminJobDetail(BaseModel):
    job_id: str
    status: str
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    topic: Optional[str] = None
    content: Optional[str] = None
    language: Optional[str] = None
    style: Optional[str] = None
    audience: Optional[str] = None
    slide_count: Optional[int] = None
    content_chars: Optional[int] = None
    extra_requirements: Optional[str] = None
    search_level: Optional[str] = None
    worker_name: Optional[str] = None
    model_name: Optional[str] = None
    estimated_input_tokens: Optional[int] = None
    estimated_output_tokens: Optional[int] = None
    generation_prompt_chars: Optional[int] = None
    generated_html_chars: Optional[int] = None
    error_message: Optional[str] = None
    output_dir: Optional[str] = None
    prompt_path: Optional[str] = None
    logs_path: Optional[str] = None
    index_html_path: Optional[str] = None
    standalone_html_path: Optional[str] = None
    zip_path: Optional[str] = None
    quality_report: Optional[dict] = None
    quality_status: Optional[str] = None
    quality_score: Optional[int] = None
    quality_warnings_count: Optional[int] = None
    quality_errors_count: Optional[int] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    queue_seconds: Optional[float] = None
    generation_seconds: Optional[float] = None
    # Output URLs
    preview_url: Optional[str] = None
    preview_standalone_url: Optional[str] = None
    download_html_url: Optional[str] = None
    download_standalone_url: Optional[str] = None
    download_zip_url: Optional[str] = None
    logs_url: Optional[str] = None
    # Storage keys (Phase 5B)
    index_html_key: Optional[str] = None
    standalone_html_key: Optional[str] = None
    zip_key: Optional[str] = None
    logs_key: Optional[str] = None
    quality_report_key: Optional[str] = None
    deck_plan_key: Optional[str] = None
    packed_context_key: Optional[str] = None
    input_cleaned_key: Optional[str] = None
    generation_prompt_key: Optional[str] = None


class SettingUpdate(BaseModel):
    key: str
    value: str


class SettingItem(BaseModel):
    key: str
    value: Optional[str] = None


# ── Admin user / usage models (Phase 4F) ───────────────────────────────

class AdminUserItem(BaseModel):
    user_id: str
    name: str
    email: str
    is_admin: bool = False
    can_generate: bool = True
    created_at: Optional[str] = None
    total_jobs: int = 0
    success_jobs: int = 0
    failed_jobs: int = 0
    this_month_count: int = 0
    monthly_limit: int = 0


class AdminUserListResponse(BaseModel):
    users: list[AdminUserItem]
    total: int


class UpdateUserRequest(BaseModel):
    is_admin: Optional[bool] = None
    can_generate: Optional[bool] = None


class AdminStatsResponse(BaseModel):
    last_7_days_jobs: int = 0
    last_7_days_tokens: int = 0
    total_users: int = 0
    total_usage_this_month: int = 0
    free_limit: int = 0


# ── Invite code admin models (Phase 5D) ──────────────────────────────────

class CreateInviteCodeRequest(BaseModel):
    code: str
    monthly_limit: int = Field(default=10, ge=1, le=999)
    notes: Optional[str] = None


class InviteCodeItem(BaseModel):
    id: str
    code: str
    created_by: Optional[str] = None
    bound_user_id: Optional[str] = None
    bound_user_name: Optional[str] = None
    bound_user_email: Optional[str] = None
    monthly_limit: int = 10
    is_active: bool = True
    created_at: Optional[str] = None
    bound_at: Optional[str] = None
    notes: Optional[str] = None


class InviteCodeListResponse(BaseModel):
    invite_codes: list[InviteCodeItem]
    total: int
