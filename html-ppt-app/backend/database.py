import shutil
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from settings import settings


def _is_sqlite() -> bool:
    return settings.database_url.startswith("sqlite:///") or settings.database_url.startswith("sqlite://")


def _is_postgresql() -> bool:
    return settings.database_url.startswith("postgresql://") or settings.database_url.startswith("postgres://")


# ── Engine ────────────────────────────────────────────────────────────────
if _is_sqlite():
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        echo=False,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()
else:
    try:
        import psycopg2  # noqa: F401
    except ImportError:
        raise ImportError(
            "DATABASE_URL is a PostgreSQL URL but psycopg2 is not installed. "
            "Either install psycopg2-binary or switch DATABASE_URL to sqlite:////data/app.db for local/Volume mode."
        )
    engine = create_engine(
        settings.database_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        echo=False,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    import models  # noqa: F401 — ensure models are loaded
    Base.metadata.create_all(bind=engine)
    _migrate()
    _cleanup_temp_job_dirs()


def _migrate():
    """Add missing columns to existing tables (safe to run on fresh DB too)."""
    inspector = inspect(engine)

    # ── jobs table ────────────────────────────────────────────────────
    if inspector.has_table("jobs"):
        existing = {col["name"] for col in inspector.get_columns("jobs")}
        additions = [
            ("worker_name", "VARCHAR"),
            ("queue_position", "INTEGER"),
            ("retry_count", "INTEGER DEFAULT 0"),
            # Phase 4C
            ("estimated_input_tokens", "INTEGER"),
            ("estimated_output_tokens", "INTEGER"),
            ("model_name", "VARCHAR"),
            ("generation_prompt_chars", "INTEGER"),
            ("generated_html_chars", "INTEGER"),
            # Phase 4E
            ("quality_status", "VARCHAR"),
            ("quality_score", "INTEGER"),
            ("quality_warnings_count", "INTEGER"),
            ("quality_errors_count", "INTEGER"),
            # Phase 4F
            ("user_id", "VARCHAR"),
            # Phase 5B: Storage keys (S3 object keys)
            ("index_html_key", "VARCHAR"),
            ("standalone_html_key", "VARCHAR"),
            ("zip_key", "VARCHAR"),
            ("logs_key", "VARCHAR"),
            ("quality_report_key", "VARCHAR"),
            ("deck_plan_key", "VARCHAR"),
            ("packed_context_key", "VARCHAR"),
            ("input_cleaned_key", "VARCHAR"),
            ("generation_prompt_key", "VARCHAR"),
            # Download token for auth-free download/preview links
            ("download_token", "VARCHAR"),
        ]
        with engine.connect() as conn:
            for col_name, col_type in additions:
                if col_name not in existing:
                    conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_type}"))
                    conn.commit()

    # ── Backfill download_token for existing jobs ─────────────────────
    if inspector.has_table("jobs"):
        import secrets
        cols = {col["name"] for col in inspector.get_columns("jobs")}
        if "download_token" in cols:
            with engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT id, download_token FROM jobs WHERE status = 'success' AND download_token IS NULL")
                ).fetchall()
                for row in rows:
                    tok = secrets.token_urlsafe(16)
                    conn.execute(
                        text("UPDATE jobs SET download_token = :tok WHERE id = :jid"),
                        {"tok": tok, "jid": row[0]},
                    )
                if rows:
                    conn.commit()

    # ── system_settings table ─────────────────────────────────────────
    if not inspector.has_table("system_settings"):
        import models  # noqa: F811
        Base.metadata.create_all(bind=engine, tables=[models.SystemSetting.__table__])

    # ── users table ───────────────────────────────────────────────────
    if not inspector.has_table("users"):
        import models  # noqa: F811
        Base.metadata.create_all(bind=engine, tables=[models.User.__table__])
    else:
        user_cols = {col["name"] for col in inspector.get_columns("users")}
        user_additions = [
            ("password_hash", "VARCHAR DEFAULT ''"),
            ("last_login_at", "DATETIME"),
            ("is_admin", "INTEGER DEFAULT 0"),
            ("can_generate", "INTEGER DEFAULT 1"),
        ]
        with engine.connect() as conn:
            for col_name, col_type in user_additions:
                if col_name not in user_cols:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"))
                    conn.commit()

    # ── Seed admin user ───────────────────────────────────────────────
    _seed_admin_user()

    # ── usage_records table ───────────────────────────────────────────
    if not inspector.has_table("usage_records"):
        import models  # noqa: F811
        Base.metadata.create_all(bind=engine, tables=[models.UsageRecord.__table__])


def _seed_admin_user():
    """Ensure dchen022@e.ntu.edu.sg is an admin with unlimited generations."""
    from models import User
    db = SessionLocal()
    try:
        admin_email = "dchen022@e.ntu.edu.sg"
        user = db.query(User).filter(User.email == admin_email).first()
        if user and (not user.is_admin or not user.can_generate):
            user.is_admin = True
            user.can_generate = True
            db.commit()
    finally:
        db.close()


def _cleanup_temp_job_dirs():
    """Remove orphaned temp job directories from previous worker runs."""
    for tmp_root in [
        Path(tempfile.gettempdir()) / "htmlppt-jobs",
        Path("/app/tmp/htmlppt-jobs"),
    ]:
        if tmp_root.is_dir():
            shutil.rmtree(tmp_root, ignore_errors=True)
