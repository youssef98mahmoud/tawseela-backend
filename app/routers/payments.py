from fastapi import APIRouter, Depends, HTTPException, Request
from app.core.config import Config
from app.core.dependencies import get_current_user
from app.services import subscription_service as billing

router = APIRouter()


@router.post('/subscription-intent')
async def subscription_intent(user=Depends(get_current_user)):
    return await billing.checkout(user.id)


@router.get('/subscription')
async def subscription_status(user=Depends(get_current_user)):
    return await billing.status(user.id)


@router.post('/subscription/cancel')
async def cancel_subscription(user=Depends(get_current_user)):
    return await billing.cancel(user.id)


@router.post('/webhook')
async def stripe_webhook(request: Request):
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > 262144:
            raise HTTPException(413, 'Webhook too large')
    return await billing.webhook(billing.verify_event(bytes(payload), request.headers.get('stripe-signature', '')))


async def require_subscription(user=Depends(get_current_user)):
    if Config.REQUIRE_SUBSCRIPTION and not (await billing.status(user.id))['active']:
        raise HTTPException(402, 'An active subscription is required to offer or book a new ride')
