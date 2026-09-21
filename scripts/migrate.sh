#!/bin/bash
# Migration script using Python in a container
# This runs a Python migration script that doesn't require local Python

cat > /tmp/migrate.py << 'EOF'
import sqlite3
import os
from pathlib import Path
import sys

SQLITE_DB = "/data/catalog.sqlite"

# Read all data from SQLite
print("Reading from SQLite...")
sqlite_conn = sqlite3.connect(SQLITE_DB)
sqlite_conn.row_factory = sqlite3.Row
cursor = sqlite_conn.cursor()

cursor.execute("SELECT COUNT(*) FROM catalog_jobs")
total = cursor.fetchone()[0]
print(f"Total jobs: {total:,}")

cursor.execute("""
    SELECT provider, source_key, job_id, title, location, employment_type,
           compensation, salary_min, salary_max, salary_currency, salary_period, salary_location,
           salary_is_estimated, department, job_url, updated_at, posted_at, first_seen_at, last_seen_at
    FROM catalog_jobs
""")

rows = cursor.fetchall()
sqlite_conn.close()

print(f"Read {len(rows):,} rows from SQLite")

# Write to a format PostgreSQL can understand
# Using SQL INSERT statements
print("Generating SQL insert statements...")

inserts = []
for i, row in enumerate(rows):
    # Properly escape values for SQL
    values = []
    for v in row:
        if v is None:
            values.append("NULL")
        elif isinstance(v, str):
            values.append("'" + v.replace("'", "''") + "'")
        elif isinstance(v, int):
            values.append(str(v))
        else:
            values.append("'" + str(v).replace("'", "''") + "'")
    
    insert = f"""INSERT INTO catalog_jobs (provider, source_key, job_id, title, location, employment_type, compensation, salary_min, salary_max, salary_currency, salary_period, salary_location, salary_is_estimated, department, job_url, updated_at, posted_at, first_seen_at, last_seen_at) VALUES ({', '.join(values)}) ON CONFLICT (provider, source_key, job_id) DO NOTHING;"""
    inserts.append(insert)
    
    if (i + 1) % 10000 == 0:
        print(f"  {i+1:,} statements generated")

# Write SQL file
print("Writing SQL file...")
with open("/tmp/migrate.sql", "w") as f:
    f.write("\n".join(inserts))

print(f"✓ Generated {len(inserts):,} INSERT statements")
EOF

# Run Python script in Alpine container
docker run --rm -v "$PWD/state:/data:ro" python:3.14-alpine python /dev/stdin < /tmp/migrate.py

# Now execute the SQL file in PostgreSQL
echo "Loading SQL into PostgreSQL..."
docker exec -i job-crawler-postgres psql -U job_admin -d job_catalog < /tmp/migrate.sql

echo "✓ Migration complete"
