"""Apply schema and pending migrations without deleting data."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db


if __name__ == "__main__":
    applied = db.apply_schema()
    print("Applied: " + ", ".join(applied) if applied else "Database schema is up to date")
