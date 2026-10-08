"""Run only on a backed-up original-account database, not the live prototype."""
import asyncio
from app.core.database import engine, Base
from app.core.credit_schema import migrate_credit_schema

async def main():
    async with engine.begin() as conn:
        await conn.run_sync(migrate_credit_schema)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print('Credit schema ready. Legacy bookings have not been charged or settled.')

if __name__ == '__main__':
    asyncio.run(main())
