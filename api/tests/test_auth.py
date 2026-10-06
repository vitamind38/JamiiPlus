from helpers import bearer, last_code

from jamii_api.sms import ConsoleBackend


def test_chp_logs_in_with_one_time_code(client, make):
    chp = make.chp(make.unit())
    r = client.post("/api/v1/auth/otp/request", json={"phone": "0" + chp.phone[4:]})
    assert r.status_code == 202
    code = last_code(chp.phone)
    r = client.post("/api/v1/auth/otp/verify", json={"phone": chp.phone, "code": code})
    assert r.status_code == 200
    body = r.json()
    assert body["me"]["pseudonym"].startswith("CHP-")
    assert client.get("/api/v1/me", headers={"Authorization": "Bearer " + body["access_token"]}).status_code == 200
    # A code works once.
    assert client.post("/api/v1/auth/otp/verify", json={"phone": chp.phone, "code": code}).status_code == 401


def test_unknown_number_gets_the_same_answer_and_no_sms(client):
    r = client.post("/api/v1/auth/otp/request", json={"phone": "0799999999"})
    assert r.status_code == 202
    assert ConsoleBackend.sent == []


def test_officer_number_cannot_log_into_the_chp_app(client, make):
    user = make.user("county", county="Nairobi")
    client.post("/api/v1/auth/otp/request", json={"phone": user.phone})
    assert ConsoleBackend.sent == []


def test_wrong_codes_lock_the_number(client, make):
    chp = make.chp(make.unit())
    client.post("/api/v1/auth/otp/request", json={"phone": chp.phone})
    good = last_code(chp.phone)
    bad = "000000" if good != "000000" else "111111"
    for _ in range(5):
        assert client.post("/api/v1/auth/otp/verify", json={"phone": chp.phone, "code": bad}).status_code == 401
    r = client.post("/api/v1/auth/otp/verify", json={"phone": chp.phone, "code": good})
    assert r.status_code == 429
    assert client.post("/api/v1/auth/otp/request", json={"phone": chp.phone}).status_code == 429


def test_code_requests_are_rate_limited(client, make):
    chp = make.chp(make.unit())
    for _ in range(3):
        assert client.post("/api/v1/auth/otp/request", json={"phone": chp.phone}).status_code == 202
    assert client.post("/api/v1/auth/otp/request", json={"phone": chp.phone}).status_code == 429


def test_logout_revokes_tokens(client, make):
    chp = make.chp(make.unit())
    headers = bearer(chp)
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/me", headers=headers).status_code == 401


def test_deactivated_chp_cannot_use_token(client, make, db):
    chp = make.chp(make.unit())
    headers = bearer(chp)
    chp.active = False
    db.commit()
    assert client.get("/api/v1/me", headers=headers).status_code == 401


def test_bad_phone_is_rejected(client):
    assert client.post("/api/v1/auth/otp/request", json={"phone": "12"}).status_code == 422
