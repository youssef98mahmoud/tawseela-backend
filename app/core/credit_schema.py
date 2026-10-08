"""Explicit additive migration for the original TuShare SQLAlchemy schema only.

The older deployed credit prototype uses different table shapes. Refuse that
schema instead of pretending this migration can merge account identities.
"""
from sqlalchemy import inspect

ADDITIONS = {
    'users': {'credit_balance': 'INTEGER NOT NULL DEFAULT 0 CHECK (credit_balance >= 0)',
              'escrow_balance': 'INTEGER NOT NULL DEFAULT 0 CHECK (escrow_balance >= 0)'},
    'rides': {'status': "TEXT NOT NULL DEFAULT 'open'"},
    'bookings': {'credit_status': "TEXT NOT NULL DEFAULT 'legacy'",
                 'credits_escrowed': 'INTEGER NOT NULL DEFAULT 0 CHECK (credits_escrowed >= 0)'},
}

def check_original_schema(conn):
    inspector = inspect(conn)
    tables = inspector.get_table_names()
    required = {'users': {'password','is_verified','is_active'},
                'rides': {'is_available','price_per_seat'},
                'bookings': {'id','seats_booked','total_price'}}
    for table, columns in required.items():
        if table in tables:
            actual = {c['name'] for c in inspector.get_columns(table)}
            if not columns <= actual:
                raise RuntimeError('Incompatible database: migrate prototype data separately on a backed-up staging copy')

def check_credit_schema(conn):
    check_original_schema(conn)
    inspector = inspect(conn)
    for table, columns in ADDITIONS.items():
        if table in inspector.get_table_names():
            actual = {c['name'] for c in inspector.get_columns(table)}
            if not set(columns) <= actual:
                raise RuntimeError('Credit schema upgrade required: back up database then run python -m scripts.migrate_credits')

def migrate_credit_schema(conn):
    if conn.dialect.name != 'sqlite':
        raise RuntimeError('This migration supports SQLite only')
    check_original_schema(conn)
    inspector = inspect(conn)
    tables = inspector.get_table_names()
    for table, columns in ADDITIONS.items():
        if table not in tables:
            continue
        actual = {c['name'] for c in inspector.get_columns(table)}
        for name, ddl in columns.items():
            if name not in actual:
                conn.exec_driver_sql(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}')
