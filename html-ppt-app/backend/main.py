import json
import re
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from pathlib import Path

import redis
from fastapi import FastAPI, HTTPException, Depends, Query, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse

from rq import Queue, Worker
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from jose import JWTError, jwt
import bcrypt

from database import init_db, get_db
from models import (
    GenerateRequest, JobResponse, JobListResponse, CreateJobResponse, Job,
    User, UsageRecord, SystemSetting, InviteCode, Feedback,
    RegisterRequest, LoginRequest, LoginResponse, UserResponse,
    MyJobItem, MyUsageResponse,
    AdminSummaryResponse, AdminJobItem, AdminJobListResponse, AdminJobDetail,
    AdminUserItem, AdminUserListResponse, AdminStatsResponse,
    SettingUpdate, SettingItem, UpdateUserRequest,
    CreateInviteCodeRequest, InviteCodeItem, InviteCodeListResponse,
    FeedbackRequest, FeedbackResponse,
)
from services import file_manager
from services.admin_auth import verify_admin_password
from services.path_contract import (
    get_storage_key, artifact_filename, filename_to_artifact_type,
    ArtifactType, ALL_ARTIFACT_TYPES,
)
from settings import settings

BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def _sanitize_filename(name: str, max_len: int = 60) -> str:
    """Sanitize a string for use as a download filename."""
    import unicodedata
    # Keep only alphanumeric, Chinese chars, spaces, and basic punctuation
    cleaned = "".join(c for c in name if c.isalnum() or c.isspace() or c in "_-+()（）")
    # Normalize unicode
    cleaned = unicodedata.normalize("NFKC", cleaned)
    # Collapse whitespace
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rsplit(" ", 1)[0]
    return cleaned.strip() or "report"


def _job_download_name(job: Job, suffix: str = ".html") -> str:
    """Generate a download filename from job topic."""
    topic = (job.topic or "").strip()
    if topic:
        return _sanitize_filename(topic) + suffix
    return f"report-{job.id[:8]}{suffix}"


def _can_access_job(current_user: User, job: Job) -> bool:
    """User can access a job if they own it or are admin."""
    return bool(current_user.is_admin) or job.user_id == current_user.id

def _lookup_job(job_id: str, db: Session) -> Job:
    """Look up a successful job or raise 404."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job or job.status != "success":
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ── Rate limiting (Phase 5D) ──────────────────────────────────────────

def _check_rate_limit(key: str, max_requests: int, window_seconds: int) -> bool:
    """Redis-based sliding window rate limit. Returns True if under limit."""
    try:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        window_start = now_ms - (window_seconds * 1000)
        pipe = redis_conn.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zcard(key)
        _, count = pipe.execute()
        if count < max_requests:
            redis_conn.zadd(key, {str(now_ms): now_ms})
            redis_conn.expire(key, window_seconds + 10)
            return True
        return False
    except Exception:
        return True  # fail open if Redis is down


def _get_client_ip(request: Request) -> str:
    """Best-effort client IP from X-Forwarded-For or direct connection."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def _extract_token(
    authorization: str | None = Header(None, include_in_schema=False),
    access_token: str | None = Query(None, alias="access_token", include_in_schema=False),
) -> str | None:
    """Extract JWT from Authorization: Bearer <token> or ?access_token=<token>."""
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return access_token


def _get_optional_user(
    token: str | None = Depends(_extract_token),
    db: Session = Depends(get_db),
) -> User | None:
    """Like get_current_user but returns None instead of raising 401."""
    if token is None:
        return None
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            return None
    except JWTError:
        return None
    return db.query(User).filter(User.id == user_id).first()

def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def _verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    file_manager.ensure_outputs_dir()
    yield


app = FastAPI(title="HTML PPT Generator", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Redis / RQ connection
redis_conn = redis.from_url(settings.redis_url)
generation_queue = Queue("generation", connection=redis_conn)


@app.get("/")
def root():
    return {"status": "ok", "app": "Slidehttp HTML PPT Generator"}


@app.get("/api/health")
def health_check(db: Session = Depends(get_db)):
    """Phase 5A — comprehensive health check for Railway deployment."""
    import shutil
    import os

    checks: dict[str, bool | str] = {}

    # 1. API
    checks["api"] = "ok"

    # 2. Database
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # 3. Redis
    try:
        if redis_conn.ping():
            checks["redis"] = "connected"
        else:
            checks["redis"] = "no response"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    # 4. Output directory / Storage
    if settings.storage_provider == "s3":
        from services.storage import get_storage_client
        try:
            storage_ok, storage_msg = get_storage_client().health_check()
            checks["storage"] = storage_msg
        except Exception as e:
            checks["storage"] = f"error: {e}"
    else:
        from services import file_manager
        output_dir = file_manager.OUTPUTS_DIR
        try:
            file_manager.ensure_outputs_dir()
            test_file = output_dir / ".health_check"
            test_file.write_text("ok")
            test_file.unlink()
            checks["output_dir"] = f"writable ({output_dir})"
        except Exception as e:
            checks["output_dir"] = f"error: {e}"

    # 5. Claude Code CLI
    claude_cmd = settings.claude_code_command
    claude_path = shutil.which(claude_cmd)
    if claude_path:
        checks["claude_command"] = f"found ({claude_path})"
    else:
        # Also check for just "claude" if the configured command is something else
        alt = shutil.which("claude")
        if alt:
            checks["claude_command"] = f"found as 'claude' ({alt})"
        else:
            checks["claude_command"] = "NOT FOUND — Claude Code CLI not installed"

    # 6. html-ppt skill
    skill_path = BASE_DIR.parent.parent / ".agents" / "skills" / "html-ppt" / "SKILL.md"
    if skill_path.is_file():
        checks["html_ppt_skill"] = f"exists ({skill_path})"
    else:
        # Check relative to cwd
        cwd_skill = Path.cwd() / ".agents" / "skills" / "html-ppt" / "SKILL.md"
        if cwd_skill.is_file():
            checks["html_ppt_skill"] = f"exists ({cwd_skill})"
        else:
            checks["html_ppt_skill"] = "NOT FOUND"

    # 7. Environment info
    checks["python_version"] = os.sys.version.split()[0]
    checks["worker_count"] = str(settings.worker_count if hasattr(settings, 'worker_count') else 2)

    all_ok = all(
        isinstance(v, str) and ("error" not in v.lower() and "not found" not in v.lower())
        for v in checks.values()
        if v != "ok"  # skip the plain "ok" string
    )

    return {
        "status": "pass" if all_ok else "degraded",
        "checks": checks,
    }


# ── Auth helpers (Phase 4G) ────────────────────────────────────────────

def _create_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_expire_days)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def get_current_user(
    token: str | None = Depends(_extract_token),
    db: Session = Depends(get_db),
) -> User:
    if token is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


# ── Auth endpoints (Phase 4G) ──────────────────────────────────────────

@app.post("/api/auth/register")
def auth_register(req: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    name = req.name.strip()

    if not email or not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="A valid email address is required.")
    if not name:
        raise HTTPException(status_code=400, detail="Please provide your name.")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")

    # Phase 5D: Rate limiting (per IP, hourly)
    ip = _get_client_ip(request)
    rl_key = f"ratelimit:register:{ip}"
    if not _check_rate_limit(rl_key, settings.rate_limit_register_per_hour, 3600):
        raise HTTPException(status_code=429, detail="Too many registration attempts. Please try again later.")

    # Phase 5D: Invite code validation
    code = ""
    invite = None
    if settings.invite_code_required:
        code = (req.invite_code or "").strip()
        if not code:
            raise HTTPException(status_code=400, detail="An invite code is required to register.")

        # Check universal test invite code first
        if settings.test_invite_code and code == settings.test_invite_code:
            pass  # universal code accepted
        else:
            invite = db.query(InviteCode).filter(
                InviteCode.code == code,
                InviteCode.is_active == 1,
            ).first()
            if not invite:
                raise HTTPException(status_code=400, detail="Invalid or expired invite code.")
            if invite.bound_user_id:
                raise HTTPException(status_code=400, detail="This invite code has already been used.")

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        # Phase 4F legacy user without password → allow completing registration
        if not existing.password_hash:
            existing.name = name
            existing.password_hash = _hash_password(req.password)
            db.commit()
            return {"message": "Registration complete. Please login with your new password."}
        raise HTTPException(status_code=400, detail="Email already registered.")

    user = User(
        name=name,
        email=email,
        password_hash=_hash_password(req.password),
        created_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.flush()  # get user.id

    # Phase 5D: Bind invite code to this user
    if settings.invite_code_required and code and code != settings.test_invite_code:
        invite.bound_user_id = user.id
        invite.bound_at = datetime.now(timezone.utc)

    db.commit()

    return {"message": "Registration successful. Please login."}


@app.post("/api/auth/login", response_model=LoginResponse)
def auth_login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required.")

    # Phase 5D: Rate limiting (per IP, per 10 min window)
    ip = _get_client_ip(request)
    rl_key = f"ratelimit:login:{ip}"
    if not _check_rate_limit(rl_key, settings.rate_limit_login_per_10min, 600):
        raise HTTPException(status_code=429, detail="Too many login attempts. Please try again later.")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if not user.password_hash:
        raise HTTPException(
            status_code=400,
            detail="This account was created before password support. Please register again with the same email to set a password.",
        )

    if not _verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    token = _create_token(user.id)
    return LoginResponse(
        access_token=token,
        user=UserResponse(
            id=user.id,
            name=user.name,
            email=user.email,
            created_at=user.created_at.isoformat() if user.created_at else None,
        ),
    )


@app.get("/api/auth/me", response_model=UserResponse)
def auth_me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=current_user.id,
        name=current_user.name,
        email=current_user.email,
        created_at=current_user.created_at.isoformat() if current_user.created_at else None,
    )


@app.post("/api/auth/logout")
def auth_logout():
    return {"message": "Logged out (client should discard token)"}


# ── Job endpoints ─────────────────────────────────────────────────────

@app.post("/api/jobs", response_model=CreateJobResponse)
def create_job(
    req: GenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not req.topic.strip() and not req.content.strip():
        raise HTTPException(status_code=400, detail="Please provide at least a topic or some content.")

    # Phase 5D: Input size limits
    topic_len = len(req.topic or "")
    content_len = len(req.content or "")
    extra_len = len(req.extra_requirements or "")

    if topic_len > settings.max_topic_chars:
        raise HTTPException(
            status_code=400,
            detail=f"Topic is too long ({topic_len} chars). Maximum is {settings.max_topic_chars} characters.",
        )
    if content_len > settings.max_report_chars:
        raise HTTPException(
            status_code=400,
            detail=f"Report content is too long ({content_len} chars). Maximum is {settings.max_report_chars} characters.",
        )
    if extra_len > settings.max_extra_requirements_chars:
        raise HTTPException(
            status_code=400,
            detail=f"Extra requirements are too long ({extra_len} chars). Maximum is {settings.max_extra_requirements_chars} characters.",
        )

    # Phase 5D: Rate limiting (per user, hourly) — skipped for admins
    is_admin = bool(current_user.is_admin)
    if not is_admin:
        rl_key = f"ratelimit:create_job:{current_user.id}"
        if not _check_rate_limit(rl_key, settings.rate_limit_create_job_per_hour, 3600):
            raise HTTPException(
                status_code=429,
                detail=f"You've reached the rate limit ({settings.rate_limit_create_job_per_hour} jobs per hour). Please wait before creating another job.",
            )

    # ── Permission check ───────────────────────────────────────────────
    if not current_user.can_generate:
        raise HTTPException(
            status_code=403,
            detail="Your account has been restricted from generating. Please contact the admin.",
        )

    # ── Monthly generation limit (Phase 4F + Phase 5D invite code limit) ──
    now = datetime.now(timezone.utc)
    month_key = now.strftime("%Y-%m")

    # Phase 5D: Check invite code binding for custom monthly limit
    if not is_admin:
        invite = db.query(InviteCode).filter(InviteCode.bound_user_id == current_user.id).first()
        limit = invite.monthly_limit if invite else settings.free_generations_per_month
    else:
        limit = 999999
        invite = None

    if not is_admin:
        usage = db.query(UsageRecord).filter(
            UsageRecord.user_id == current_user.id,
            UsageRecord.month == month_key,
        ).first()

        current_count = usage.generation_count if usage else 0
        if current_count >= limit:
            raise HTTPException(
                status_code=429,
                detail=f"Monthly free generation limit reached ({limit}/{limit}). "
                       f"Please try again next month or contact the admin.",
            )
    else:
        usage = None
        current_count = 0

    # ── Increment usage (track admin usage too, just don't block) ──────
    if not is_admin:
        if usage:
            usage.generation_count = current_count + 1
        else:
            usage = UsageRecord(user_id=current_user.id, month=month_key, generation_count=1)
            db.add(usage)
        db.commit()

    # ── Create job ────────────────────────────────────────────────────
    import secrets
    job_id = file_manager.generate_job_id()
    download_token = secrets.token_urlsafe(16)
    job = Job(
        id=job_id,
        user_id=current_user.id,
        status="queued",
        topic=req.topic or "",
        content=req.content or "",
        language=req.language,
        style=req.style,
        audience=req.audience,
        slide_count=req.slide_count,
        extra_requirements=req.extra_requirements,
        search_level=req.search_level,
        content_chars=len(req.content or ""),
        download_token=download_token,
    )
    db.add(job)
    db.commit()

    # Enqueue the generation task
    from tasks.generate_deck import generate_deck
    try:
        generation_queue.enqueue(generate_deck, job_id, job_timeout=settings.claude_timeout)
        job.queue_position = _compute_queue_position(job_id)
        db.commit()
    except Exception as enq_err:
        job.status = "failed"
        job.error_message = f"Failed to enqueue job (is Redis running?): {enq_err}"
        db.commit()
        raise HTTPException(
            status_code=503,
            detail=f"Failed to enqueue job. Is Redis running? {enq_err}",
        )

    remaining = max(0, limit - current_count - 1)
    return CreateJobResponse(
        job_id=job_id,
        status="queued",
        remaining_generations=remaining,
    )


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    resp = JobResponse.from_orm(job, settings.public_backend_url)
    # Compute live queue position for queued jobs
    if job.status == "queued":
        resp.queue_position = _compute_queue_position(job_id)
    return resp


@app.get("/api/jobs", response_model=JobListResponse)
def list_jobs(limit: int = 50, db: Session = Depends(get_db)):
    jobs = db.query(Job).order_by(Job.created_at.desc()).limit(limit).all()
    return JobListResponse(jobs=[JobResponse.from_orm(j, settings.public_backend_url) for j in jobs])


# ── My Jobs / My Usage (Phase 4G) ──────────────────────────────────────

@app.get("/api/my/jobs")
def my_jobs(
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    jobs = (
        db.query(Job)
        .filter(Job.user_id == current_user.id)
        .order_by(Job.created_at.desc())
        .limit(limit)
        .all()
    )
    items = []
    for j in jobs:
        item = {
            "job_id": j.id,
            "status": j.status,
            "topic": j.topic,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "quality_status": j.quality_status,
            "quality_score": j.quality_score,
        }
        if j.status == "success":
            tok = f"?token={j.download_token}" if j.download_token else ""
            item.update({
                "preview_url": f"{settings.public_backend_url}/api/preview/{j.id}{tok}",
                "download_html_url": f"{settings.public_backend_url}/api/download/{j.id}/html{tok}",
                "download_standalone_url": f"{settings.public_backend_url}/api/download/{j.id}/standalone{tok}",
                "download_zip_url": f"{settings.public_backend_url}/api/download/{j.id}/zip{tok}",
            })
        items.append(MyJobItem(**item))
    return {"jobs": items}


@app.get("/api/my/usage", response_model=MyUsageResponse)
def my_usage(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    month_key = now.strftime("%Y-%m")

    # Phase 5D: Check invite code for custom monthly limit
    invite = db.query(InviteCode).filter(InviteCode.bound_user_id == current_user.id).first()
    limit = invite.monthly_limit if invite else settings.free_generations_per_month

    usage = db.query(UsageRecord).filter(
        UsageRecord.user_id == current_user.id,
        UsageRecord.month == month_key,
    ).first()
    used = usage.generation_count if usage else 0

    success = db.query(func.count(Job.id)).filter(
        Job.user_id == current_user.id, Job.status == "success"
    ).scalar() or 0
    failed = db.query(func.count(Job.id)).filter(
        Job.user_id == current_user.id, Job.status == "failed"
    ).scalar() or 0

    return MyUsageResponse(
        month=month_key,
        used=used,
        limit=limit,
        remaining=max(0, limit - used),
        success_jobs=success,
        failed_jobs=failed,
    )


# ── Admin endpoints (Phase 4C) ──────────────────────────────────────────

_ADMIN_AUTH = Depends(verify_admin_password)


@app.get("/api/admin/summary", response_model=AdminSummaryResponse)
def admin_summary(db: Session = Depends(get_db), _=Depends(verify_admin_password)):
    """Aggregate statistics across all jobs."""
    total = db.query(func.count(Job.id)).scalar() or 0
    success = db.query(func.count(Job.id)).filter(Job.status == "success").scalar() or 0
    failed = db.query(func.count(Job.id)).filter(Job.status == "failed").scalar() or 0
    running = db.query(func.count(Job.id)).filter(Job.status == "running").scalar() or 0
    queued = db.query(func.count(Job.id)).filter(Job.status == "queued").scalar() or 0
    total_chars = db.query(func.sum(Job.content_chars)).scalar() or 0
    total_in = db.query(func.sum(Job.estimated_input_tokens)).scalar() or 0
    total_out = db.query(func.sum(Job.estimated_output_tokens)).scalar() or 0
    total_users = db.query(func.count(User.id)).scalar() or 0

    avg_sec = 0.0
    timed_jobs = db.query(Job).filter(
        Job.status.in_(["success", "failed"]),
        Job.started_at.isnot(None),
        Job.finished_at.isnot(None),
    ).all()
    if timed_jobs:
        diffs = [(j.finished_at - j.started_at).total_seconds() for j in timed_jobs]
        avg_sec = sum(diffs) / len(diffs)

    success_rate = round(success / total, 4) if total > 0 else 0.0

    # Phase 5H: Path check stats
    path_check_failed = db.query(func.count(Job.id)).filter(
        Job.path_check_status == "fail"
    ).scalar() or 0
    missing_storage = db.query(func.count(Job.id)).filter(
        Job.status == "success",
        Job.index_html_key.is_(None),
        Job.index_html_path.is_(None),
    ).scalar() or 0

    # Phase 5E: Feedback stats
    fb_total = db.query(func.count(Feedback.id)).scalar() or 0
    avg_rating = 0.0
    avg_accuracy = 0.0
    avg_visual = 0.0
    avg_useful = 0.0
    wua_rate = 0.0
    low_rating = 0
    if fb_total > 0:
        avg_rating = round((db.query(func.avg(Feedback.rating)).scalar() or 0.0), 1)
        avg_accuracy = round((db.query(func.avg(Feedback.content_accuracy)).scalar() or 0.0), 1)
        avg_visual = round((db.query(func.avg(Feedback.visual_quality)).scalar() or 0.0), 1)
        avg_useful = round((db.query(func.avg(Feedback.usefulness)).scalar() or 0.0), 1)
        would_again = db.query(func.count(Feedback.id)).filter(Feedback.would_use_again == 1).scalar() or 0
        wua_rate = round(would_again / fb_total, 2) if fb_total > 0 else 0.0
        low_rating = db.query(func.count(Feedback.id)).filter(Feedback.rating <= 2).scalar() or 0

    return {
        "total_jobs": total,
        "success_jobs": success,
        "failed_jobs": failed,
        "running_jobs": running,
        "queued_jobs": queued,
        "total_users": total_users,
        "total_content_chars": total_chars or 0,
        "estimated_input_tokens": total_in or 0,
        "estimated_output_tokens": total_out or 0,
        "average_generation_seconds": round(avg_sec, 1),
        "success_rate": success_rate,
        "path_check_failed_jobs": path_check_failed,
        "missing_storage_object_jobs": missing_storage,
        "average_rating": avg_rating,
        "average_content_accuracy": avg_accuracy,
        "average_visual_quality": avg_visual,
        "average_usefulness": avg_useful,
        "would_use_again_rate": wua_rate,
        "feedback_count": fb_total,
        "low_rating_jobs": low_rating,
    }


@app.get("/api/admin/jobs", response_model=AdminJobListResponse)
def admin_jobs(
    status: str = Query(None, description="Filter: queued|running|success|failed"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _=Depends(verify_admin_password),
):
    """Paginated job list with optional status filter."""
    q = db.query(Job, User).outerjoin(User, Job.user_id == User.id)
    if status:
        q = q.filter(Job.status == status)
    total = q.count()
    rows = q.order_by(Job.created_at.desc()).offset(offset).limit(limit).all()

    items = []
    for j, u in rows:
        items.append(AdminJobItem(
            job_id=j.id,
            status=j.status,
            user_name=u.name if u else None,
            user_email=u.email if u else None,
            topic=j.topic,
            language=j.language,
            style=j.style,
            audience=j.audience,
            slide_count=j.slide_count,
            content_chars=j.content_chars,
            estimated_input_tokens=j.estimated_input_tokens,
            estimated_output_tokens=j.estimated_output_tokens,
            quality_status=j.quality_status,
            quality_score=j.quality_score,
            created_at=j.created_at.isoformat() if j.created_at else None,
            started_at=j.started_at.isoformat() if j.started_at else None,
            finished_at=j.finished_at.isoformat() if j.finished_at else None,
            error_message=j.error_message,
        ))

    return AdminJobListResponse(jobs=items, total=total, limit=limit, offset=offset)


@app.get("/api/admin/jobs/{job_id}", response_model=AdminJobDetail)
def admin_job_detail(job_id: str, db: Session = Depends(get_db), _=Depends(verify_admin_password)):
    """Full job detail including timing, paths, and quality report."""
    j = db.query(Job).filter(Job.id == job_id).first()
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")

    prompt_path = None
    if j.output_dir:
        gen_prompt = Path(j.output_dir) / "generation_prompt.txt"
        simple_prompt = Path(j.output_dir) / "prompt.txt"
        if gen_prompt.is_file():
            prompt_path = str(gen_prompt)
        elif simple_prompt.is_file():
            prompt_path = str(simple_prompt)

    quality_report = None
    if j.output_dir:
        qr_path = Path(j.output_dir) / "quality_report.json"
        if qr_path.is_file():
            try:
                quality_report = json.loads(qr_path.read_text(encoding="utf-8"))
            except Exception:
                pass

    queue_seconds = None
    generation_seconds = None
    if j.created_at and j.started_at:
        queue_seconds = round((j.started_at - j.created_at).total_seconds(), 1)
    if j.started_at and j.finished_at:
        generation_seconds = round((j.finished_at - j.started_at).total_seconds(), 1)

    # Lookup user
    user_name = None
    user_email = None
    if j.user_id:
        u = db.query(User).filter(User.id == j.user_id).first()
        if u:
            user_name = u.name
            user_email = u.email

    detail = {
        "job_id": j.id,
        "status": j.status,
        "user_name": user_name,
        "user_email": user_email,
        "topic": j.topic,
        "content": j.content[:5000] if j.content else None,
        "language": j.language,
        "style": j.style,
        "audience": j.audience,
        "slide_count": j.slide_count,
        "content_chars": j.content_chars,
        "extra_requirements": j.extra_requirements,
        "search_level": j.search_level,
        "worker_name": j.worker_name,
        "model_name": j.model_name,
        "estimated_input_tokens": j.estimated_input_tokens,
        "estimated_output_tokens": j.estimated_output_tokens,
        "generation_prompt_chars": j.generation_prompt_chars,
        "generated_html_chars": j.generated_html_chars,
        "error_message": j.error_message,
        "output_dir": j.output_dir,
        "prompt_path": prompt_path,
        "logs_path": j.logs_path,
        "index_html_path": j.index_html_path,
        "standalone_html_path": j.standalone_html_path,
        "zip_path": j.zip_path,
        "quality_report": quality_report,
        "quality_status": j.quality_status,
        "quality_score": j.quality_score,
        "quality_warnings_count": j.quality_warnings_count,
        "quality_errors_count": j.quality_errors_count,
        "created_at": j.created_at.isoformat() if j.created_at else None,
        "started_at": j.started_at.isoformat() if j.started_at else None,
        "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        "queue_seconds": queue_seconds,
        "generation_seconds": generation_seconds,
    }

    if j.status == "success":
        tok = f"?token={j.download_token}" if j.download_token else ""
        tok_amp = f"&token={j.download_token}" if j.download_token else ""
        detail.update({
            "preview_url": f"{settings.public_backend_url}/api/preview/{j.id}{tok}",
            "preview_standalone_url": f"{settings.public_backend_url}/api/preview/{j.id}?type=standalone{tok_amp}",
            "download_html_url": f"{settings.public_backend_url}/api/download/{j.id}/html{tok}",
            "download_standalone_url": f"{settings.public_backend_url}/api/download/{j.id}/standalone{tok}",
            "download_zip_url": f"{settings.public_backend_url}/api/download/{j.id}/zip{tok}",
        })
    if j.logs_path or j.logs_key:
        detail["logs_url"] = f"{settings.public_backend_url}/api/admin/jobs/{j.id}/logs"

    # Storage keys (Phase 5B)
    detail.update({
        "index_html_key": j.index_html_key,
        "standalone_html_key": j.standalone_html_key,
        "zip_key": j.zip_key,
        "logs_key": j.logs_key,
        "quality_report_key": j.quality_report_key,
        "deck_plan_key": j.deck_plan_key,
        "packed_context_key": j.packed_context_key,
        "input_cleaned_key": j.input_cleaned_key,
        "generation_prompt_key": j.generation_prompt_key,
    })

    # Path check (Phase 5H)
    detail.update({
        "path_check_status": j.path_check_status,
        "path_check_errors_count": j.path_check_errors_count or 0,
        "path_check_warnings_count": j.path_check_warnings_count or 0,
        "path_check_key": j.path_check_key,
    })

    # Feedback (Phase 5E)
    fb = db.query(Feedback).filter(Feedback.job_id == j.id).first()
    if fb:
        detail["feedback"] = {
            "id": fb.id,
            "rating": fb.rating,
            "content_accuracy": fb.content_accuracy,
            "visual_quality": fb.visual_quality,
            "usefulness": fb.usefulness,
            "would_use_again": bool(fb.would_use_again),
            "most_needed_feature": fb.most_needed_feature,
            "comment": fb.comment,
            "created_at": fb.created_at.isoformat() if fb.created_at else None,
        }

    return detail


@app.get("/api/admin/queue")
def admin_queue(db: Session = Depends(get_db), _=Depends(verify_admin_password)):
    """Queue status for admin monitoring."""
    queued = db.query(func.count(Job.id)).filter(Job.status == "queued").scalar() or 0
    started = db.query(func.count(Job.id)).filter(Job.status == "running").scalar() or 0
    finished = db.query(func.count(Job.id)).filter(Job.status == "success").scalar() or 0
    failed = db.query(func.count(Job.id)).filter(Job.status == "failed").scalar() or 0

    redis_ok = False
    worker_count = 0
    worker_names: list[str] = []
    queue_len = 0
    try:
        redis_ok = redis_conn.ping()
        workers = Worker.all(connection=redis_conn)
        worker_count = len(workers)
        worker_names = [w.name for w in workers]
        queue_len = len(generation_queue)
    except Exception:
        pass

    return {
        "queued_jobs": queued,
        "started_jobs": started,
        "finished_jobs": finished,
        "failed_jobs": failed,
        "worker_count_detected": worker_count,
        "worker_names": worker_names,
        "redis_connected": redis_ok,
        "rq_queue_length": queue_len,
    }


@app.get("/api/admin/settings")
def admin_get_settings(db: Session = Depends(get_db), _=Depends(verify_admin_password)):
    """Get all system settings."""
    rows = db.query(SystemSetting).all()
    return [SettingItem(key=r.key, value=r.value) for r in rows]


@app.post("/api/admin/settings")
def admin_set_settings(
    body: SettingUpdate,
    db: Session = Depends(get_db),
    _=Depends(verify_admin_password),
):
    """Set a system setting (upsert)."""
    row = db.query(SystemSetting).filter(SystemSetting.key == body.key).first()
    if row:
        row.value = body.value
    else:
        row = SystemSetting(key=body.key, value=body.value)
        db.add(row)
    db.commit()
    return {"key": body.key, "value": body.value}


# ── Admin user / usage endpoints (Phase 4F) ───────────────────────────

@app.get("/api/admin/users", response_model=AdminUserListResponse)
def admin_users(db: Session = Depends(get_db), _=Depends(verify_admin_password)):
    """List all users with usage stats."""
    now = datetime.now(timezone.utc)
    month_key = now.strftime("%Y-%m")
    default_limit = settings.free_generations_per_month

    users = db.query(User).order_by(User.created_at.desc()).all()
    items = []
    for u in users:
        total_jobs = db.query(func.count(Job.id)).filter(Job.user_id == u.id).scalar() or 0
        success_jobs = db.query(func.count(Job.id)).filter(
            Job.user_id == u.id, Job.status == "success").scalar() or 0
        failed_jobs = db.query(func.count(Job.id)).filter(
            Job.user_id == u.id, Job.status == "failed").scalar() or 0
        usage = db.query(UsageRecord).filter(
            UsageRecord.user_id == u.id, UsageRecord.month == month_key).first()
        this_month = usage.generation_count if usage else 0

        # Phase 5D: Each user may have a different limit via invite code
        ic = db.query(InviteCode).filter(InviteCode.bound_user_id == u.id).first()
        user_limit = ic.monthly_limit if ic else default_limit

        items.append(AdminUserItem(
            user_id=u.id,
            name=u.name,
            email=u.email,
            is_admin=bool(u.is_admin),
            can_generate=bool(u.can_generate),
            created_at=u.created_at.isoformat() if u.created_at else None,
            total_jobs=total_jobs,
            success_jobs=success_jobs,
            failed_jobs=failed_jobs,
            this_month_count=this_month,
            monthly_limit=user_limit,
        ))
    return AdminUserListResponse(users=items, total=len(items))


@app.put("/api/admin/users/{user_id}")
def admin_update_user(
    user_id: str,
    req: UpdateUserRequest,
    db: Session = Depends(get_db),
    _=Depends(verify_admin_password),
):
    """Update user admin status and generation permission."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if req.is_admin is not None:
        user.is_admin = 1 if req.is_admin else 0
    if req.can_generate is not None:
        user.can_generate = 1 if req.can_generate else 0

    db.commit()
    return {
        "user_id": user_id,
        "is_admin": bool(user.is_admin),
        "can_generate": bool(user.can_generate),
    }


@app.get("/api/admin/stats", response_model=AdminStatsResponse)
def admin_stats(db: Session = Depends(get_db), _=Depends(verify_admin_password)):
    """Quick stats: last 7 days jobs, tokens, users, usage."""
    now = datetime.now(timezone.utc)
    month_key = now.strftime("%Y-%m")
    limit = settings.free_generations_per_month

    # Last 7 days
    from datetime import timedelta
    seven_days_ago = now - timedelta(days=7)
    last_7_jobs = db.query(func.count(Job.id)).filter(
        Job.created_at >= seven_days_ago).scalar() or 0
    last_7_tokens = (
        (db.query(func.sum(Job.estimated_input_tokens)).filter(
            Job.created_at >= seven_days_ago).scalar() or 0)
        + (db.query(func.sum(Job.estimated_output_tokens)).filter(
            Job.created_at >= seven_days_ago).scalar() or 0)
    )

    total_users = db.query(func.count(User.id)).scalar() or 0
    total_usage = db.query(func.sum(UsageRecord.generation_count)).filter(
        UsageRecord.month == month_key).scalar() or 0

    return {
        "last_7_days_jobs": last_7_jobs,
        "last_7_days_tokens": last_7_tokens,
        "total_users": total_users,
        "total_usage_this_month": total_usage,
        "free_limit": limit,
    }


# ── Admin invite code endpoints (Phase 5D) ─────────────────────────────

@app.get("/api/admin/invite-codes", response_model=InviteCodeListResponse)
def admin_list_invite_codes(db: Session = Depends(get_db), _=Depends(verify_admin_password)):
    """List all invite codes with binding status."""
    rows = db.query(InviteCode).order_by(InviteCode.created_at.desc()).all()
    items = []
    for ic in rows:
        bound_name = None
        bound_email = None
        if ic.bound_user_id:
            u = db.query(User).filter(User.id == ic.bound_user_id).first()
            if u:
                bound_name = u.name
                bound_email = u.email
        items.append(InviteCodeItem(
            id=ic.id,
            code=ic.code,
            created_by=ic.created_by,
            bound_user_id=ic.bound_user_id,
            bound_user_name=bound_name,
            bound_user_email=bound_email,
            monthly_limit=ic.monthly_limit,
            is_active=bool(ic.is_active),
            created_at=ic.created_at.isoformat() if ic.created_at else None,
            bound_at=ic.bound_at.isoformat() if ic.bound_at else None,
            notes=ic.notes,
        ))
    return InviteCodeListResponse(invite_codes=items, total=len(items))


@app.post("/api/admin/invite-codes")
def admin_create_invite_code(
    req: CreateInviteCodeRequest,
    db: Session = Depends(get_db),
    _=Depends(verify_admin_password),
):
    """Create a new invite code."""
    code = req.code.strip()
    if not code or len(code) < 4:
        raise HTTPException(status_code=400, detail="Invite code must be at least 4 characters.")
    if len(code) > 64:
        raise HTTPException(status_code=400, detail="Invite code must be at most 64 characters.")

    existing = db.query(InviteCode).filter(InviteCode.code == code).first()
    if existing:
        raise HTTPException(status_code=400, detail="This invite code already exists.")

    ic = InviteCode(
        code=code,
        monthly_limit=req.monthly_limit,
        notes=req.notes,
    )
    db.add(ic)
    db.commit()
    db.refresh(ic)

    return {
        "id": ic.id,
        "code": ic.code,
        "monthly_limit": ic.monthly_limit,
        "is_active": bool(ic.is_active),
        "notes": ic.notes,
        "created_at": ic.created_at.isoformat() if ic.created_at else None,
    }


@app.put("/api/admin/invite-codes/{invite_id}")
def admin_update_invite_code(
    invite_id: str,
    req: dict,
    db: Session = Depends(get_db),
    _=Depends(verify_admin_password),
):
    """Update an invite code (monthly_limit, is_active, notes). Cannot change code string."""
    ic = db.query(InviteCode).filter(InviteCode.id == invite_id).first()
    if not ic:
        raise HTTPException(status_code=404, detail="Invite code not found")

    if "is_active" in req:
        ic.is_active = 1 if req["is_active"] else 0
    if "monthly_limit" in req:
        limit_val = int(req["monthly_limit"])
        if limit_val < 1 or limit_val > 999:
            raise HTTPException(status_code=400, detail="Monthly limit must be between 1 and 999.")
        ic.monthly_limit = limit_val
    if "notes" in req:
        ic.notes = req["notes"]

    db.commit()
    return {"id": ic.id, "code": ic.code, "is_active": bool(ic.is_active), "monthly_limit": ic.monthly_limit, "notes": ic.notes}


@app.delete("/api/admin/invite-codes/{invite_id}")
def admin_delete_invite_code(
    invite_id: str,
    db: Session = Depends(get_db),
    _=Depends(verify_admin_password),
):
    """Delete an invite code. Cannot delete a bound code."""
    ic = db.query(InviteCode).filter(InviteCode.id == invite_id).first()
    if not ic:
        raise HTTPException(status_code=404, detail="Invite code not found")
    if ic.bound_user_id:
        raise HTTPException(status_code=400, detail="Cannot delete an invite code that is already bound to a user.")

    db.delete(ic)
    db.commit()
    return {"message": "Invite code deleted"}


@app.post("/api/admin/reset-database")
def admin_reset_database(
    confirm: str = Query(None),
    db: Session = Depends(get_db),
    _=Depends(verify_admin_password),
):
    """Reset all data — wipe users, jobs, usage_records, invite_codes, system_settings.
    Requires ?confirm=yes to prevent accidental invocation."""
    if confirm != "yes":
        raise HTTPException(status_code=400, detail="Add ?confirm=yes to confirm database reset. This is irreversible.")

    tables = ["usage_records", "jobs", "invite_codes", "system_settings", "users"]
    deleted = {}
    for table in tables:
        result = db.execute(text(f"DELETE FROM {table}"))
        deleted[table] = result.rowcount

    db.commit()

    # Re-seed admin user
    from database import _seed_admin_user
    _seed_admin_user()

    return {"message": "Database reset complete", "deleted": deleted}


def _compute_queue_position(job_id: str) -> int | None:
    """Get a queued job's current position in the Redis queue (1-indexed).
    Matches by the job_id argument passed to generate_deck, not RQ's internal UUID."""
    try:
        for i, rq_job in enumerate(generation_queue.jobs):
            if rq_job.args and rq_job.args[0] == job_id:
                return i + 1
    except Exception:
        pass
    return None


# ── Pipeline artifact endpoints ─────────────────────────────────────────

_PIPELINE_ARTIFACTS = [
    "input_cleaned.json",
    "deck_plan.json",
    "packed_context.json",
    "generation_prompt.txt",
    "quality_report.json",
    "prompt.txt",
]

# Phase 5D: Files that only admins can access (not job owners)
_SENSITIVE_ARTIFACTS = {
    "logs.txt",
    "generation_prompt.txt",
    "packed_context.json",
    "deck_plan.json",
}


@app.get("/api/jobs/{job_id}/artifacts")
def list_artifacts(
    job_id: str,
    db: Session = Depends(get_db),
    token: str | None = Query(None),
    opt_user: User | None = Depends(_get_optional_user),
):
    """List available pipeline artifacts (auth via download_token or JWT). Sensitive files are admin-only."""
    job = _auth_download(job_id, token, opt_user, db)
    is_admin = bool(opt_user and opt_user.is_admin) if opt_user else False

    available = []
    is_s3 = settings.storage_provider == "s3"

    # Phase 5D: Non-admin users cannot see sensitive artifacts
    visible = _PIPELINE_ARTIFACTS if is_admin else [a for a in _PIPELINE_ARTIFACTS if a not in _SENSITIVE_ARTIFACTS]

    for name in visible:
        key_attr = _artifact_key_attr(name)
        if is_s3:
            key = getattr(job, key_attr, None)
            # Fallback to canonical key from path_contract
            if not key:
                at = filename_to_artifact_type(name)
                key = get_storage_key(job_id, at) if at else None
            if key:
                available.append({
                    "filename": name,
                    "size": None,  # S3: size not easily known without HEAD
                    "url": f"{settings.public_backend_url}/api/jobs/{job_id}/artifacts/{name}",
                })
        else:
            fpath = file_manager.get_job_dir(job_id) / name
            if fpath.is_file():
                available.append({
                    "filename": name,
                    "size": fpath.stat().st_size,
                    "url": f"/outputs/{job_id}/{name}",
                })

    return {"job_id": job_id, "artifacts": available}


def _artifact_key_attr(filename: str) -> str:
    """Map artifact filename to Job storage key attribute (from path_contract)."""
    at = filename_to_artifact_type(filename)
    if at is None:
        return ""
    mapping = {
        "index_html": "index_html_key",
        "standalone_html": "standalone_html_key",
        "zip": "zip_key",
        "logs": "logs_key",
        "quality_report": "quality_report_key",
        "deck_plan": "deck_plan_key",
        "packed_context": "packed_context_key",
        "generation_prompt": "generation_prompt_key",
        "input_cleaned": "input_cleaned_key",
        "prompt": "generation_prompt_key",
    }
    return mapping.get(at, "")


@app.get("/api/jobs/{job_id}/artifacts/{filename:path}")
def get_artifact(
    job_id: str,
    filename: str,
    db: Session = Depends(get_db),
    token: str | None = Query(None),
    opt_user: User | None = Depends(_get_optional_user),
):
    """Download/view a specific pipeline artifact (auth via download_token or JWT). Sensitive files admin-only."""
    job = _auth_download(job_id, token, opt_user, db)

    # Phase 5D: Restrict sensitive files to admin only
    if filename in _SENSITIVE_ARTIFACTS:
        if not opt_user or not bool(opt_user.is_admin):
            raise HTTPException(status_code=403, detail="Access denied. Only admins can view this file.")

    allowed = set(_PIPELINE_ARTIFACTS) | {"logs.txt"}
    if filename not in allowed:
        raise HTTPException(status_code=403, detail="File not accessible as artifact")

    is_s3 = settings.storage_provider == "s3"
    if is_s3:
        from services.storage import get_storage_client
        storage = get_storage_client()
        at = filename_to_artifact_type(filename)
        key = get_storage_key(job_id, at) if at else f"jobs/{job_id}/{filename}"
        if not storage.object_exists(key):
            raise HTTPException(status_code=404, detail="Artifact not found")
        url = storage.generate_presigned_url(key)
        return RedirectResponse(url=url, status_code=302)

    file_path = file_manager.get_job_dir(job_id) / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")

    media_type = "application/json" if filename.endswith(".json") else "text/plain"
    return FileResponse(path=str(file_path), filename=filename, media_type=media_type)


# ── Feedback (Phase 5E) ──────────────────────────────────────────────

@app.post("/api/jobs/{job_id}/feedback", response_model=FeedbackResponse)
def submit_feedback(
    job_id: str,
    req: FeedbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit or update feedback for a completed job. Only the job owner can submit."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "success" and job.status != "failed":
        raise HTTPException(status_code=400, detail="Feedback can only be submitted for completed jobs.")
    if job.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only submit feedback for your own jobs.")

    fb = db.query(Feedback).filter(Feedback.job_id == job_id).first()
    if fb:
        fb.rating = req.rating
        fb.content_accuracy = req.content_accuracy
        fb.visual_quality = req.visual_quality
        fb.usefulness = req.usefulness
        fb.would_use_again = 1 if req.would_use_again else 0
        fb.most_needed_feature = req.most_needed_feature
        fb.comment = req.comment
    else:
        fb = Feedback(
            job_id=job_id,
            user_id=current_user.id,
            rating=req.rating,
            content_accuracy=req.content_accuracy,
            visual_quality=req.visual_quality,
            usefulness=req.usefulness,
            would_use_again=1 if req.would_use_again else 0,
            most_needed_feature=req.most_needed_feature,
            comment=req.comment,
        )
        db.add(fb)

    db.commit()
    db.refresh(fb)

    return FeedbackResponse(
        id=fb.id,
        job_id=fb.job_id,
        rating=fb.rating,
        content_accuracy=fb.content_accuracy,
        visual_quality=fb.visual_quality,
        usefulness=fb.usefulness,
        would_use_again=bool(fb.would_use_again),
        most_needed_feature=fb.most_needed_feature,
        comment=fb.comment,
        created_at=fb.created_at.isoformat() if fb.created_at else None,
    )


@app.get("/api/jobs/{job_id}/feedback", response_model=FeedbackResponse)
def get_feedback(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the feedback for a job the current user owns."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not _can_access_job(current_user, job):
        raise HTTPException(status_code=403, detail="Access denied")

    fb = db.query(Feedback).filter(Feedback.job_id == job_id).first()
    if not fb:
        raise HTTPException(status_code=404, detail="No feedback for this job")

    return FeedbackResponse(
        id=fb.id,
        job_id=fb.job_id,
        rating=fb.rating,
        content_accuracy=fb.content_accuracy,
        visual_quality=fb.visual_quality,
        usefulness=fb.usefulness,
        would_use_again=bool(fb.would_use_again),
        most_needed_feature=fb.most_needed_feature,
        comment=fb.comment,
        created_at=fb.created_at.isoformat() if fb.created_at else None,
    )


# ── Download endpoints (Phase 5B: auth via download_token or JWT) ─────

def _auth_download(job_id: str, token: str | None, opt_user: User | None, db: Session) -> Job:
    """Authenticate a download request: download_token first, then JWT fallback."""
    job = _lookup_job(job_id, db)
    # 1. Valid download_token → allow
    if token and job.download_token and token == job.download_token:
        return job
    # 2. Valid JWT user who owns the job → allow
    if opt_user and _can_access_job(opt_user, job):
        return job
    # 3. Neither worked → 401
    raise HTTPException(status_code=401, detail="Authentication required")


@app.get("/api/download/{job_id}/html")
def download_html(
    job_id: str,
    db: Session = Depends(get_db),
    token: str | None = Query(None),
    opt_user: User | None = Depends(_get_optional_user),
):
    job = _auth_download(job_id, token, opt_user, db)
    return _download_or_redirect(job, "index_html_key", "index.html", "text/html",
                                  download_filename=_job_download_name(job, "-standard.html"))


@app.get("/api/download/{job_id}/standalone")
def download_standalone(
    job_id: str,
    db: Session = Depends(get_db),
    token: str | None = Query(None),
    opt_user: User | None = Depends(_get_optional_user),
):
    job = _auth_download(job_id, token, opt_user, db)
    return _download_or_redirect(job, "standalone_html_key", "standalone.html", "text/html",
                                  download_filename=_job_download_name(job, ".html"))


@app.get("/api/download/{job_id}/zip")
def download_zip(
    job_id: str,
    db: Session = Depends(get_db),
    token: str | None = Query(None),
    opt_user: User | None = Depends(_get_optional_user),
):
    job = _auth_download(job_id, token, opt_user, db)
    return _download_or_redirect(job, "zip_key", f"{job_id}.zip", "application/zip",
                                  download_filename=_job_download_name(job, ".zip"))


def _download_or_redirect(job: Job, key_attr: str, filename: str, media_type: str,
                          download: bool = True, download_filename: str | None = None):
    """Return a download response — presigned URL redirect for S3, FileResponse for local.

    All storage keys come from path_contract. Fallback key uses get_storage_key().
    """
    if settings.storage_provider == "s3":
        from services.storage import get_storage_client
        storage = get_storage_client()
        key = getattr(job, key_attr, None)
        if not key:
            # Fallback: compute canonical key from path_contract
            at = filename_to_artifact_type(filename)
            key = get_storage_key(job.id, at) if at else f"jobs/{job.id}/{filename}"
        if not storage.object_exists(key):
            raise HTTPException(status_code=404, detail="File not available")
        dl_name = download_filename or (filename if download else None)
        url = storage.generate_presigned_url(key, download_filename=dl_name)
        return RedirectResponse(url=url, status_code=302)

    # Local mode
    from services import file_manager
    local_path = file_manager.get_job_dir(job.id) / filename
    if local_path.is_file():
        kw: dict = {}
        if download:
            kw["filename"] = download_filename or filename
        return FileResponse(path=str(local_path), media_type=media_type, **kw)
    raise HTTPException(status_code=404, detail="File not found")


# ── Preview endpoint (Phase 5B) ───────────────────────────────────────

@app.get("/api/preview/{job_id}")
def preview_job(
    job_id: str,
    type: str = Query("index", description="index or standalone"),
    db: Session = Depends(get_db),
    token: str | None = Query(None),
    opt_user: User | None = Depends(_get_optional_user),
):
    """Serve index.html or standalone.html for preview (auth via download_token or JWT)."""
    job = _auth_download(job_id, token, opt_user, db)

    if type == "standalone":
        key_attr = "standalone_html_key"
        artifact_type: ArtifactType = "standalone_html"
    else:
        key_attr = "index_html_key"
        artifact_type = "index_html"

    filename = artifact_filename(artifact_type)

    if settings.storage_provider == "s3":
        from services.storage import get_storage_client
        storage = get_storage_client()
        key = getattr(job, key_attr, None) or get_storage_key(job_id, artifact_type)
        if not storage.object_exists(key):
            raise HTTPException(status_code=404, detail="Preview not available")
        url = storage.generate_presigned_url(key)
        return RedirectResponse(url=url, status_code=302)

    local_path = file_manager.get_job_dir(job_id) / filename
    if local_path.is_file():
        return FileResponse(path=str(local_path), media_type="text/html")
    raise HTTPException(status_code=404, detail="Preview not available")


# ── Admin file access (Phase 5B) ──────────────────────────────────────

@app.get("/api/admin/jobs/{job_id}/logs")
def admin_download_logs(
    job_id: str,
    db: Session = Depends(get_db),
    _=Depends(verify_admin_password),
):
    """Admin: download logs.txt for a job."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if settings.storage_provider == "s3" and job.logs_key:
        from services.storage import get_storage_client
        storage = get_storage_client()
        url = storage.generate_presigned_url(job.logs_key)
        return RedirectResponse(url=url, status_code=302)

    if job.logs_path:
        logs_path = Path(job.logs_path)
        if logs_path.is_file():
            return FileResponse(path=str(logs_path), filename="logs.txt", media_type="text/plain")

    raise HTTPException(status_code=404, detail="Logs not available")


# ── Admin path check endpoint (Phase 5H) ──────────────────────────────

@app.get("/api/admin/jobs/{job_id}/path-check")
def admin_view_path_check(
    job_id: str,
    db: Session = Depends(get_db),
    _=Depends(verify_admin_password),
):
    """Admin: view path_check.json for a job."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if settings.storage_provider == "s3" and job.path_check_key:
        from services.storage import get_storage_client
        storage = get_storage_client()
        url = storage.generate_presigned_url(job.path_check_key)
        return RedirectResponse(url=url, status_code=302)

    # Local mode: look for path_check.json in job dir
    if job.output_dir:
        pc_path = Path(job.output_dir) / "path_check.json"
        if pc_path.is_file():
            return FileResponse(path=str(pc_path), filename="path_check.json",
                                media_type="application/json")

    raise HTTPException(status_code=404, detail="Path check not available")


# ── CSV Export (Phase 5E) ────────────────────────────────────────────

import csv
import io
from fastapi.responses import StreamingResponse


def _auth_export(admin_password_q: str | None = Query(None),
                 x_admin_password: str | None = Header(None)) -> None:
    """Auth for CSV export — accepts header or query param (<a> tag support)."""
    if not settings.admin_password:
        return
    if x_admin_password == settings.admin_password:
        return
    if admin_password_q == settings.admin_password:
        return
    raise HTTPException(status_code=401, detail="Invalid admin password")


@app.get("/api/admin/export/jobs.csv")
def admin_export_jobs_csv(db: Session = Depends(get_db), _=Depends(_auth_export)):
    """Export all jobs as CSV."""
    rows = db.query(Job, User).outerjoin(User, Job.user_id == User.id).order_by(Job.created_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["job_id", "status", "user_name", "user_email", "topic", "language", "style",
                      "slide_count", "content_chars", "quality_status", "quality_score",
                      "estimated_input_tokens", "estimated_output_tokens",
                      "created_at", "started_at", "finished_at", "error_message"])
    for j, u in rows:
        writer.writerow([
            j.id, j.status,
            u.name if u else "", u.email if u else "",
            j.topic, j.language, j.style,
            j.slide_count, j.content_chars,
            j.quality_status, j.quality_score,
            j.estimated_input_tokens, j.estimated_output_tokens,
            j.created_at.isoformat() if j.created_at else "",
            j.started_at.isoformat() if j.started_at else "",
            j.finished_at.isoformat() if j.finished_at else "",
            (j.error_message or "")[:500],
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=jobs.csv"},
    )


@app.get("/api/admin/export/users.csv")
def admin_export_users_csv(db: Session = Depends(get_db), _=Depends(_auth_export)):
    """Export all users with usage stats as CSV."""
    now = datetime.now(timezone.utc)
    month_key = now.strftime("%Y-%m")
    users = db.query(User).order_by(User.created_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["user_id", "name", "email", "is_admin", "can_generate",
                      "total_jobs", "success_jobs", "failed_jobs",
                      "this_month_generations", "created_at", "last_login_at"])
    for u in users:
        total_jobs = db.query(func.count(Job.id)).filter(Job.user_id == u.id).scalar() or 0
        success = db.query(func.count(Job.id)).filter(Job.user_id == u.id, Job.status == "success").scalar() or 0
        failed = db.query(func.count(Job.id)).filter(Job.user_id == u.id, Job.status == "failed").scalar() or 0
        usage = db.query(UsageRecord).filter(UsageRecord.user_id == u.id, UsageRecord.month == month_key).first()
        this_month = usage.generation_count if usage else 0
        writer.writerow([
            u.id, u.name, u.email,
            1 if u.is_admin else 0, 1 if u.can_generate else 0,
            total_jobs, success, failed, this_month,
            u.created_at.isoformat() if u.created_at else "",
            u.last_login_at.isoformat() if u.last_login_at else "",
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=users.csv"},
    )


@app.get("/api/admin/export/feedback.csv")
def admin_export_feedback_csv(db: Session = Depends(get_db), _=Depends(_auth_export)):
    """Export all feedback as CSV."""
    rows = db.query(Feedback, User, Job).join(User, Feedback.user_id == User.id) \
        .join(Job, Feedback.job_id == Job.id).order_by(Feedback.created_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["feedback_id", "job_id", "user_name", "user_email", "topic",
                      "rating", "content_accuracy", "visual_quality", "usefulness",
                      "would_use_again", "most_needed_feature", "comment", "created_at"])
    for fb, u, j in rows:
        writer.writerow([
            fb.id, fb.job_id, u.name, u.email, j.topic,
            fb.rating, fb.content_accuracy, fb.visual_quality, fb.usefulness,
            1 if fb.would_use_again else 0,
            fb.most_needed_feature or "", (fb.comment or "")[:500],
            fb.created_at.isoformat() if fb.created_at else "",
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=feedback.csv"},
    )


# ── Static file serving (outputs & examples) — must be last ────────────

# Only mount static /outputs in local mode; S3 mode uses presigned URLs
if settings.storage_provider != "s3" and OUTPUTS_DIR.exists():
    app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR), html=True), name="outputs")

# Phase 4G: Serve example standalone.html files
_examples_dir = BASE_DIR.parent / "frontend" / "public" / "Examples"
if _examples_dir.exists():
    app.mount("/examples", StaticFiles(directory=str(_examples_dir), html=True), name="examples")
