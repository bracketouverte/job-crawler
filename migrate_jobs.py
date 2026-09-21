#!/usr/bin/env python3
import sqlite3
from datetime import datetime
import sys
import os
import time

# Retry logic for psycopg2 import (in case network is still initializing)
psycopg2 = None
for attempt in range(10):
    try:
        import psycopg2
        from psycopg2.extras import execute_values
        break
    except ImportError:
        if attempt < 9:
            time.sleep(1)
            continue
        raise

# SQLite connection
sqlite_path = '/app/crawler/state/catalog.sqlite'
print(f'Connecting to SQLite at {sqlite_path}...')
sqlite_conn = sqlite3.connect(sqlite_path)
sqlite_cursor = sqlite_conn.cursor()

# PostgreSQL connection
pg_conn = psycopg2.connect(
    host='job-crawler-postgres',
    user='job_admin',
    password='job_admin_password',
    database='job_catalog'
)
pg_cursor = pg_conn.cursor()

# Clear existing data
pg_cursor.execute('DELETE FROM catalog_jobs')
pg_conn.commit()

# Fetch all jobs from SQLite
sqlite_cursor.execute('''
    SELECT provider, source_key, job_id, title, location, employment_type, 
           compensation, salary_min, salary_max, salary_currency, salary_period, 
           salary_location, salary_is_estimated, department, job_url, updated_at, 
           posted_at, first_seen_at, last_seen_at 
    FROM catalog_jobs
''')

def parse_timestamp(val):
    """Convert timestamp string to valid format, or return None"""
    if not val or val.strip() == '':
        return None
    try:
        return datetime.fromisoformat(val.replace('Z', '+00:00'))
    except:
        return None

# Insert in batches
batch_size = 5000
batch = []
inserted = 0
skipped = 0

while True:
    rows = sqlite_cursor.fetchmany(batch_size)
    if not rows:
        break
    
    for row in rows:
        provider, source_key, job_id, title, location, employment_type, compensation, \
        salary_min, salary_max, salary_currency, salary_period, salary_location, \
        salary_is_estimated, department, job_url, updated_at, posted_at, \
        first_seen_at, last_seen_at = row
        
        # Clean timestamps
        updated_at = parse_timestamp(updated_at)
        posted_at = parse_timestamp(posted_at)
        first_seen_at = parse_timestamp(first_seen_at)
        last_seen_at = parse_timestamp(last_seen_at)
        
        # Validate critical fields
        if not provider or not source_key or not job_id:
            skipped += 1
            continue
        
        batch.append((
            provider, source_key, job_id, title, location, employment_type,
            compensation, salary_min, salary_max, salary_currency, salary_period,
            salary_location, salary_is_estimated or 0, department, job_url,
            updated_at, posted_at, first_seen_at, last_seen_at
        ))
    
    # Insert batch
    if batch:
        execute_values(pg_cursor, '''
            INSERT INTO catalog_jobs 
            (provider, source_key, job_id, title, location, employment_type,
             compensation, salary_min, salary_max, salary_currency, salary_period,
             salary_location, salary_is_estimated, department, job_url,
             updated_at, posted_at, first_seen_at, last_seen_at)
            VALUES %s
        ''', batch)
        pg_conn.commit()
        inserted += len(batch)
        batch = []
        print(f'Inserted {inserted} rows...')

sqlite_conn.close()
pg_conn.close()

print(f'\nMigration complete:')
print(f'  Inserted: {inserted}')
print(f'  Skipped: {skipped}')
