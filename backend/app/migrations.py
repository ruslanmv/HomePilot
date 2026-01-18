"""
Database migration runner for HomePilot
Applies SQL migrations from backend/migrations directory
"""
import sqlite3
from pathlib import Path
from typing import List
from .config import SQLITE_PATH


def get_migrations_dir() -> Path:
    """Get the migrations directory path"""
    backend_dir = Path(__file__).resolve().parents[1]
    return backend_dir / "migrations"


def get_applied_migrations(conn: sqlite3.Connection) -> List[str]:
    """Get list of already applied migrations"""
    cursor = conn.cursor()

    # Create migrations table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    # Get applied migrations
    cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
    return [row[0] for row in cursor.fetchall()]


def apply_migration(conn: sqlite3.Connection, version: str, sql: str) -> None:
    """Apply a single migration"""
    cursor = conn.cursor()

    # Execute migration SQL
    cursor.executescript(sql)

    # Record migration as applied
    cursor.execute(
        "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
        (version,)
    )

    conn.commit()


def run_migrations() -> None:
    """
    Run all pending migrations
    Migrations are SQL files in backend/migrations/
    Named like: 001_command_center.sql, 002_feature.sql, etc.
    """
    migrations_dir = get_migrations_dir()

    if not migrations_dir.exists():
        print(f"Migrations directory not found: {migrations_dir}")
        return

    # Connect to database
    conn = sqlite3.connect(SQLITE_PATH)

    try:
        # Get applied migrations
        applied = get_applied_migrations(conn)

        # Find all migration files
        migration_files = sorted(migrations_dir.glob("*.sql"))

        if not migration_files:
            print("No migration files found")
            return

        # Apply pending migrations
        for migration_file in migration_files:
            version = migration_file.stem  # e.g., "001_command_center"

            if version in applied:
                print(f"✓ Migration {version} already applied")
                continue

            print(f"→ Applying migration {version}...")
            sql = migration_file.read_text()
            apply_migration(conn, version, sql)
            print(f"✓ Migration {version} applied successfully")

        print("All migrations applied successfully")

    except Exception as e:
        print(f"Migration error: {e}")
        conn.rollback()
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    run_migrations()
