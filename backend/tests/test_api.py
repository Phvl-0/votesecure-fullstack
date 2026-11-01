import base64
import json
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

import main
from main import app, create_access_token

PASSWORD = "throwaway-pass-123"


@pytest.fixture(scope="module")
def client():
    # Using "with" runs the app's startup code, which creates the tables.
    with TestClient(app) as c:
        yield c


def new_email():
    return f"test-{uuid.uuid4().hex[:12]}@example.com"


def register(client, email, **extra):
    return client.post("/register", json={"email": email, "password": PASSWORD, **extra})


def get_token(client, email):
    resp = client.post("/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def b64(data):
    raw = json.dumps(data).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


# --- Sign-up and login ---

def test_register_ignores_role_and_id_sent_by_caller(client):
    email = new_email()
    resp = register(client, email, role="admin", id="attacker-chosen-id")
    assert resp.status_code == 200
    assert resp.json()["user_id"] != "attacker-chosen-id"
    me = client.get("/me", headers=bearer(get_token(client, email)))
    assert me.json()["profile"]["role"] == "voter"


def test_duplicate_email_is_rejected(client):
    email = new_email()
    assert register(client, email).status_code == 200
    assert register(client, email).status_code == 400


def test_login_with_wrong_password_gives_no_token(client):
    email = new_email()
    register(client, email)
    resp = client.post("/login", json={"email": email, "password": "wrong-password"})
    assert 400 <= resp.status_code < 500
    assert "access_token" not in resp.text


def test_login_for_unknown_user_gives_no_token(client):
    resp = client.post("/login", json={"email": new_email(), "password": PASSWORD})
    assert 400 <= resp.status_code < 500
    assert "access_token" not in resp.text


# --- Tokens ---

def test_me_without_token_is_rejected(client):
    assert client.get("/me").status_code == 401


def test_me_with_valid_token_returns_profile(client):
    email = new_email()
    register(client, email)
    resp = client.get("/me", headers=bearer(get_token(client, email)))
    assert resp.status_code == 200
    assert resp.json()["profile"]["email"] == email


def test_tampered_token_is_rejected(client):
    email = new_email()
    register(client, email)
    token = get_token(client, email)
    assert client.get("/me", headers=bearer(token + "x")).status_code == 401


def test_expired_token_is_rejected(client):
    payload = {
        "sub": "1",
        "role": "voter",
        "email": "a@example.com",
        "exp": datetime.now(timezone.utc) - timedelta(minutes=5),
    }
    token = jwt.encode(payload, main.SECRET_KEY, algorithm=main.ALGORITHM)
    assert client.get("/me", headers=bearer(token)).status_code == 401


def test_token_signed_with_another_key_is_rejected(client):
    payload = {"sub": "1", "role": "admin", "email": "a@example.com"}
    token = jwt.encode(payload, "x" * 40, algorithm="HS256")
    assert client.get("/admin/users", headers=bearer(token)).status_code == 401


def test_unsigned_token_with_alg_none_is_rejected(client):
    header = b64({"alg": "none", "typ": "JWT"})
    body = b64({"sub": "1", "role": "admin", "email": "a@example.com"})
    forged = f"{header}.{body}."
    assert client.get("/admin/users", headers=bearer(forged)).status_code == 401


def test_token_without_subject_is_rejected(client):
    token = create_access_token({"role": "admin", "email": "a@example.com"})
    assert client.get("/me", headers=bearer(token)).status_code == 401


# --- Roles ---

def test_admin_endpoint_without_token_is_unauthorized(client):
    assert client.get("/admin/users").status_code == 401


def test_admin_endpoint_refuses_a_voter(client):
    email = new_email()
    register(client, email)
    resp = client.get("/admin/users", headers=bearer(get_token(client, email)))
    assert resp.status_code == 403


def test_admin_endpoint_allows_an_admin_and_hides_password_hashes(client):
    email = new_email()
    register(client, email)
    token = create_access_token({"sub": "admin-test", "role": "admin", "email": "admin@example.com"})
    resp = client.get("/admin/users", headers=bearer(token))
    assert resp.status_code == 200
    assert email in [u["email"] for u in resp.json()]
    assert "hashed_password" not in resp.text
    assert "$2b$" not in resp.text
