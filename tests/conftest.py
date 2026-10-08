import os
import tempfile
from pathlib import Path

# Never use the upstream database or real email/Redis in tests.
_test_dir = tempfile.TemporaryDirectory()
settings = {
    'DATABASE_URL': 'sqlite+aiosqlite:///' + str(Path(_test_dir.name) / 'test.sqlite3'),
    'SECRET_KEY': 'test-only-email-key', 'JWT_SECRET': 'test-only-jwt-key',
    'JWT_ALGORITHM': 'HS256', 'JTI_EXPIRY': '86400', 'ACCESS_TOKEN_EXPIRY': '3600',
    'REFRESH_TOKEN_EXPIRY': '1', 'REDIS_HOST': '127.0.0.1', 'REDIS_PORT': '6379',
    'DOMAIN': 'http://testserver', 'MAIL_USERNAME': '', 'MAIL_PASSWORD': '',
    'MAIL_FROM': 'test@example.com', 'MAIL_PORT': '1025', 'MAIL_SERVER': 'localhost',
    'MAIL_FROM_NAME': 'Tawseela Test', 'MAIL_STARTTLS': 'false', 'MAIL_SSL_TLS': 'false',
    'USE_CREDENTIALS': 'false', 'VALIDATE_CERTS': 'true',
}
os.environ.update(settings)

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from app import app
from app.core.database import Base, engine, AsyncSessionLocal
from app.models import User, Ride, Booking
from app.routers.auth import mail
from app.utils.auth import create_access_token, create_url_safe_token

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mail, 'send_message', AsyncMock())
    monkeypatch.setattr('app.core.token_bearer.token_in_blacklist', AsyncMock(return_value=False))
    async def reset():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSessionLocal() as db:
            for name in ['driver', 'passenger', 'stranger']:
                db.add(User(id=name, first_name=name, last_name='Test', gender='male',
                            username=name, email=name+'@example.com', password='unused',
                            mobile_number={'driver':'201000000001','passenger':'201000000002','stranger':'201000000003'}[name],
                            is_verified=True, role='driver' if name=='driver' else 'passenger'))
            await db.flush()
            db.add(Ride(id='ride', driver_id='driver', vehicle_type='car', vehicle_plate='TEST',
                        available_seats=3, departure_location='Cairo', destination='Giza',
                        departure_time=datetime(2030,1,1), price_per_seat=10))
            await db.flush()
            db.add(Booking(ride_id='ride', passenger_id='passenger', seats_booked=1, total_price=10, status='confirmed'))
            await db.commit()
    asyncio.run(reset())
    with TestClient(app) as test_client:
        yield test_client

def headers(name):
    return {'Authorization': 'Bearer '+create_access_token({'email':name+'@example.com', 'user_id':name, 'role':'passenger'})}
