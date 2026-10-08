from conftest import headers
from app.routers.auth import mail

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
    profile = client.get('/api/v1/users/profile', headers={'Authorization':'Bearer '+login.json()['access_token']})
    assert profile.status_code == 200, profile.text
    assert profile.json()['credit_balance'] == 0
    assert profile.json()['escrow_balance'] == 0
    assert 'password' not in profile.json()
