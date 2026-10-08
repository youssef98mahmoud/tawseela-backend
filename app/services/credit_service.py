"""SQLite credit writes are serialized before reading balances or seat counts.

Uses a separate session from authentication, which may already have a read
transaction. BEGIN IMMEDIATE protects against concurrent processes, not only
concurrent requests in a single worker. Any failure rolls the whole write back.
"""
from contextlib import asynccontextmanager
from fastapi import HTTPException
from sqlalchemy import select, text
from app.core.database import AsyncSessionLocal
from app.models import User, Ride, Booking, PlatformLedger, CreditTransfer

@asynccontextmanager
async def credit_transaction():
    async with AsyncSessionLocal() as db:
        if db.bind.dialect.name != 'sqlite':
            raise RuntimeError('Credit transactions currently require SQLite; review locking before changing databases')
        await db.execute(text('BEGIN IMMEDIATE'))
        try:
            yield db
            await db.commit()
        except BaseException:
            await db.rollback()
            raise

async def verified_user(db, user_id):
    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(401, 'Account is unavailable')
    if not user.is_verified:
        raise HTTPException(403, 'Verify your email before booking or completing rides')
    return user

async def book_with_credits(ride_id, user_id):
    async with credit_transaction() as db:
        user = await verified_user(db, user_id)
        ride = await db.get(Ride, ride_id)
        if not ride:
            raise HTTPException(404, 'Ride not found')
        if ride.driver_id == user_id:
            raise HTTPException(400, 'Drivers cannot book their own ride')
        if ride.status != 'open' or not ride.is_available or ride.available_seats < 1:
            raise HTTPException(409, 'Ride is no longer available')
        if await db.scalar(select(Booking.id).where(Booking.ride_id == ride_id, Booking.passenger_id == user_id)):
            raise HTTPException(409, 'Ride already booked')
        raw = ride.price_per_seat
        if raw is None or raw <= 0 or raw > 1000000 or raw != int(raw):
            raise HTTPException(409, 'Ride price must be a positive whole number of credits')
        cost = int(raw)
        if user.credit_balance < cost:
            raise HTTPException(402, 'Insufficient Credits')
        user.credit_balance -= cost
        user.escrow_balance += cost
        ride.available_seats -= 1
        db.add(Booking(ride_id=ride_id, passenger_id=user_id, seats_booked=1,
                       total_price=cost, status='confirmed', credit_status='escrowed', credits_escrowed=cost))
        db.add(CreditTransfer(ride_id=ride_id, passenger_id=user_id, kind='escrow', amount=cost))
        return {'message':'Ride booked with credits', 'credits_escrowed':cost}

async def complete_with_credits(ride_id, user_id):
    async with credit_transaction() as db:
        driver = await verified_user(db, user_id)
        ride = await db.get(Ride, ride_id)
        if not ride:
            raise HTTPException(404, 'Ride not found')
        if ride.driver_id != user_id:
            raise HTTPException(403, 'Only the driver can complete this ride')
        if ride.status != 'open':
            raise HTTPException(409, 'Ride is already complete')
        bookings = (await db.scalars(select(Booking).where(Booking.ride_id == ride_id, Booking.status != 'canceled'))).all()
        gross = 0
        for booking in bookings:
            if booking.credit_status != 'escrowed' or booking.credits_escrowed <= 0:
                raise HTTPException(409, 'Legacy or unsettled booking requires review; no credits moved')
            passenger = await db.get(User, booking.passenger_id)
            amount = booking.credits_escrowed
            if passenger is None or passenger.escrow_balance < amount:
                raise HTTPException(409, 'Escrow ledger is inconsistent')
            passenger.escrow_balance -= amount
            booking.credit_status = 'released'
            booking.status = 'completed'
            db.add(CreditTransfer(ride_id=ride_id, passenger_id=passenger.id, kind='release', amount=amount))
            gross += amount
        commission = gross * 10 // 100
        ledger = await db.get(PlatformLedger, 1)
        if ledger is None:
            ledger = PlatformLedger(id=1, commission_balance=0)
            db.add(ledger)
        driver.credit_balance += gross - commission
        ledger.commission_balance += commission
        ride.status = 'complete'
        ride.is_available = False
        return {'message':'Ride completed and escrow released', 'gross_credits':gross,
                'driver_credits':gross - commission, 'platform_commission':commission}
