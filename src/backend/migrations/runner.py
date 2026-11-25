"""
Versioned database migration runner - the release step (inspection finding F-26).

Before: the runner called SQLAlchemy `create_all` and then executed `infra/init-db.sql`
split on ';', printing and *ignoring* every failing statement, with no record of what had
been applied. A broken migration could therefore "succeed".

Now:
  * the ordered `NNN_*.sql` files in this directory are the schema source of truth;
  * each file runs in its own transaction and stops the release on the first error;
  * `schema_migrations` records version, file name and SHA-256 checksum; an applied file
    whose content later changes is a hard error (migrations are immutable);
  * the least-privileged application role is created (or its password rotated) from
    APP_DB_PASSWORD - no password is committed for non-development databases;
  * a session-level advisory lock prevents two releases migrating concurrently.

Usage (run with an owner/admin connection, never the application role):
    MIGRATION_DATABASE_URL=postgresql://owner:...@db:5432/sales_ai_db \\
    APP_DB_PASSWORD=... python -m src.backend.migrations.runner [--status] [--baseline 017]

`--baseline N` marks 001..N as applied without running them (for a database that was
bootstrapped from infra/init-db.sql before version tracking existed).
"""
import argparse
import hashlib
import os
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import psycopg
from psycopg import sql

MIGRATIONS_DIR = Path(__file__).resolve().parent
FILE_PATTERN = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
LOCK_KEY = 0x5A1E5A1  # arbitrary, constant advisory-lock key for this application
APP_ROLE = "sales_app_user"


class MigrationError(RuntimeError):
    pass


def discover(directory: Path = MIGRATIONS_DIR) -> List[Tuple[str, Path, str]]:
    found = []
    for path in sorted(directory.iterdir()):
        m = FILE_PATTERN.match(path.name)
        if m:
            found.append((m.group(1), path, hashlib.sha256(path.read_bytes()).hexdigest()))
    versions = [v for v, _, _ in found]
    if len(set(versions)) != len(versions):
        raise MigrationError("duplicate migration version numbers")
    return found


def _ensure_tracking(conn: psycopg.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    VARCHAR(16) PRIMARY KEY,
            filename   TEXT        NOT NULL,
            checksum   CHAR(64)    NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    if _role_exists(conn):  # the application never needs (or gets) the migration ledger
        conn.execute(sql.SQL("REVOKE ALL ON schema_migrations FROM {}").format(sql.Identifier(APP_ROLE)))


def _role_exists(conn: psycopg.Connection) -> bool:
    return conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,)).fetchone() is not None


def ensure_app_role(conn: psycopg.Connection, password: Optional[str]) -> str:
    """Create the RLS-bound application role, or rotate its password. Never superuser/BYPASSRLS."""
    exists = _role_exists(conn)
    if password:
        stmt = "ALTER ROLE {} WITH LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD {}" if exists \
            else "CREATE ROLE {} WITH LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD {}"
        conn.execute(sql.SQL(stmt).format(sql.Identifier(APP_ROLE), sql.Literal(password)))
        return "rotated" if exists else "created"
    if not exists:
        raise MigrationError(f"role {APP_ROLE} does not exist: set APP_DB_PASSWORD to create it")
    return "unchanged"


def applied(conn: psycopg.Connection) -> dict:
    return {v: (f, c) for v, f, c in conn.execute("SELECT version, filename, checksum FROM schema_migrations")}


def migrate(url: str, app_password: Optional[str] = None, baseline: Optional[str] = None,
            directory: Path = MIGRATIONS_DIR, log=print) -> List[str]:
    files = discover(directory)
    ran: List[str] = []
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
        try:
            log(f"application role {APP_ROLE}: {ensure_app_role(conn, app_password)}")
            _ensure_tracking(conn)
            done = applied(conn)
            for version, path, checksum in files:
                if version in done:
                    if done[version][1] != checksum:
                        raise MigrationError(f"{path.name} changed after it was applied (checksum mismatch)")
                    continue
                if baseline and version <= baseline:
                    conn.execute("INSERT INTO schema_migrations(version, filename, checksum) VALUES (%s,%s,%s)",
                                 (version, path.name, checksum))
                    log(f"baselined {path.name}")
                    continue
                body = path.read_text(encoding="utf-8")
                # Files that manage their own BEGIN/COMMIT run as-is; others are wrapped.
                self_managed = re.search(r"^\s*BEGIN\s*;", body, flags=re.I | re.M) is not None
                try:
                    if self_managed:
                        conn.execute(body)
                    else:
                        with conn.transaction():
                            conn.execute(body)
                    conn.execute("INSERT INTO schema_migrations(version, filename, checksum) VALUES (%s,%s,%s)",
                                 (version, path.name, checksum))
                except Exception as exc:
                    if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
                        conn.execute("ROLLBACK")
                    raise MigrationError(f"{path.name} failed: {type(exc).__name__}: {exc}") from exc
                ran.append(path.name)
                log(f"applied {path.name}")
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
    log(f"migrations complete: {len(ran)} applied, {len(files) - len(ran)} already present")
    return ran


def status(url: str, directory: Path = MIGRATIONS_DIR) -> List[str]:
    with psycopg.connect(url, autocommit=True) as conn:
        tracked = conn.execute("SELECT to_regclass('schema_migrations')").fetchone()[0] is not None
        done = applied(conn) if tracked else {}
    return [f"{'applied' if v in done else 'PENDING'} {p.name}" for v, p, _ in discover(directory)]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Apply versioned SQL migrations")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--baseline", metavar="NNN", help="mark migrations up to NNN as applied without running them")
    args = parser.parse_args(argv)
    url = os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        print("MIGRATION_DATABASE_URL is required (owner connection, not the application role)", file=sys.stderr)
        return 2
    url = url.replace("postgresql+psycopg://", "postgresql://")
    try:
        if args.status:
            print("\n".join(status(url)))
        else:
            migrate(url, os.environ.get("APP_DB_PASSWORD") or None, args.baseline)
    except MigrationError as exc:
        print(f"MIGRATION FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
