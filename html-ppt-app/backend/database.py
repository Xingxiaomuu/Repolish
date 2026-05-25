from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from settings import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    echo=False,
)

# Enable WAL mode for concurrent writer safety
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()

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
        ]
        with engine.connect() as conn:
            for col_name, col_type in additions:
                if col_name not in existing:
                    conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_type}"))
                    conn.commit()

    # ── system_settings table ─────────────────────────────────────────
    if not inspector.has_table("system_settings"):
        import models  # noqa: F811
        Base.metadata.create_all(bind=engine, tables=[models.SystemSetting.__table__])

    # ── users table (Phase 4F) ────────────────────────────────────────
    if not inspector.has_table("users"):
        import models  # noqa: F811
        Base.metadata.create_all(bind=engine, tables=[models.User.__table__])
    else:
        # Phase 4G: add password_hash and last_login_at
        user_cols = {col["name"] for col in inspector.get_columns("users")}
        user_additions = [
            ("password_hash", "VARCHAR DEFAULT ''"),
            ("last_login_at", "DATETIME"),
            # Phase 4G+: admin + generation control
            ("is_admin", "INTEGER DEFAULT 0"),
            ("can_generate", "INTEGER DEFAULT 1"),
        ]
        with engine.connect() as conn:
            for col_name, col_type in user_additions:
                if col_name not in user_cols:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"))
                    conn.commit()

    # ── Seed admin user ────────────────────────────────────────────────
    _seed_admin_user()

    # ── usage_records table (Phase 4F) ────────────────────────────────
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

