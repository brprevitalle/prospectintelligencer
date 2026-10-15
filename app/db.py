import os
from pathlib import Path
import psycopg
from psycopg.rows import dict_row


def connect():
    return psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row)


def migrate():
    with connect() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(141000)')
        conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY)')
        for path in sorted((Path(__file__).resolve().parent.parent / 'migrations').glob('*.sql')):
            if not conn.execute('SELECT 1 FROM schema_migrations WHERE name=%s', (path.name,)).fetchone():
                conn.execute(path.read_text())
                conn.execute('INSERT INTO schema_migrations VALUES (%s)', (path.name,))
