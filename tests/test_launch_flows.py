import asyncio
import base64
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine, select

from conftest import headers
from test_credits import configure, balances
from app.core.database import AsyncSessionLocal
from app.models import CreditRefund
from app.routers.auth import mail
from app.services.credit_service import cancel_with_credits, complete_with_credits
from app.utils.uploads import save_profile_image, MAX_IMAGE_BYTES
from scripts.migrate_ride_lifecycle import migrate_ride_lifecycle


def test_passenger_refund_once_and_no_chat_access(client):
    asyncio.run(configure())
    assert client.post('/api/v1/ride/book', headers=headers('passenger')).status_code == 201
    assert client.post('/api/v1/rides/ride/cancel', headers=headers('stranger')).status_code == 409
    response = client.post('/api/v1/rides/ride/cancel', headers=headers('passenger'))
    assert response.status_code == 200, response.text
    assert response.json()['credits_refunded'] == 17
    before = asyncio.run(balances())
    assert before[0]['passenger'] == (100, 0)
    assert before[2] == 3
    assert client.post('/api/v1/rides/ride/cancel', headers=headers('passenger')).status_code == 409
    assert asyncio.run(balances()) == before
    assert client.get('/api/v1/message/ride/get', headers=headers('passenger')).status_code == 403


def test_driver_cancel_refunds_all_and_cannot_complete(client):
    asyncio.run(configure())
    for name in ['passenger', 'stranger']:
        assert client.post('/api/v1/ride/book', headers=headers(name)).status_code == 201
    response = client.post('/api/v1/rides/ride/cancel', headers=headers('driver'))
    assert response.json()['credits_refunded'] == 34
    snapshot = asyncio.run(balances())
    assert snapshot[0]['passenger'] == (100, 0)
    assert snapshot[0]['stranger'] == (100, 0)
    assert snapshot[0]['driver'] == (0, 0)
    assert client.post('/api/v1/rides/ride/complete', headers=headers('driver')).status_code == 409
    assert client.post('/api/v1/ride/book', headers=headers('passenger')).status_code == 409
    assert asyncio.run(balances()) == snapshot


def test_cancellation_races_completion_without_double_credit(client):
    asyncio.run(configure())
    assert client.post('/api/v1/ride/book', headers=headers('passenger')).status_code == 201
    async def race():
        return await asyncio.gather(cancel_with_credits('ride', 'driver'),
                                    complete_with_credits('ride', 'driver'), return_exceptions=True)
    results = asyncio.run(race())
    assert sum(isinstance(r, dict) for r in results) == 1
    assert [r.status_code for r in results if isinstance(r, HTTPException)] == [409]
    b = asyncio.run(balances())
    assert sum(a + e for a, e in b[0].values()) + b[1] == 200


def test_member_can_offer_multiple_future_rides_same_vehicle(client):
    data = {'vehicle_type': 'Sedan', 'vehicle_model': 'Toyota', 'vehicle_plate': 'MY-CAR',
            'available_seats': 2, 'departure_location': 'Cairo', 'destination': 'Giza',
            'departure_time': '2030-01-01T12:00:00+02:00', 'price_per_seat': 15}
    for _ in range(2):
        response = client.post('/api/v1/rides/new-ride', headers=headers('passenger'), json=data)
        assert response.status_code == 201, response.text
        assert response.json()['driver_id'] == 'passenger'
        assert response.json()['departure_time'].startswith('2030-01-01T10:00:00')
    data['departure_time'] = '2020-01-01T12:00:00Z'
    assert client.post('/api/v1/rides/new-ride', headers=headers('passenger'), json=data).status_code == 422
    data['departure_time'] = '2030-01-01T12:00:00'
    assert client.post('/api/v1/rides/new-ride', headers=headers('passenger'), json=data).status_code == 422


def test_reset_is_public_purpose_bound_and_not_reusable(client):
    data = {'first_name': 'Reset', 'last_name': 'Test', 'username': 'reset',
            'email': 'reset@example.com', 'mobile_number': '+201000000099',
            'gender': 'female', 'password': 'old-password-123'}
    assert client.post('/api/v1/auth/signup', data=data).status_code == 201
    verify_token = mail.send_message.call_args.args[0].template_body['verification_link'].rsplit('/', 1)[1]
    password = {'new_password': 'new-password-123', 'confirm_new_password': 'new-password-123'}
    assert client.post('/api/v1/auth/confirm-reset-password/' + verify_token, json=password).status_code == 400
    result = client.post('/api/v1/auth/reset-password', json={'email': data['email']})
    assert result.status_code == 200
    token = mail.send_message.call_args.args[0].template_body['reset_password_link'].rsplit('/', 1)[1]
    assert client.get('/api/v1/auth/verify/' + token).status_code == 400
    assert client.post('/api/v1/auth/confirm-reset-password/' + token, json=password).status_code == 200
    assert client.post('/api/v1/auth/confirm-reset-password/' + token, json=password).status_code == 400
    assert client.post('/api/v1/auth/login', json={'username': data['email'], 'password': 'new-password-123'}).status_code == 200
    assert client.post('/api/v1/auth/reset-password', json={'email': 'absent@example.com'}).json() == result.json()


def test_invalid_signup_is_validation_error(client):
    response = client.post('/api/v1/auth/signup', data={'first_name': 'A', 'last_name': 'B',
        'username': 'invalid', 'email': 'invalid@example.com', 'mobile_number': '01000000001',
        'gender': 'female', 'password': 'test-password'})
    assert response.status_code == 422


def test_upload_paths_types_and_size(monkeypatch, tmp_path):
    monkeypatch.setattr('app.utils.uploads.UPLOAD_DIR', str(tmp_path))
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jB9kAAAAASUVORK5CYII=')
    stored = asyncio.run(save_profile_image(UploadFile(filename='../../outside.png', file=BytesIO(png))))
    from pathlib import Path
    assert Path(stored).parent == tmp_path
    assert Path(stored).name != 'outside.png'
    for data, status in [(b'<svg>not a profile image</svg>', 422), (b'x' * (MAX_IMAGE_BYTES + 1), 413)]:
        with pytest.raises(HTTPException) as error:
            asyncio.run(save_profile_image(UploadFile(filename='valid.png', file=BytesIO(data))))
        assert error.value.status_code == status
    assert len(list(tmp_path.iterdir())) == 1


def test_plate_migration_preserves_rides_bookings_and_is_repeatable(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'migration.sqlite3'))
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE users (id TEXT PRIMARY KEY, password TEXT, is_verified INTEGER, is_active INTEGER)')
        conn.exec_driver_sql('CREATE TABLE rides (id TEXT PRIMARY KEY, vehicle_plate TEXT UNIQUE, is_available INTEGER, price_per_seat FLOAT)')
        conn.exec_driver_sql('CREATE TABLE bookings (id TEXT PRIMARY KEY, ride_id TEXT REFERENCES rides(id), seats_booked INTEGER, total_price FLOAT)')
        conn.exec_driver_sql("INSERT INTO rides VALUES ('ride', 'ABC', 1, 10)")
        conn.exec_driver_sql("INSERT INTO bookings VALUES ('booking', 'ride', 1, 10)")
        migrate_ride_lifecycle(conn)
        migrate_ride_lifecycle(conn)
        conn.exec_driver_sql("INSERT INTO rides VALUES ('next', 'ABC', 1, 10)")
        assert conn.exec_driver_sql('SELECT ride_id FROM bookings').scalar() == 'ride'
        assert conn.exec_driver_sql('SELECT COUNT(*) FROM rides').scalar() == 2
    engine.dispose()
