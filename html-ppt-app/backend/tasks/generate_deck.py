import json
import os
import shutil
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from database import SessionLocal
from models import Job
from services import file_manager
from services.claude_runner import run_claude
from services.html_inliner import inline_html
from services.storage import get_storage_client
from settings import settings


# Threshold: content below this uses the simple prompt path (no pipeline)
PIPELINE_MIN_CONTENT_CHARS = 1000


def _resolve_job_dir(job_id: str) -> Path:
    """Return the working directory for job generation."""
    if settings.storage_provider == "s3":
        tmp = Path(tempfile.gettempdir()) / "htmlppt-jobs" / job_id
        tmp.mkdir(parents=True, exist_ok=True)
        return tmp
    else:
        return file_manager.create_job_dir(job_id)


def _upload_outputs(job: Job, job_dir: Path) -> None:
    """Upload all generated outputs to object storage and write storage keys to DB."""
    storage = get_storage_client()
    jid = job.id

    files_to_upload = {
        "index_html_key": ("index.html", "text/html; charset=utf-8"),
        "standalone_html_key": ("standalone.html", "text/html; charset=utf-8"),
        "zip_key": (f"{jid}.zip", "application/zip"),
        "logs_key": ("logs.txt", "text/plain; charset=utf-8"),
        "quality_report_key": ("quality_report.json", "application/json"),
        "deck_plan_key": ("deck_plan.json", "application/json"),
        "packed_context_key": ("packed_context.json", "application/json"),
        "input_cleaned_key": ("input_cleaned.json", "application/json"),
        "generation_prompt_key": ("generation_prompt.txt", "text/plain; charset=utf-8"),
    }

    for attr, (filename, _content_type) in files_to_upload.items():
        local_path = job_dir / filename
        if local_path.is_file():
            key = f"jobs/{jid}/{filename}"
            storage.upload_file(local_path, key)
            setattr(job, attr, key)

    # Zip lives in parent dir (alongside job dir), not inside it
    zip_at_parent = job_dir.parent / f"{jid}.zip"
    if zip_at_parent.is_file() and not job.zip_key:
        key = f"jobs/{jid}/{jid}.zip"
        storage.upload_file(zip_at_parent, key)
        job.zip_key = key


def _setup_request(job: Job) -> SimpleNamespace:
    return SimpleNamespace(
        language=job.language or "English",
        topic=job.topic or "Untitled Presentation",
        content=job.content or "",
        style=job.style or "professional",
        audience=job.audience or "general audience",
        extra_requirements=job.extra_requirements or "",
        slide_count=job.slide_count or 10,
        search_level=job.search_level or "none",
    )


def generate_deck(job_id: str):
    """RQ task: generate an HTML PPT deck for the given job_id."""
    db = SessionLocal()
    job_obj = None
    job_dir = None
    logs_path = None
    is_s3 = settings.storage_provider == "s3"

    try:
        job_obj = db.query(Job).filter(Job.id == job_id).first()
        if not job_obj:
            return

        # ── Mark running ──────────────────────────────────────────────
        job_obj.status = "running"
        job_obj.started_at = datetime.now(timezone.utc)
        job_obj.worker_name = os.environ.get("WORKER_NAME", None)
        db.commit()

        # ── Set up working directory ───────────────────────────────────
        job_dir = _resolve_job_dir(job_id)
        logs_path = job_dir / "logs.txt"

        # Still store paths on DB for local mode (backward compat)
        job_obj.output_dir = str(job_dir)
        job_obj.logs_path = str(logs_path)
        db.commit()

        request = _setup_request(job_obj)
        content = job_obj.content or ""
        use_pipeline = len(content.strip()) >= PIPELINE_MIN_CONTENT_CHARS

        if use_pipeline:
            prompt = _run_pipeline(request, job_dir, logs_path)
        else:
            prompt = _run_simple_prompt(request, job_dir)

        # Write prompt file (overwritten if pipeline already wrote it)
        prompt_file = job_dir / "prompt.txt"
        if not prompt_file.exists():
            prompt_file.write_text(prompt, encoding="utf-8")

        # Store prompt char count for token estimation
        job_obj.generation_prompt_chars = len(prompt)
        job_obj.model_name = "claude-code"
        db.commit()

        # ── Run Claude Code ────────────────────────────────────────────
        if is_s3:
            # In S3 mode, set cwd to job_dir so Claude writes there
            old_cwd = os.getcwd()
            os.chdir(str(job_dir))
        exit_code = run_claude(job_dir, logs_path)
        if is_s3:
            os.chdir(old_cwd)

        if exit_code == -2:
            _fail_job(db, job_obj,
                "Claude Code CLI not found. Install Claude Code CLI or set CLAUDE_CODE_COMMAND.",
                logs_path, job_dir)
            return

        if exit_code == -1:
            _fail_job(db, job_obj,
                f"Generation timed out after {settings.claude_timeout} seconds.",
                logs_path, job_dir)
            return

        # ── Verify output ──────────────────────────────────────────────
        index_html = job_dir / "index.html"
        if not index_html.is_file():
            if exit_code != 0:
                _fail_job(db, job_obj,
                    f"Claude Code exited with code {exit_code}. Check logs.", logs_path, job_dir)
            else:
                _fail_job(db, job_obj,
                    "Claude Code completed but index.html was not generated. "
                    "The html-ppt-skill may not be installed.", logs_path, job_dir)
            return

        # ── Run inliner → standalone.html ──────────────────────────────
        try:
            inline_html(job_dir)
        except Exception as e:
            with open(logs_path, "a", encoding="utf-8") as f:
                f.write(f"\n=== Standalone inliner warning ===\n{e}\n")

        # ── Create zip ─────────────────────────────────────────────────
        zip_path = file_manager.create_zip(job_id)
        job_obj.zip_path = str(zip_path)

        # ── Quality check ───────────────────────────────────────────────
        quality_report = _run_quality_check(job_dir, logs_path, use_pipeline=use_pipeline)
        if quality_report:
            job_obj.quality_status = quality_report.get("status")
            job_obj.quality_score = quality_report.get("score")
            job_obj.quality_warnings_count = quality_report.get("warning_count")
            job_obj.quality_errors_count = quality_report.get("failed")
            db.commit()

        # ── Token estimation ────────────────────────────────────────────
        from services.token_estimator import estimate_tokens

        gen_prompt_file = job_dir / "generation_prompt.txt"
        simple_prompt_file = job_dir / "prompt.txt"
        prompt_text = ""
        if gen_prompt_file.is_file():
            prompt_text = gen_prompt_file.read_text(encoding="utf-8")
        elif simple_prompt_file.is_file():
            prompt_text = simple_prompt_file.read_text(encoding="utf-8")

        html_text = index_html.read_text(encoding="utf-8")
        job_obj.generated_html_chars = len(html_text)
        job_obj.estimated_input_tokens = estimate_tokens(prompt_text)
        job_obj.estimated_output_tokens = estimate_tokens(html_text)
        db.commit()

        # ── Upload to storage (S3 mode) ─────────────────────────────────
        if is_s3:
            _upload_outputs(job_obj, job_dir)

        # ── Mark success ───────────────────────────────────────────────
        job_obj.status = "success"
        job_obj.index_html_path = str(index_html)
        job_obj.standalone_html_path = str(job_dir / "standalone.html")
        job_obj.finished_at = datetime.now(timezone.utc)
        db.commit()

    except Exception:
        tb = traceback.format_exc()
        _fail_job(db, job_obj, f"Internal error:\n{tb}", logs_path, job_dir)
    finally:
        # Clean up temp dir in S3 mode
        if is_s3 and job_dir and job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
        db.close()


def _run_pipeline(request, job_dir: Path, logs_path: Path) -> str:
    """Run Steps 1–3 of the generation pipeline, return the generation prompt."""
    from services.pipeline.input_cleaner import clean
    from services.pipeline.deck_planner import plan
    from services.pipeline.context_packer import pack
    from services.pipeline.prompt_builder import build

    content = request.content.strip()
    log = _log_writer(logs_path)

    log("=== Phase 4D Pipeline: Steps 1-3 ===\n")

    # Step 1: Input Cleaning
    log("[Step 1/3] Input Cleaning...")
    cleaned = clean(content)
    _save_json(job_dir / "input_cleaned.json", cleaned)
    log(f"  → {len(cleaned.get('sections', []))} sections, "
        f"{len(cleaned.get('tables', []))} tables, "
        f"{len(cleaned.get('global_entities', {}).get('companies', []))} companies, "
        f"{len(cleaned.get('global_entities', {}).get('technologies', []))} technologies, "
        f"{len(cleaned.get('global_entities', {}).get('metrics', []))} metrics")

    # Step 2: Deck Planning
    log("[Step 2/3] Deck Planning...")
    deck_plan = plan(
        cleaned,
        target_slide_count=request.slide_count or 10,
        audience=request.audience or "",
        style=request.style or "professional",
        language=request.language or "English",
    )
    _save_json(job_dir / "deck_plan.json", deck_plan)
    log(f"  → {len(deck_plan.get('slides', []))} slides planned "
        f"(type: {deck_plan.get('deck_type', 'unknown')})")

    # Step 3: Context Packing
    log("[Step 3/3] Context Packing...")
    packed = pack(cleaned, deck_plan)
    _save_json(job_dir / "packed_context.json", packed)
    total_ctx_chars = sum(
        sum(len(ctx.get("excerpt", "")) for ctx in s.get("source_context", []))
        for s in packed.get("slides", [])
    )
    log(f"  → {len(packed.get('slides', []))} slides with context "
        f"({total_ctx_chars:,} chars total)")

    # Step 4: Build generation prompt
    log("[Step 4] Building generation prompt...")
    prompt = build(
        topic=request.topic or "Untitled Presentation",
        language=request.language or "English",
        style=request.style or "professional",
        audience=request.audience or "",
        extra_requirements=request.extra_requirements or "",
        deck_plan=deck_plan,
        packed_context=packed,
        job_dir=job_dir,
        search_level=request.search_level or "none",
    )
    (job_dir / "generation_prompt.txt").write_text(prompt, encoding="utf-8")
    log(f"  → Prompt: {len(prompt):,} chars\n")

    return prompt


def _run_simple_prompt(request, job_dir: Path) -> str:
    """Short input: use the simple prompt from claude_runner."""
    from services.claude_runner import build_prompt
    prompt = build_prompt(request, job_dir)
    (job_dir / "generation_prompt.txt").write_text(prompt, encoding="utf-8")
    return prompt


def _run_quality_check(job_dir: Path, logs_path: Path, use_pipeline: bool = False):
    """Run quality checks and save report. Returns the report dict or None."""
    from services.pipeline.quality_checker import check as qc

    log = _log_writer(logs_path)
    log("\n=== Quality Check ===\n")

    deck_plan = None
    packed = None
    input_cleaned = None

    if use_pipeline:
        try:
            deck_plan = json.loads((job_dir / "deck_plan.json").read_text(encoding="utf-8"))
            packed = json.loads((job_dir / "packed_context.json").read_text(encoding="utf-8"))
            input_cleaned = json.loads((job_dir / "input_cleaned.json").read_text(encoding="utf-8"))
        except Exception:
            log("  → Pipeline artifacts not found, running basic checks only.\n")

    report = qc(job_dir, deck_plan=deck_plan, packed_context=packed, input_cleaned=input_cleaned)
    _save_json(job_dir / "quality_report.json", report)

    log(f"  → Status: {report.get('status', 'unknown')}, Score: {report.get('score', 0)}/100")
    log(f"  → Passed: {report.get('passed', 0)}, "
        f"Warnings: {report.get('warning_count', 0)}, "
        f"Failed: {report.get('failed', 0)}")
    for c in report.get("checks", []):
        icon = {"PASS": "[OK]", "WARN": "[WARN]", "FAIL": "[FAIL]"}.get(c.get("result", ""), "?")
        log(f"     [{icon}] {c['name']}: {c.get('message', '')}")
    log("")

    return report


def _save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _log_writer(logs_path: Path):
    def write(msg: str):
        with open(logs_path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    return write


def _fail_job(db, job: Job | None, error_message: str, logs_path: Path | None, job_dir: Path | None = None):
    """Mark job as failed, write error to log, and upload logs in S3 mode."""
    if job is None:
        try:
            db.commit()
        except Exception:
            pass
        return

    job.status = "failed"
    job.error_message = error_message
    job.finished_at = datetime.now(timezone.utc)

    if logs_path:
        job.logs_path = str(logs_path)
        try:
            with open(logs_path, "a", encoding="utf-8") as f:
                f.write(f"\n=== ERROR ===\n{error_message}\n")
        except Exception:
            pass

        # In S3 mode, upload logs so admin can inspect
        if settings.storage_provider == "s3":
            try:
                storage = get_storage_client()
                key = f"jobs/{job.id}/logs.txt"
                storage.upload_file(logs_path, key)
                job.logs_key = key
            except Exception:
                pass

    try:
        db.commit()
    except Exception:
        pass
