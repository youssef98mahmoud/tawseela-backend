"""Recurring membership, independent of the ride-credit ledger.

Stripe requests use an explicit version. SQLite serializes per-request state
refreshes, including webhook refreshes, so stale event payloads never set access.
Network requests are bounded; this initial single-instance implementation is not
intended for high-throughput billing. No payment details or secrets are logged.
"""
import hashlib
import hmac
import json
import time
from uuid import uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import Config
from app.models import Membership, BillingEvent
from app.services.credit_service import credit_transaction, verified_user

API_VERSION = '2024-06-20'


def configured():
    if not Config.BILLING_ENABLED or not Config.STRIPE_MONTHLY_PRICE_ID or not Config.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(503, 'Subscriptions are not configured yet')
    key = Config.STRIPE_SECRET_KEY
    if not key.startswith('sk_test_') and not (Config.BILLING_ALLOW_LIVE and key.startswith('sk_live_')):
        raise HTTPException(503, 'Subscription payment credentials are not configured')


def live_mode():
    return Config.STRIPE_SECRET_KEY.startswith('sk_live_')


async def stripe_request(method, path, data=None, key=None):
    headers = {'Stripe-Version': API_VERSION}
    if key:
        headers['Idempotency-Key'] = key
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.request(method, 'https://api.stripe.com/v1/' + path,
                auth=(Config.STRIPE_SECRET_KEY, ''), headers=headers, data=data)
        if response.status_code >= 400:
            raise HTTPException(502, 'Payment provider unavailable; check membership status before retrying')
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, 'Payment provider unavailable; check membership status before retrying') from exc


def membership_response(row):
    return {'status': row.status if row else 'none',
            'active': bool(row and row.status == 'active' and row.paid_until > int(time.time())),
            'paid_until': row.paid_until if row else 0,
            'cancel_at_period_end': bool(row and row.cancel_at_period_end),
            'amount': 15000, 'currency': 'egp', 'interval': 'month'}


async def refresh(row):
    sub = await stripe_request('GET', 'subscriptions/' + row.subscription_id + '?expand[]=latest_invoice.payment_intent.latest_charge')
    items = sub.get('items', {}).get('data', [])
    if (sub.get('customer') != row.customer_id or sub.get('metadata', {}).get('user_id') != row.user_id
            or sub.get('livemode') != live_mode() or len(items) != 1
            or items[0].get('price', {}).get('id') != row.price_id or items[0].get('quantity') != 1):
        raise HTTPException(502, 'Subscription ownership or plan mismatch')
    row.status = sub['status']
    row.cancel_at_period_end = bool(sub.get('cancel_at_period_end'))
    invoice = sub.get('latest_invoice') or {}
    # A client callback, unconfirmed invoice, trial or stale event cannot grant access.
    row.paid_until = 0
    intent = invoice.get('payment_intent') if isinstance(invoice, dict) else None
    charge = intent.get('latest_charge') if isinstance(intent, dict) else None
    payment_reversed = isinstance(charge, dict) and (charge.get('refunded') or charge.get('disputed'))
    if (not payment_reversed and row.status == 'active' and isinstance(invoice, dict) and invoice.get('paid') is True
            and invoice.get('currency') == 'egp' and invoice.get('amount_paid', 0) >= 15000
            and not sub.get('pause_collection')):
        row.paid_until = int(sub.get('current_period_end') or 0)
    return sub


async def status(user_id):
    configured()
    async with credit_transaction() as db:
        await verified_user(db, user_id)
        row = await db.get(Membership, user_id)
        if row and row.subscription_id:
            await refresh(row)
        return membership_response(row)


async def checkout(user_id):
    configured()
    # Persist the idempotency key BEFORE making external requests. An ambiguous
    # network failure must reuse it, including after this process restarts.
    async with credit_transaction() as db:
        await verified_user(db, user_id)
        row = await db.get(Membership, user_id)
        if not row:
            row = Membership(user_id=user_id, checkout_key=uuid4().hex,
                checkout_started=int(time.time()), price_id=Config.STRIPE_MONTHLY_PRICE_ID)
            db.add(row)
        elif row.subscription_id:
            await refresh(row)
            if row.status in ('canceled', 'incomplete_expired'):
                row.subscription_id = None
                row.checkout_key = uuid4().hex
                row.checkout_started = int(time.time())
                row.price_id = Config.STRIPE_MONTHLY_PRICE_ID
                row.status = 'none'
    async with credit_transaction() as db:
        user = await verified_user(db, user_id)
        row = await db.get(Membership, user_id)
        if row.subscription_id:
            sub = await refresh(row)
        else:
            if int(time.time()) - row.checkout_started >= 23 * 3600:
                raise HTTPException(409, 'Checkout requires payment-provider reconciliation before retrying')
            price = await stripe_request('GET', 'prices/' + row.price_id)
            recurring = price.get('recurring') or {}
            if (price.get('active') is not True or price.get('livemode') != live_mode()
                    or price.get('unit_amount') != 15000 or price.get('currency') != 'egp'
                    or recurring.get('interval') != 'month' or recurring.get('interval_count') != 1
                    or recurring.get('usage_type') != 'licensed'):
                raise HTTPException(503, 'Configure the EGP 150 monthly recurring price')
            if not row.customer_id:
                customer = await stripe_request('POST', 'customers',
                    {'metadata[user_id]': user.id}, key='customer-' + row.checkout_key)
                row.customer_id = customer['id']
            sub = await stripe_request('POST', 'subscriptions', {
                'customer': row.customer_id, 'items[0][price]': row.price_id,
                'items[0][quantity]': '1', 'payment_behavior': 'default_incomplete',
                'payment_settings[save_default_payment_method]': 'on_subscription',
                'payment_settings[payment_method_types][0]': 'card',
                'metadata[user_id]': user.id, 'expand[0]': 'latest_invoice.payment_intent',
            }, key='subscription-' + row.checkout_key)
            row.subscription_id = sub['id']
            sub = await refresh(row)
        result = membership_response(row)
        if result['active']:
            return {**result, 'client_secret': None}
        if row.status != 'incomplete':
            raise HTTPException(409, 'An existing subscription needs attention; check its status or cancel renewal')
        intent = (sub.get('latest_invoice') or {}).get('payment_intent') or {}
        secret = intent.get('client_secret') if isinstance(intent, dict) else None
        if not secret:
            raise HTTPException(502, 'Subscription confirmation is temporarily unavailable')
        return {**result, 'client_secret': secret}


async def cancel(user_id):
    configured()
    async with credit_transaction() as db:
        await verified_user(db, user_id)
        row = await db.get(Membership, user_id)
        if not row or not row.subscription_id:
            raise HTTPException(404, 'No subscription to cancel')
        sub = await refresh(row)
        if row.status not in ('canceled', 'incomplete_expired'):
            # End incomplete subscriptions immediately; paid memberships retain
            # paid access until the period ends. Repeated calls are harmless.
            if row.status == 'incomplete':
                await stripe_request('DELETE', 'subscriptions/' + row.subscription_id)
            else:
                await stripe_request('POST', 'subscriptions/' + row.subscription_id,
                    {'cancel_at_period_end': 'true'}, key='cancel-' + row.subscription_id)
            await refresh(row)
        return membership_response(row)


def verify_event(payload, signature):
    configured()
    try:
        parts = [p.split('=', 1) for p in signature.split(',')]
        timestamps = [v for k, v in parts if k == 't']
        if len(timestamps) != 1 or abs(int(time.time()) - int(timestamps[0])) > 300:
            raise ValueError()
        digest = hmac.new(Config.STRIPE_WEBHOOK_SECRET.encode(),
            timestamps[0].encode() + b'.' + payload, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(digest, v) for k, v in parts if k == 'v1'):
            raise ValueError()
        event = json.loads(payload)
        if not isinstance(event.get('id'), str) or event.get('livemode') != live_mode():
            raise ValueError()
        return event
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise HTTPException(400, 'Invalid webhook signature or event') from exc


async def webhook(event):
    event_type = event.get('type', '')
    obj = event.get('data', {}).get('object', {})
    if event_type.startswith('customer.subscription.'):
        subscription_id = obj.get('id')
    elif event_type.startswith('invoice.'):
        subscription_id = obj.get('subscription')
    elif event_type in ('charge.refunded', 'charge.dispute.created', 'charge.dispute.closed'):
        charge = obj
        if event_type.startswith('charge.dispute.'):
            charge_id = obj.get('charge')
            if not isinstance(charge_id, str):
                return {'received': True}
            charge = await stripe_request('GET', 'charges/' + charge_id)
        invoice_id = charge.get('invoice')
        if not isinstance(invoice_id, str):
            return {'received': True}
        invoice = await stripe_request('GET', 'invoices/' + invoice_id)
        subscription_id = invoice.get('subscription')
    else:
        return {'received': True}
    if not isinstance(subscription_id, str):
        return {'received': True}
    async with credit_transaction() as db:
        if await db.get(BillingEvent, event['id']):
            return {'received': True}
        row = await db.scalar(select(Membership).where(Membership.subscription_id == subscription_id))
        if row:
            await refresh(row)  # retrieve current provider state, never apply event snapshots
        db.add(BillingEvent(id=event['id'], processed_at=int(time.time())))
    return {'received': True}
