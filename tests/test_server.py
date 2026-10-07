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

def test_boot_and_auth(client):
    assert client.get('/health').json() == {'status':'ok'}
    assert client.get('/api/v1/docs').status_code == 200
    assert client.get('/api/v1/message/ride/get').status_code == 401

def test_chat_membership_and_sender(client):
    assert client.get('/api/v1/message/ride/get',headers=headers('stranger')).status_code == 403
    assert client.post('/api/v1/message/send',headers=headers('passenger'), json={'ride_id':'ride','sender_id':'driver','content':'hello'}).status_code == 403
    assert client.post('/api/v1/message/send',headers=headers('passenger'), json={'ride_id':'ride','content':'hello'}).status_code == 201
    data=client.get('/api/v1/message/ride/get',headers=headers('driver')).json()[0]
    assert data['messages'][0]['sender']['id'] == 'passenger'
    assert {u['id'] for u in data['group_members']} == {'driver','passenger'}
    assert client.get('/api/v1/message/passenger/messages',headers=headers('stranger')).status_code == 403
    assert client.get('/api/v1/message/passenger/messages',headers=headers('passenger')).json()[0]['latest_message'] == 'hello'

def test_verification_and_signup(client):
    result=client.post('/api/v1/auth/signup',data={'first_name':'New','last_name':'User','username':'newuser', 'email':'new@example.com','mobile_number':'+201000000004','gender':'female','password':'test-only-password'})
    assert result.status_code == 201, result.text
    assert 'password' not in result.json()['user']
    message=mail.send_message.call_args.args[0]
    link=message.template_body['verification_link']
    assert '/auth/verify/' in link
    assert client.get(link).status_code == 200
    assert client.get('/api/v1/auth/verify/bad-token').status_code != 500

    login = client.post('/api/v1/auth/login', json={'username':'newuser','password':'test-only-password'})
    assert login.status_code == 200, login.text
    assert login.json()['access_token']
    assert client.post('/api/v1/auth/login', json={'username':'newuser','password':'wrong'}).status_code == 400
