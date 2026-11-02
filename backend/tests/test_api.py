import base64
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
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


# --- Elections ---
def admin_headers():
    token = create_access_token({"sub": "admin-test", "role": "admin", "email": "admin@example.com"})
    return bearer(token)


def voter_headers(client):
    email = new_email()
    register(client, email)
    return bearer(get_token(client, email))


def election_payload(start_days, end_days, title=None):
    now = datetime.now(timezone.utc)
    return {
        "title": title or f"Election {uuid.uuid4().hex[:8]}",
        "description": "test",
        "start_date": (now + timedelta(days=start_days)).isoformat(),
        "end_date": (now + timedelta(days=end_days)).isoformat(),
    }


def test_election_list_without_token_is_rejected(client):
    assert client.get("/elections").status_code == 401


def test_voter_cannot_create_an_election(client):
    resp = client.post("/elections", json=election_payload(-1, 1), headers=voter_headers(client))
    assert resp.status_code == 403


def test_admin_creates_an_election_and_voter_sees_it(client):
    payload = election_payload(-1, 1)
    created = client.post("/elections", json=payload, headers=admin_headers())
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "active"
    assert body["candidates"] == []
    assert "total_votes" not in body
    listed = client.get("/elections", headers=voter_headers(client))
    assert listed.status_code == 200
    assert body["id"] in [e["id"] for e in listed.json()]


def test_election_status_comes_from_the_dates(client):
    upcoming = client.post("/elections", json=election_payload(1, 2), headers=admin_headers())
    ended = client.post("/elections", json=election_payload(-2, -1), headers=admin_headers())
    assert upcoming.json()["status"] == "upcoming"
    assert ended.json()["status"] == "ended"


def test_election_with_end_before_start_is_rejected(client):
    resp = client.post("/elections", json=election_payload(2, 1), headers=admin_headers())
    assert resp.status_code == 422


def test_election_dates_without_timezone_are_rejected(client):
    payload = election_payload(-1, 1)
    payload["start_date"] = "2030-01-01T10:00:00"
    payload["end_date"] = "2030-01-02T10:00:00"
    resp = client.post("/elections", json=payload, headers=admin_headers())
    assert resp.status_code == 422


def test_election_needs_a_title(client):
    resp = client.post("/elections", json=election_payload(-1, 1, title="   "), headers=admin_headers())
    assert resp.status_code == 422


# --- Candidates and election removal ---
def make_election(client, start_days, end_days):
    resp = client.post("/elections", json=election_payload(start_days, end_days), headers=admin_headers())
    assert resp.status_code == 201
    return resp.json()["id"]


def make_candidate(client, election_id, name="Ada"):
    return client.post(
        f"/elections/{election_id}/candidates",
        json={"name": name, "party": "Test Party"},
        headers=admin_headers(),
    )


def candidate_ids(client, election_id):
    listed = client.get("/elections", headers=admin_headers()).json()
    election = next(e for e in listed if e["id"] == election_id)
    return [c["id"] for c in election["candidates"]]


def test_voter_cannot_add_a_candidate(client):
    election_id = make_election(client, 1, 2)
    resp = client.post(
        f"/elections/{election_id}/candidates",
        json={"name": "Nope"},
        headers=voter_headers(client),
    )
    assert resp.status_code == 403


def test_admin_adds_a_candidate_and_it_shows_in_the_election_list(client):
    election_id = make_election(client, 1, 2)
    resp = make_candidate(client, election_id)
    assert resp.status_code == 201
    assert resp.json()["name"] == "Ada"
    assert resp.json()["id"] in candidate_ids(client, election_id)


def test_candidate_for_unknown_election_is_404(client):
    resp = client.post(
        f"/elections/{uuid.uuid4()}/candidates",
        json={"name": "Ghost"},
        headers=admin_headers(),
    )
    assert resp.status_code == 404


def test_candidate_needs_a_name(client):
    election_id = make_election(client, 1, 2)
    resp = client.post(
        f"/elections/{election_id}/candidates",
        json={"name": "   "},
        headers=admin_headers(),
    )
    assert resp.status_code == 422


def test_candidates_cannot_be_added_once_the_election_started(client):
    election_id = make_election(client, -1, 1)
    assert make_candidate(client, election_id).status_code == 409


def test_admin_deletes_a_candidate_before_the_election_starts(client):
    election_id = make_election(client, 1, 2)
    candidate = make_candidate(client, election_id).json()
    resp = client.delete(f"/candidates/{candidate['id']}", headers=admin_headers())
    assert resp.status_code == 204
    assert candidate["id"] not in candidate_ids(client, election_id)


def test_voter_cannot_delete_a_candidate(client):
    election_id = make_election(client, 1, 2)
    candidate = make_candidate(client, election_id).json()
    resp = client.delete(f"/candidates/{candidate['id']}", headers=voter_headers(client))
    assert resp.status_code == 403


def test_deleting_an_unknown_candidate_is_404(client):
    resp = client.delete(f"/candidates/{uuid.uuid4()}", headers=admin_headers())
    assert resp.status_code == 404


def test_admin_deletes_an_election_and_its_candidates_go_with_it(client):
    election_id = make_election(client, 1, 2)
    candidate = make_candidate(client, election_id).json()
    resp = client.delete(f"/elections/{election_id}", headers=admin_headers())
    assert resp.status_code == 204
    listed = client.get("/elections", headers=admin_headers()).json()
    assert election_id not in [e["id"] for e in listed]
    assert client.delete(f"/candidates/{candidate['id']}", headers=admin_headers()).status_code == 404


def test_voter_cannot_delete_an_election(client):
    election_id = make_election(client, 1, 2)
    resp = client.delete(f"/elections/{election_id}", headers=voter_headers(client))
    assert resp.status_code == 403


def test_deleting_an_unknown_election_is_404(client):
    resp = client.delete(f"/elections/{uuid.uuid4()}", headers=admin_headers())
    assert resp.status_code == 404


# --- Voting ---
@pytest.fixture(scope="module")
def open_election(client):
    """An election built the way a real one is: candidates first, then it starts."""
    now = datetime.now(timezone.utc)
    payload = {
        "title": f"Open {uuid.uuid4().hex[:8]}",
        "description": "test",
        "start_date": (now + timedelta(seconds=2)).isoformat(),
        "end_date": (now + timedelta(hours=1)).isoformat(),
    }
    created = client.post("/elections", json=payload, headers=admin_headers())
    assert created.status_code == 201
    election_id = created.json()["id"]
    cand_a = make_candidate(client, election_id, "Ada").json()["id"]
    cand_b = make_candidate(client, election_id, "Bola").json()["id"]
    time.sleep(3)
    return election_id, cand_a, cand_b


def cast(client, election_id, candidate_id, headers):
    return client.post(
        f"/elections/{election_id}/votes",
        json={"candidate_id": candidate_id},
        headers=headers,
    )


def has_voted(client, election_id, headers):
    return client.get(f"/elections/{election_id}/my-vote", headers=headers).json()["has_voted"]


def test_vote_without_token_is_rejected(client, open_election):
    election_id, cand_a, _ = open_election
    resp = client.post(f"/elections/{election_id}/votes", json={"candidate_id": cand_a})
    assert resp.status_code == 401


def test_voter_votes_once_and_my_vote_reflects_it(client, open_election):
    election_id, cand_a, _ = open_election
    voter = voter_headers(client)
    other = voter_headers(client)
    assert has_voted(client, election_id, voter) is False
    resp = cast(client, election_id, cand_a, voter)
    assert resp.status_code == 201
    assert cand_a not in resp.text
    assert has_voted(client, election_id, voter) is True
    assert has_voted(client, election_id, other) is False


def test_second_vote_in_the_same_election_is_refused(client, open_election):
    election_id, cand_a, cand_b = open_election
    voter = voter_headers(client)
    assert cast(client, election_id, cand_a, voter).status_code == 201
    assert cast(client, election_id, cand_b, voter).status_code == 409
    assert has_voted(client, election_id, voter) is True


def test_cannot_vote_before_the_election_starts(client):
    election_id = make_election(client, 1, 2)
    resp = cast(client, election_id, str(uuid.uuid4()), voter_headers(client))
    assert resp.status_code == 409


def test_cannot_vote_after_the_election_ended(client):
    election_id = make_election(client, -2, -1)
    resp = cast(client, election_id, str(uuid.uuid4()), voter_headers(client))
    assert resp.status_code == 409


def test_candidate_from_another_election_is_refused(client, open_election):
    election_id, _, _ = open_election
    other_election = make_election(client, 1, 2)
    foreign = make_candidate(client, other_election).json()["id"]
    resp = cast(client, election_id, foreign, voter_headers(client))
    assert resp.status_code == 422


def test_vote_in_unknown_election_is_404(client):
    resp = cast(client, str(uuid.uuid4()), str(uuid.uuid4()), voter_headers(client))
    assert resp.status_code == 404


def test_token_for_unknown_user_cannot_vote(client, open_election):
    election_id, cand_a, _ = open_election
    resp = cast(client, election_id, cand_a, admin_headers())
    assert resp.status_code == 401


def test_two_simultaneous_votes_from_one_voter_count_once(client, open_election):
    election_id, cand_a, cand_b = open_election
    voter = voter_headers(client)
    barrier = threading.Barrier(2)

    def fire(candidate_id):
        barrier.wait()
        return cast(client, election_id, candidate_id, voter).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(fire, [cand_a, cand_b]))
    assert sorted(results) == [201, 409]
