import json
import re
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from pathlib import Path

import redis
from fastapi import FastAPI, HTTPException, Depends, Query, Header
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
    User, UsageRecord, SystemSetting,
    RegisterRequest, LoginRequest, LoginResponse, UserResponse,
    MyJobItem, MyUsageResponse,
    AdminSummaryResponse, AdminJobItem, AdminJobListResponse, AdminJobDetail,
    AdminUserItem, AdminUserListResponse, AdminStatsResponse,
    SettingUpdate, SettingItem, UpdateUserRequest,
)
from services import file_manager
from services.admin_auth import verify_admin_password
from settings import settings

BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def _can_access_job(current_user: User, job: Job) -> bool:
    """User can access a job if they own it or are admin."""
    return bool(current_user.is_admin) or job.user_id == current_user.id

def _lookup_job(job_id: str, db: Session) -> Job:
    """Look up a successful job or raise 404."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job or job.status != "success":
        raise HTTPException(status_code=404, detail="Job not found")
    return job


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
def auth_register(req: RegisterRequest, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    name = req.name.strip()

    if not email or not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="A valid email address is required.")
    if not name:
        raise HTTPException(status_code=400, detail="Please provide your name.")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")

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
    db.commit()

    return {"message": "Registration successful. Please login."}


@app.post("/api/auth/login", response_model=LoginResponse)
def auth_login(req: LoginRequest, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required.")

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

    # ── Permission check ───────────────────────────────────────────────
    if not current_user.can_generate:
        raise HTTPException(
            status_code=403,
            detail="Your account has been restricted from generating. Please contact the admin.",
        )

    # ── Rate limiting (skipped for admins) ─────────────────────────────
    now = datetime.now(timezone.utc)
    month_key = now.strftime("%Y-%m")
    limit = settings.free_generations_per_month
    is_admin = bool(current_user.is_admin)

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
    limit = settings.free_generations_per_month

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
    limit = settings.free_generations_per_month

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
            monthly_limit=limit,
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
        user.is_admin = req.is_admin
    if req.can_generate is not None:
        user.can_generate = req.can_generate

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


@app.get("/api/jobs/{job_id}/artifacts")
def list_artifacts(
    job_id: str,
    db: Session = Depends(get_db),
    token: str | None = Query(None),
    opt_user: User | None = Depends(_get_optional_user),
):
    """List available pipeline artifacts for a job (auth via download_token or JWT)."""
    job = _auth_download(job_id, token, opt_user, db)

    available = []
    is_s3 = settings.storage_provider == "s3"

    for name in _PIPELINE_ARTIFACTS:
        key_attr = _artifact_key_attr(name)
        if is_s3:
            key = getattr(job, key_attr, None)
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
    """Map artifact filename to Job storage key attribute."""
    mapping = {
        "input_cleaned.json": "input_cleaned_key",
        "deck_plan.json": "deck_plan_key",
        "packed_context.json": "packed_context_key",
        "generation_prompt.txt": "generation_prompt_key",
        "quality_report.json": "quality_report_key",
        "prompt.txt": "generation_prompt_key",
    }
    return mapping.get(filename, "")


@app.get("/api/jobs/{job_id}/artifacts/{filename:path}")
def get_artifact(
    job_id: str,
    filename: str,
    db: Session = Depends(get_db),
    token: str | None = Query(None),
    opt_user: User | None = Depends(_get_optional_user),
):
    """Download/view a specific pipeline artifact (auth via download_token or JWT)."""
    job = _auth_download(job_id, token, opt_user, db)

    allowed = set(_PIPELINE_ARTIFACTS) | {"logs.txt"}
    if filename not in allowed:
        raise HTTPException(status_code=403, detail="File not accessible as artifact")

    is_s3 = settings.storage_provider == "s3"
    if is_s3:
        from services.storage import get_storage_client
        storage = get_storage_client()
        key = f"jobs/{job_id}/{filename}"
        if not storage.object_exists(key):
            raise HTTPException(status_code=404, detail="Artifact not found")
        url = storage.generate_presigned_url(key)
        return RedirectResponse(url=url, status_code=302)

    file_path = file_manager.get_job_dir(job_id) / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")

    media_type = "application/json" if filename.endswith(".json") else "text/plain"
    return FileResponse(path=str(file_path), filename=filename, media_type=media_type)


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
    return _download_or_redirect(job, "index_html_key", "index.html", "text/html")


@app.get("/api/download/{job_id}/standalone")
def download_standalone(
    job_id: str,
    db: Session = Depends(get_db),
    token: str | None = Query(None),
    opt_user: User | None = Depends(_get_optional_user),
):
    job = _auth_download(job_id, token, opt_user, db)
    return _download_or_redirect(job, "standalone_html_key", "standalone.html", "text/html")


@app.get("/api/download/{job_id}/zip")
def download_zip(
    job_id: str,
    db: Session = Depends(get_db),
    token: str | None = Query(None),
    opt_user: User | None = Depends(_get_optional_user),
):
    job = _auth_download(job_id, token, opt_user, db)
    return _download_or_redirect(job, "zip_key", f"{job_id}.zip", "application/zip")


def _download_or_redirect(job: Job, key_attr: str, filename: str, media_type: str):
    """Return a download response — presigned URL redirect for S3, FileResponse for local."""
    if settings.storage_provider == "s3":
        from services.storage import get_storage_client
        storage = get_storage_client()
        key = getattr(job, key_attr, None) or f"jobs/{job.id}/{filename}"
        if not storage.object_exists(key):
            raise HTTPException(status_code=404, detail="File not available")
        url = storage.generate_presigned_url(key)
        return RedirectResponse(url=url, status_code=302)

    # Local mode
    from services import file_manager
    local_path = file_manager.get_job_dir(job.id) / filename
    if local_path.is_file():
        return FileResponse(path=str(local_path), filename=filename, media_type=media_type)
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
        filename = "standalone.html"
    else:
        key_attr = "index_html_key"
        filename = "index.html"

    if settings.storage_provider == "s3":
        from services.storage import get_storage_client
        storage = get_storage_client()
        key = getattr(job, key_attr, None) or f"jobs/{job_id}/{filename}"
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


# ── Static file serving (outputs & examples) — must be last ────────────

# Only mount static /outputs in local mode; S3 mode uses presigned URLs
if settings.storage_provider != "s3" and OUTPUTS_DIR.exists():
    app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR), html=True), name="outputs")

# Phase 4G: Serve example standalone.html files
_examples_dir = BASE_DIR.parent / "frontend" / "public" / "Examples"
if _examples_dir.exists():
    app.mount("/examples", StaticFiles(directory=str(_examples_dir), html=True), name="examples")
