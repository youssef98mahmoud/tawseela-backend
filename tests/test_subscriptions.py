import asyncio
import copy
import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from conftest import headers
from app.core.config import Config
from app.core.database import AsyncSessionLocal
from app.models import Membership, User
from app.services import subscription_service as billing


@pytest.fixture
def provider(monkeypatch):
    for name, value in {'BILLING_ENABLED': True, 'BILLING_ALLOW_LIVE': False,
        'REQUIRE_SUBSCRIPTION': False, 'STRIPE_SECRET_KEY': 'sk_test_fake',
        'STRIPE_WEBHOOK_SECRET': 'whsec_test', 'STRIPE_MONTHLY_PRICE_ID': 'price_monthly'}.items():
        monkeypatch.setattr(Config, name, value)
    sub = {'id': 'sub_test', 'customer': 'cus_test', 'metadata': {'user_id': 'passenger'},
        'livemode': False, 'status': 'incomplete', 'current_period_end': int(time.time()) + 86400,
        'cancel_at_period_end': False,
        'items': {'data': [{'price': {'id': 'price_monthly'}, 'quantity': 1}]},
        'latest_invoice': {'paid': False, 'currency': 'egp', 'amount_paid': 0,
                           'payment_intent': {'client_secret': 'pi_test_secret_test'}}}
    calls = []
    async def request(method, path, data=None, key=None):
        calls.append((method, path, data, key))
        if path.startswith('prices/'):
            return {'active': True, 'livemode': False, 'unit_amount': 15000, 'currency': 'egp',
                    'recurring': {'interval': 'month', 'interval_count': 1, 'usage_type': 'licensed'}}
        if path == 'customers': return {'id': 'cus_test'}
        if method == 'DELETE': sub['status'] = 'canceled'
        if method == 'POST' and path == 'subscriptions/sub_test': sub['cancel_at_period_end'] = True
        return copy.deepcopy(sub)
    monkeypatch.setattr(billing, 'stripe_request', request)
    return sub, calls


def paid(sub):
    sub['status'] = 'active'
    sub['latest_invoice'].update(paid=True, amount_paid=15000)


def signed_event(event, timestamp=None):
    raw = json.dumps(event).encode()
    timestamp = str(timestamp or int(time.time()))
    sig = hmac.new(b'whsec_test', timestamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
    return raw, {'Stripe-Signature': 't=' + timestamp + ',v1=' + sig, 'Content-Type': 'application/json'}


async def balances():
    async with AsyncSessionLocal() as db:
        return [(u.id, u.credit_balance, u.escrow_balance) for u in (await db.scalars(select(User))).all()]


def test_disabled_billing_and_auth_fail_closed(client, monkeypatch):
    monkeypatch.setattr(Config, 'BILLING_ENABLED', False)
    assert client.post('/api/v1/payments/subscription-intent').status_code == 401
    assert client.post('/api/v1/payments/subscription-intent', headers=headers('passenger')).status_code == 503


def test_checkout_reuses_subscription_and_never_mints_credits(client, provider):
    sub, calls = provider
    before = asyncio.run(balances())
    for _ in range(2):
        response = client.post('/api/v1/payments/subscription-intent', headers=headers('passenger'), json={'amount': 1, 'user_id': 'stranger'})
        assert response.status_code == 200, response.text
        assert response.json()['active'] is False
        assert response.json()['client_secret'] == 'pi_test_secret_test'
    creates = [c for c in calls if c[:2] == ('POST', 'subscriptions')]
    assert len(creates) == 1
    assert creates[0][2]['items[0][price]'] == 'price_monthly'
    paid(sub)
    assert client.get('/api/v1/payments/subscription', headers=headers('passenger')).json()['active'] is True
    assert asyncio.run(balances()) == before
    assert client.get('/api/v1/payments/subscription', headers=headers('stranger')).json()['active'] is False


def test_pending_canceled_and_expired_invoices_do_not_grant_access(client, provider):
    sub, _ = provider
    client.post('/api/v1/payments/subscription-intent', headers=headers('passenger'))
    sub['status'] = 'active'
    assert not client.get('/api/v1/payments/subscription', headers=headers('passenger')).json()['active']
    paid(sub)
    sub['current_period_end'] = int(time.time()) - 1
    assert not client.get('/api/v1/payments/subscription', headers=headers('passenger')).json()['active']
    sub['current_period_end'] = int(time.time()) + 100
    sub['status'] = 'past_due'
    assert not client.get('/api/v1/payments/subscription', headers=headers('passenger')).json()['active']


def test_cancel_paid_period_is_idempotent_and_does_not_touch_credits(client, provider):
    sub, _ = provider
    client.post('/api/v1/payments/subscription-intent', headers=headers('passenger'))
    paid(sub)
    before = asyncio.run(balances())
    for _ in range(2):
        response = client.post('/api/v1/payments/subscription/cancel', headers=headers('passenger'))
        assert response.status_code == 200
        assert response.json()['active'] and response.json()['cancel_at_period_end']
    assert client.post('/api/v1/payments/subscription/cancel', headers=headers('stranger')).status_code == 404
    assert asyncio.run(balances()) == before


def test_signed_webhook_deduplicates_and_refreshes_current_state(client, provider):
    sub, calls = provider
    client.post('/api/v1/payments/subscription-intent', headers=headers('passenger'))
    paid(sub)
    event = {'id': 'evt_1', 'livemode': False, 'type': 'customer.subscription.updated',
        'data': {'object': {'id': 'sub_test', 'status': 'canceled'}}}
    raw, hs = signed_event(event)
    assert client.post('/api/v1/payments/webhook', content=raw, headers=hs).status_code == 200
    count = len(calls)
    assert client.post('/api/v1/payments/webhook', content=raw, headers=hs).status_code == 200
    assert len(calls) == count
    assert client.get('/api/v1/payments/subscription', headers=headers('passenger')).json()['active']
    sub['status'] = 'canceled'
    event['id'] = 'evt_2'
    event['data']['object']['status'] = 'active'
    raw, hs = signed_event(event)
    assert client.post('/api/v1/payments/webhook', content=raw, headers=hs).status_code == 200
    assert not client.get('/api/v1/payments/subscription', headers=headers('passenger')).json()['active']
    assert client.post('/api/v1/payments/webhook', content=raw).status_code == 400
    raw, hs = signed_event(event, int(time.time()) - 1000)
    assert client.post('/api/v1/payments/webhook', content=raw, headers=hs).status_code == 400


def test_provider_failure_retry_uses_persisted_idempotency_key(client, provider, monkeypatch):
    original = billing.stripe_request
    keys = []
    async def fail_once(method, path, data=None, key=None):
        if method == 'POST' and path == 'subscriptions':
            keys.append(key)
            if len(keys) == 1: raise HTTPException(502, 'ambiguous network response')
        return await original(method, path, data, key)
    monkeypatch.setattr(billing, 'stripe_request', fail_once)
    assert client.post('/api/v1/payments/subscription-intent', headers=headers('passenger')).status_code == 502
    assert client.post('/api/v1/payments/subscription-intent', headers=headers('passenger')).status_code == 200
    assert len(keys) == 2 and keys[0] == keys[1]


def test_gate_only_new_rides_not_existing_obligations(client, provider, monkeypatch):
    monkeypatch.setattr(Config, 'REQUIRE_SUBSCRIPTION', True)
    assert client.post('/api/v1/ride/book', headers=headers('stranger')).status_code == 402
    # Existing legacy booking has no escrow, so cancellation needs review, not payment.
    assert client.post('/api/v1/rides/ride/cancel', headers=headers('passenger')).status_code == 409


def test_ownership_and_live_mode_mismatch_rejected(client, provider, monkeypatch):
    sub, _ = provider
    client.post('/api/v1/payments/subscription-intent', headers=headers('passenger'))
    sub['metadata']['user_id'] = 'stranger'
    assert client.get('/api/v1/payments/subscription', headers=headers('passenger')).status_code == 502
    monkeypatch.setattr(Config, 'STRIPE_SECRET_KEY', 'sk_live_not_allowed')
    assert client.post('/api/v1/payments/subscription-intent', headers=headers('passenger')).status_code == 503


def test_refund_or_dispute_removes_entitlement(client, provider):
    sub, _ = provider
    client.post('/api/v1/payments/subscription-intent', headers=headers('passenger'))
    paid(sub)
    for flag in ('refunded', 'disputed'):
        sub['latest_invoice']['payment_intent']['latest_charge'] = {flag: True}
        assert not client.get('/api/v1/payments/subscription', headers=headers('passenger')).json()['active']


def test_ambiguous_checkout_after_idempotency_window_requires_reconciliation(client, provider):
    async def seed():
        async with AsyncSessionLocal() as db:
            db.add(Membership(user_id='passenger', checkout_key='old', checkout_started=int(time.time()) - 86400,
                              price_id='price_monthly'))
            await db.commit()
    asyncio.run(seed())
    assert client.post('/api/v1/payments/subscription-intent', headers=headers('passenger')).status_code == 409
    assert not [c for c in provider[1] if c[0] == 'POST']
