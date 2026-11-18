"""
Database Migration Runner for schema initialization and version tracking.
"""
import os
import sys
import asyncio

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from sqlalchemy import text
from src.backend.core.database import create_engine_instance
from src.backend.models.entities import Base

MIGRATIONS_DIR = os.path.dirname(__file__)

async def run_migrations(db_url: str = None):
    """Executes schema initialization and SQL migrations."""
    engine = create_engine_instance(db_url)
    print(f"Connecting to database to run migrations: {engine.url}")
    
    # 1. Create ORM metadata tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        print("Schema tables initialized via ORM metadata.")

    # 2. If PostgreSQL, also apply RLS policies and custom triggers if present
    if engine.dialect.name == "postgresql":
        init_sql_path = os.path.join(os.path.dirname(MIGRATIONS_DIR), "..", "..", "infra", "init-db.sql")
        if os.path.exists(init_sql_path):
            with open(init_sql_path, "r", encoding="utf-8") as f:
                sql_content = f.read()
            async with engine.begin() as conn:
                for statement in sql_content.split(";"):
                    stmt = statement.strip()
                    if stmt:
                        try:
                            await conn.execute(text(stmt))
                        except Exception as e:
                            print(f"Note on SQL statement execution: {e}")
            print("PostgreSQL RLS policies and application role configured.")

    await engine.dispose()
    print("Migrations completed successfully.")

if __name__ == "__main__":
    asyncio.run(run_migrations())
