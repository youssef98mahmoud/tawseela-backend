import asyncio
from fastapi import HTTPException
import pytest
from sqlalchemy import select, delete
from app.core.database import AsyncSessionLocal
from app.models import User, Ride, Booking, PlatformLedger, CreditTransfer
from app.services.credit_service import book_with_credits, complete_with_credits
from conftest import headers

async def configure(seats=3, price=17):
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Booking))
        for name in ['passenger','stranger']:
            (await db.get(User,name)).credit_balance = 100
        ride=await db.get(Ride,'ride')
        ride.available_seats=seats
        ride.price_per_seat=price
        (await db.get(User,'driver')).gender='female'
        await db.commit()

async def balances():
    async with AsyncSessionLocal() as db:
        users=(await db.scalars(select(User))).all()
        ledger=await db.get(PlatformLedger,1)
        ride=await db.get(Ride,'ride')
        transfers=(await db.scalars(select(CreditTransfer))).all()
        return {u.id:(u.credit_balance,u.escrow_balance) for u in users}, ledger.commission_balance if ledger else 0, ride.available_seats, len(transfers)

@pytest.fixture
def funded(client):
    asyncio.run(configure())
    return client

def test_booking_completion_conserves_credits_and_cannot_repeat(funded):
    for name in ['passenger','stranger']:
        r=funded.post('/api/v1/ride/book',headers=headers(name),json={})
        assert r.status_code==201, r.text
        assert r.json()['credits_escrowed']==17
    assert funded.post('/api/v1/ride/book',headers=headers('passenger')).status_code==409
    assert funded.post('/api/v1/rides/ride/complete',headers=headers('passenger')).status_code==403
    r=funded.post('/api/v1/rides/ride/complete',headers=headers('driver'))
    assert r.status_code==200, r.text
    assert r.json()['gross_credits']==34
    assert r.json()['platform_commission']==3
    assert r.json()['driver_credits']==31
    before=asyncio.run(balances())
    assert before[0]['passenger']==(83,0)
    assert before[0]['driver']==(31,0)
    assert sum(a+e for a,e in before[0].values())+before[1]==200
    assert before[3]==4
    assert funded.post('/api/v1/rides/ride/complete',headers=headers('driver')).status_code==409
    assert asyncio.run(balances())==before
    assert funded.get('/api/v1/rides?destination=Giza',headers=headers('passenger')).json()==[]

def test_rejections_leave_balances_and_seats_unchanged(funded):
    before=asyncio.run(balances())
    assert funded.post('/api/v1/ride/book',headers=headers('driver')).status_code==400
    assert funded.post('/api/v1/missing/book',headers=headers('passenger')).status_code==404
    assert funded.post('/api/v1/ride/book',headers={'Authorization':'Bearer passenger'}).status_code==401
    async def disable():
        async with AsyncSessionLocal() as db:
            (await db.get(User,'passenger')).is_verified=False
            (await db.get(User,'stranger')).credit_balance=0
            await db.commit()
    asyncio.run(disable())
    snapshot=asyncio.run(balances())
    assert funded.post('/api/v1/ride/book',headers=headers('passenger')).status_code==403
    assert funded.post('/api/v1/ride/book',headers=headers('stranger')).status_code==402
    assert asyncio.run(balances())==snapshot
    assert snapshot[2:]==before[2:]

def test_only_one_concurrent_booking_gets_last_seat(funded):
    asyncio.run(configure(seats=1))
    async def race():
        return await asyncio.gather(book_with_credits('ride','passenger'),book_with_credits('ride','stranger'),return_exceptions=True)
    results=asyncio.run(race())
    assert sum(isinstance(r,dict) for r in results)==1
    assert [r.status_code for r in results if isinstance(r,HTTPException)]==[409]
    b=asyncio.run(balances())
    assert b[2]==0 and b[3]==1
    assert sorted([b[0]['passenger'],b[0]['stranger']])==[(83,17),(100,0)]

def test_concurrent_duplicate_booking_and_completion(funded):
    async def book_race():
        return await asyncio.gather(book_with_credits('ride','passenger'),book_with_credits('ride','passenger'),return_exceptions=True)
    results=asyncio.run(book_race())
    assert sum(isinstance(r,dict) for r in results)==1
    assert asyncio.run(balances())[3]==1
    async def settle_race():
        return await asyncio.gather(complete_with_credits('ride','driver'),complete_with_credits('ride','driver'),return_exceptions=True)
    results=asyncio.run(settle_race())
    assert sum(isinstance(r,dict) for r in results)==1
    b=asyncio.run(balances())
    assert b[0]['driver']==(16,0) and b[1]==1 and b[3]==2

def test_settlement_failure_rolls_back_every_passenger(funded):
    for name in ['passenger','stranger']:
        assert funded.post('/api/v1/ride/book',headers=headers(name)).status_code==201
    async def corrupt():
        async with AsyncSessionLocal() as db:
            (await db.get(User,'stranger')).escrow_balance=0
            await db.commit()
    asyncio.run(corrupt())
    before=asyncio.run(balances())
    assert funded.post('/api/v1/rides/ride/complete',headers=headers('driver')).status_code==409
    assert asyncio.run(balances())==before

def test_search_and_driver_booked_rides(funded):
    r=funded.get('/api/v1/rides?destination=Giza&women_only=true',headers=headers('passenger'))
    assert r.status_code==200, r.text
    assert r.json()[0]['driver_gender']=='female'
    assert r.json()[0]['passengers']==[]
    assert isinstance(r.json()[0]['price_per_seat'],int)
    assert funded.get('/api/v1/rides/booked',headers=headers('driver')).json()[0]['id']=='ride'
    async def male():
        async with AsyncSessionLocal() as db:
            (await db.get(User,'driver')).gender='male'
            await db.commit()
    asyncio.run(male())
    assert funded.get('/api/v1/rides?women_only=true',headers=headers('passenger')).json()==[]

def test_legacy_booking_cannot_create_credits(client):
    before=asyncio.run(balances())
    r=client.post('/api/v1/rides/ride/complete',headers=headers('driver'))
    assert r.status_code==409, r.text
    assert asyncio.run(balances())==before

def test_fractional_ride_price_rejected(funded):
    data={'vehicle_type':'car','vehicle_model':'test','vehicle_plate':'TEST2','available_seats':2,
          'departure_location':'Cairo','destination':'Giza','departure_time':'2030-01-01T12:00:00','price_per_seat':1.5}
    assert funded.post('/api/v1/rides/new-ride',headers=headers('driver'),json=data).status_code==422
    data['price_per_seat']=20
    r=funded.post('/api/v1/rides/new-ride',headers=headers('driver'),json=data)
    assert r.status_code==201, r.text
    assert r.json()['price_per_seat']==20

def test_revoked_and_forged_tokens_cannot_move_credits(funded,monkeypatch):
    from unittest.mock import AsyncMock
    before=asyncio.run(balances())
    valid=headers('passenger')['Authorization']
    token=valid.rsplit('.',1)[0]+'.invalid-signature'
    assert funded.post('/api/v1/ride/book',headers={'Authorization':token}).status_code==401
    monkeypatch.setattr('app.core.token_bearer.token_in_blacklist',AsyncMock(return_value=True))
    assert funded.post('/api/v1/ride/book',headers=headers('passenger')).status_code==401
    assert asyncio.run(balances())==before

def test_signed_login_to_booking_and_completion(client):
    from app.routers.auth import mail
    from app.utils.auth import hash_password
    registration=client.post('/api/v1/auth/signup',data={'first_name':'Real','last_name':'Flow',
        'username':'flow','email':'flow@example.com','mobile_number':'+201000000009',
        'gender':'female','password':'flow-test-password'})
    assert registration.status_code==201
    assert client.get(mail.send_message.call_args.args[0].template_body['verification_link']).status_code==200
    async def prepare():
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Booking))
            account=await db.scalar(select(User).where(User.username=='flow'))
            account.credit_balance=40  # Isolated test funding, never a production API.
            (await db.get(User,'driver')).password=hash_password('driver-test-password')
            await db.commit()
    asyncio.run(prepare())
    def login(username,password):
        result=client.post('/api/v1/auth/login',json={'username':username,'password':password})
        assert result.status_code==200
        return {'Authorization':'Bearer '+result.json()['access_token']}
    passenger=login('flow','flow-test-password')
    driver=login('driver','driver-test-password')
    assert client.post('/api/v1/ride/book',headers=passenger,json={'user_id':'stranger','price':0}).json()['credits_escrowed']==10
    assert client.post('/api/v1/rides/ride/complete',headers=driver).json()['driver_credits']==9
    profile=client.get('/api/v1/users/profile',headers=passenger)
    assert profile.json()['credit_balance']==30
    assert profile.json()['escrow_balance']==0
