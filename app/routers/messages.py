"""Ride group chat endpoints. Only the driver and active passengers may access a chat."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_current_user, get_db
from app.models import Booking, Message, Ride, User

router = APIRouter()

class SendMessage(BaseModel):
    ride_id: str
    content: str = Field(min_length=1, max_length=4000)
    sender_id: str | None = None
    receiver_id: str | None = None

def person(user):
    return {"id": user.id, "first_name": user.first_name, "last_name": user.last_name,
            "profile_image": user.profile_image or "media/dps/default.png"}

async def chat_ride(ride_id, user, db):
    ride = await db.get(Ride, ride_id)
    if not ride:
        raise HTTPException(404, "Ride not found")
    booking = await db.scalar(select(Booking.id).where(
        Booking.ride_id == ride_id, Booking.passenger_id == user.id,
        Booking.status.in_(["pending", "confirmed", "completed"])))
    if ride.driver_id != user.id and booking is None:
        raise HTTPException(403, "You are not a member of this ride")
    return ride

@router.post('/message/send', status_code=201)
async def send_message(data: SendMessage, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await chat_ride(data.ride_id, user, db)
    if data.sender_id and data.sender_id != user.id:
        raise HTTPException(403, "Sender must match authenticated user")
    if data.receiver_id is not None:
        raise HTTPException(422, "Only ride group messages are supported")
    if not data.content.strip():
        raise HTTPException(422, "Message cannot be blank")
    message = Message(sender_id=user.id, ride_id=data.ride_id, content=data.content.strip())
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return {"id": message.id, "content": message.content, "timestamp": message.timestamp, "sender": person(user)}

@router.get('/message/{ride_id}/get')
async def get_messages(ride_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ride = await chat_ride(ride_id, user, db)
    messages = (await db.scalars(select(Message).options(selectinload(Message.sender)).where(
        Message.ride_id == ride_id, Message.receiver_id.is_(None)).order_by(Message.timestamp))).all()
    members = (await db.scalars(select(User).where(or_(User.id == ride.driver_id, User.id.in_(
        select(Booking.passenger_id).where(Booking.ride_id == ride_id, Booking.status != 'canceled')))))).all()
    return [{"ride_id": ride.id, "driver_name": ride.driver_name,
             "driver_profile_image": ride.driver_profile_image or "media/dps/default.png",
             "group_members": [person(member) for member in members],
             "messages": [{"id": m.id, "content": m.content, "timestamp": m.timestamp, "sender": person(m.sender)} for m in messages]}]

@router.get('/message/{user_id}/messages')
async def list_chats(user_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user_id != user.id:
        raise HTTPException(403, "Cannot list another user's chats")
    rides = (await db.scalars(select(Ride).where(or_(Ride.driver_id == user.id, Ride.id.in_(
        select(Booking.ride_id).where(Booking.passenger_id == user.id, Booking.status != 'canceled')))))).all()
    result = []
    for ride in rides:
        latest = await db.scalar(select(Message).where(Message.ride_id == ride.id, Message.receiver_id.is_(None)).order_by(Message.timestamp.desc()).limit(1))
        if latest is None:
            continue
        # Existing schema has no per-user read receipts; do not invent an unread count.
        result.append({"ride_id": ride.id, "driver_name": ride.driver_name,
                       "driver_profile_image": ride.driver_profile_image or "media/dps/default.png",
                       "latest_message": latest.content, "latest_timestamp": latest.timestamp,
                       "unread_count": 0})
    return result
