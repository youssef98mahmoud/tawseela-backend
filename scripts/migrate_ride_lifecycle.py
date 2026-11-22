"""Run on a backed-up account-backend SQLite database with writes stopped."""
import asyncio

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect


def migrate_ride_lifecycle(conn):
    if conn.dialect.name != 'sqlite':
        raise RuntimeError('This migration supports SQLite only')
    from app.core.credit_schema import check_original_schema
    check_original_schema(conn)
    inspector = inspect(conn)
    if 'rides' not in inspector.get_table_names():
        return
    constraints = [c for c in inspector.get_unique_constraints('rides')
                   if c['column_names'] == ['vehicle_plate']]
    if constraints:
        operations = Operations(MigrationContext.configure(conn))
        with operations.batch_alter_table('rides', recreate='always',
                naming_convention={'uq': 'uq_%(table_name)s_%(column_0_name)s'}) as batch:
            for constraint in constraints:
                batch.drop_constraint(constraint['name'] or 'uq_rides_vehicle_plate', type_='unique')
    if conn.exec_driver_sql('PRAGMA foreign_key_check').fetchall():
        raise RuntimeError('Foreign-key check failed; migration must be rolled back')


async def main():
    from app.core.database import engine, Base
    from app.core.credit_schema import migrate_credit_schema
    from app import models
    async with engine.begin() as conn:
        await conn.run_sync(migrate_credit_schema)
        await conn.run_sync(migrate_ride_lifecycle)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
