import pytest
from sqlalchemy import create_engine, inspect
from app.core.credit_schema import migrate_credit_schema, check_credit_schema

def test_additive_migration_preserves_accounts_and_is_repeatable(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'legacy.db'))
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE users (id TEXT PRIMARY KEY, password TEXT, is_verified BOOLEAN, is_active BOOLEAN)')
        conn.exec_driver_sql("INSERT INTO users VALUES ('existing','hash',1,1)")
        conn.exec_driver_sql('CREATE TABLE rides (id TEXT PRIMARY KEY, is_available BOOLEAN, price_per_seat FLOAT)')
        conn.exec_driver_sql('CREATE TABLE bookings (id TEXT PRIMARY KEY, seats_booked INTEGER, total_price FLOAT)')
        conn.exec_driver_sql("INSERT INTO bookings VALUES ('booking',1,10)")
        with pytest.raises(RuntimeError, match='upgrade required'):
            check_credit_schema(conn)
        migrate_credit_schema(conn)
        migrate_credit_schema(conn)
        check_credit_schema(conn)
        assert conn.exec_driver_sql('SELECT password,credit_balance,escrow_balance FROM users').one()==('hash',0,0)
        assert conn.exec_driver_sql('SELECT credit_status,credits_escrowed FROM bookings').one()==('legacy',0)
    engine.dispose()

def test_prototype_database_is_rejected_without_mutating_it(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'prototype.db'))
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE users (id TEXT PRIMARY KEY, credit_balance INTEGER)')
        with pytest.raises(RuntimeError, match='Incompatible database'):
            migrate_credit_schema(conn)
        assert [c['name'] for c in inspect(conn).get_columns('users')]==['id','credit_balance']
    engine.dispose()
