import uuid
from fastapi.testclient import TestClient
from main import app, SESSION_COOKIE_NAME


def test_session_cookie_created_on_history():
    """Verify that GET /api/history generates an HttpOnly session cookie if none exists."""
    client = TestClient(app)
    response = client.get("/api/history")
    assert response.status_code == 200
    assert SESSION_COOKIE_NAME in response.cookies
    session_id_str = response.json().get("session_id")
    assert session_id_str is not None
    assert str(uuid.UUID(session_id_str)) == session_id_str


def test_session_cookie_created_on_session_endpoint():
    """Verify that GET /api/session generates an HttpOnly session cookie if none exists."""
    client = TestClient(app)
    response = client.get("/api/session")
    assert response.status_code == 200
    assert SESSION_COOKIE_NAME in response.cookies
    session_id_str = response.json().get("session_id")
    assert session_id_str is not None
    assert str(uuid.UUID(session_id_str)) == session_id_str


def test_session_persists_across_requests():
    """Verify that sending the session cookie reuses the existing session."""
    client = TestClient(app)
    first_resp = client.get("/api/session")
    first_session_id = first_resp.json()["session_id"]

    second_resp = client.get("/api/history")
    second_session_id = second_resp.json()["session_id"]

    assert first_session_id == second_session_id


def test_ignore_spoofed_session_id_in_query_params():
    """Verify that query param ?session_id=<victim_uuid> is IGNORED and cannot access victim history."""
    victim_uuid = str(uuid.uuid4())
    client = TestClient(app)

    res1 = client.get("/api/session")
    user_session_id = res1.json()["session_id"]
    assert user_session_id != victim_uuid

    res2 = client.get(f"/api/history?session_id={victim_uuid}")
    assert res2.status_code == 200
    assert res2.json()["session_id"] == user_session_id
    assert res2.json()["session_id"] != victim_uuid


def test_ignore_spoofed_session_id_in_header():
    """Verify that X-Session-Id header is IGNORED."""
    victim_uuid = str(uuid.uuid4())
    client = TestClient(app)

    res1 = client.get("/api/session")
    user_session_id = res1.json()["session_id"]

    res2 = client.get("/api/history", headers={"X-Session-Id": victim_uuid})
    assert res2.status_code == 200
    assert res2.json()["session_id"] == user_session_id


def test_invalid_cookie_generates_new_valid_session():
    """Verify that an invalid or malformed cookie gets safely replaced with a new valid session."""
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE_NAME, "not-a-valid-uuid")

    response = client.get("/api/history")
    assert response.status_code == 200
    new_session_id = response.json()["session_id"]
    assert new_session_id != "not-a-valid-uuid"
    assert str(uuid.UUID(new_session_id)) == new_session_id
