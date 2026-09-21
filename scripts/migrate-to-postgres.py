#!/usr/bin/env python3
"""
Migration script: SQLite → PostgreSQL
Exports jobs from SQLite catalog.sqlite and imports to PostgreSQL
"""

import sqlite3
import psycopg2
import os
import sys
from pathlib import Path

SQLITE_DB = os.getenv("CATALOG_DB", Path(__file__).parent.parent / "state" / "catalog.sqlite")

PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", 5432))
PG_DB = os.getenv("PG_DB", "job_catalog")
PG_USER = os.getenv("PG_USER", "job_admin")
PG_PASSWORD = os.getenv("PG_PASSWORD", "job_admin_password")

def migrate():
    print("Starting SQLite → PostgreSQL migration...\n")
    
    # Connect to SQLite
    print(f"Reading from SQLite: {SQLITE_DB}")
    sqlite_conn = sqlite3.connect(str(SQLITE_DB))
    sqlite_cursor = sqlite_conn.cursor()
    
    # Get total count
    sqlite_cursor.execute("SELECT COUNT(*) FROM catalog_jobs")
    total_jobs = sqlite_cursor.fetchone()[0]
    print(f"Total jobs to migrate: {total_jobs:,}\n")
    
    # Connect to PostgreSQL
    print(f"Connecting to PostgreSQL: {PG_HOST}:{PG_PORT}/{PG_DB}")
    pg_conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DB,
        user=PG_USER,
        password=PG_PASSWORD
    )
    pg_cursor = pg_conn.cursor()
    print("✓ Connected to PostgreSQL\n")
    
    # Prepare insert statement
    insert_sql = """
    INSERT INTO catalog_jobs (
        provider, source_key, job_id, title, location, employment_type,
        compensation, salary_min, salary_max, salary_currency, salary_period, salary_location,
        salary_is_estimated, department, job_url, updated_at, posted_at, first_seen_at, last_seen_at
    ) VALUES (
        %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s
    )
    ON CONFLICT (provider, source_key, job_id) DO NOTHING
    """
    
    # Migrate in batches
    batch_size = 5000
    migrated = 0
    import time
    start_time = time.time()
    
    sqlite_cursor.execute("""
    SELECT provider, source_key, job_id, title, location, employment_type,
           compensation, salary_min, salary_max, salary_currency, salary_period, salary_location,
           salary_is_estimated, department, job_url, updated_at, posted_at, first_seen_at, last_seen_at
    FROM catalog_jobs
    """)
    
    batch = []
    while True:
        rows = sqlite_cursor.fetchmany(batch_size)
        if not rows:
            break
        
        for row in rows:
            batch.append(row)
        
        # Insert batch
        for row in batch:
            try:
                pg_cursor.execute(insert_sql, row)
            except Exception as e:
                print(f"Error inserting row: {e}")
                continue
        
        migrated += len(batch)
        pct = (migrated / total_jobs) * 100
        elapsed = time.time() - start_time
        print(f"  {migrated:,}/{total_jobs:,} ({pct:.1f}%) - {elapsed:.1f}s")
        
        pg_conn.commit()
        batch = []
    
    sqlite_conn.close()
    pg_conn.close()
    
    total_time = time.time() - start_time
    print(f"\n✓ Migration complete: {migrated:,} jobs in {total_time:.1f}s")

if __name__ == "__main__":
    try:
        migrate()
        sys.exit(0)
    except Exception as error:
        print(f"✗ Migration failed: {error}")
        sys.exit(1)
