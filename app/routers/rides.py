from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.dependencies import get_db, get_current_user, RoleChecker
from ..models import User
from ..schemas.rides_schema import RideCreate, RideResponse
from ..services.rides_service import RideService
from ..services.credit_service import book_with_credits, complete_with_credits


router = APIRouter()
drivers_only = Depends(RoleChecker(allowed_roles=["driver"]))
verified_members = Depends(RoleChecker(allowed_roles=["passenger", "driver"]))
service = RideService()


@router.get("/rides", dependencies=[verified_members], response_model=list[RideResponse])
async def get_available_rides(
    destination: str = Query(None),
    women_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """ Get all available rides that are not booked. """

    return await service.get_rides(destination, db, women_only)


@router.get("/rides/booked", dependencies=[verified_members], response_model=list[RideResponse])
async def get_user_booked_rides(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """ Get all rides booked by the current user along with the passengers. """

    return await service.get_rides_booked_by_current_user(current_user, db)


@router.post("/{ride_id}/book", status_code=status.HTTP_201_CREATED)
async def book_ride(
    ride_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """ Book an available ride. """

    return await book_with_credits(ride_id, current_user.id)


@router.post("/rides/new-ride", dependencies=[drivers_only], status_code=status.HTTP_201_CREATED, response_model=RideResponse)
async def share_your_ride(
    ride_data: RideCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """ Router to allow users to share their a new ride. """

    return await service.share_current_users_ride(ride_data, current_user, db)


@router.post("/rides/{ride_id}/complete")
async def complete_ride(ride_id: str, current_user: User = Depends(get_current_user)):
    return await complete_with_credits(ride_id, current_user.id)
