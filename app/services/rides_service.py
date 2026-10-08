from fastapi import HTTPException
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from app.models import Booking, Ride

class RideService:
    @staticmethod
    def query():
        return select(Ride).options(selectinload(Ride.driver), selectinload(Ride.bookings).selectinload(Booking.passenger))

    @staticmethod
    def response(ride):
        return {**{c.name:getattr(ride,c.name) for c in ride.__table__.columns},
                'price_per_seat': ride.price_per_seat,
                'driver_name': f'{ride.driver.first_name} {ride.driver.last_name}',
                'driver_gender': ride.driver.gender,
                'driver_profile_image': ride.driver.profile_image or 'media/dps/default.png',
                'passengers': [{'name':f'{b.passenger.first_name} {b.passenger.last_name}',
                    'profile_image': b.passenger.profile_image or 'media/dps/default.png',
                    'departure_location':ride.departure_location}
                    for b in ride.bookings if b.status != 'canceled']}

    async def get_rides(self, destination, db, women_only=False):
        from app.models import User
        stmt = self.query().where(Ride.status == 'open', Ride.is_available.is_(True), Ride.available_seats > 0)
        if destination:
            stmt = stmt.where(Ride.destination.ilike('%' + destination + '%'))
        if women_only:
            from sqlalchemy import func
            stmt = stmt.where(Ride.driver.has(func.lower(User.gender) == 'female'))
        rides = (await db.scalars(stmt.order_by(Ride.departure_time))).all()
        return [self.response(r) for r in rides]

    async def get_rides_booked_by_current_user(self, user, db):
        stmt = self.query().where(or_(Ride.driver_id == user.id, Ride.id.in_(
            select(Booking.ride_id).where(Booking.passenger_id == user.id, Booking.status != 'canceled'))))
        return [self.response(r) for r in (await db.scalars(stmt.order_by(Ride.departure_time))).all()]

    async def share_current_users_ride(self, ride_data, user, db):
        if ride_data.available_seats < 1:
            raise HTTPException(422, 'A new ride must have at least one seat')
        new_ride = Ride(**ride_data.model_dump(), driver_id=user.id)
        db.add(new_ride)
        try:
            await db.flush()
            ride_id = new_ride.id
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(409, 'Ride conflicts with an existing vehicle record')
        ride = await db.scalar(self.query().where(Ride.id == ride_id))
        return self.response(ride)
