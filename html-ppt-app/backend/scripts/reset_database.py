"""Phase 5D: Reset database to a clean state — wipe all data, keep schema.

Usage:
    # Local SQLite:
    cd html-ppt-app/backend && python scripts/reset_database.py

    # Railway PostgreSQL (copy DATABASE_URL from Railway → PostgreSQL → Connect):
    DATABASE_URL="postgresql://..." python scripts/reset_database.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from database import SessionLocal, init_db

# Ensure tables exist before we try to truncate
init_db()

db = SessionLocal()
try:
    # Foreign key order matters — delete children before parents
    tables = ["usage_records", "jobs", "invite_codes", "system_settings", "users"]
    for table in tables:
        result = db.execute(text(f"DELETE FROM {table}"))
        print(f"  {table}: {result.rowcount} rows deleted")

    db.commit()
    print("\nAll data cleared. Schema preserved.")
    print("The admin seed user (dchen022@e.ntu.edu.sg) will be re-created on next backend startup.")
except Exception as e:
    db.rollback()
    print(f"Error: {e}")
    sys.exit(1)
finally:
    db.close()
