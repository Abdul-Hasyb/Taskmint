from datetime import datetime, timedelta, timezone  # for making an already-expired token

import jwt  # PyJWT, to build fake tokens
import pytest  # the testing tool
from fastapi.testclient import TestClient  # the fake browser type

from app import ai  # the Gemini helper, replaced with a fake below
from app.ai import AIPlan  # the shape of a Gemini answer
from app.security import ALGORITHM, JWT_SECRET  # how real tokens are signed

PASSWORD = "correct-horse-battery"  # same as in conftest.py


def test_register_and_login(anon: TestClient) -> None:  # the full happy path
    response = anon.post("/auth/register", json={"email": "  Bilal@Example.com ", "password": PASSWORD})  # messy email on purpose
    assert response.status_code == 201  # created
    assert response.json()["email"] == "bilal@example.com"  # trimmed and lowercased
    assert "password" not in response.text and "argon2" not in response.text  # neither the password nor its hash is ever sent back
    login = anon.post("/auth/login", data={"username": "BILAL@example.com", "password": PASSWORD})  # log in (email in any case)
    assert login.status_code == 200  # worked
    token = login.json()["access_token"]  # the token
    me = anon.get("/auth/me", headers={"Authorization": f"Bearer {token}"})  # who am I?
    assert me.json()["email"] == "bilal@example.com"  # the right account


def test_duplicate_email_rejected(anon: TestClient) -> None:  # one account per email
    anon.post("/auth/register", json={"email": "sara@example.com", "password": PASSWORD})  # first time: fine
    response = anon.post("/auth/register", json={"email": "SARA@example.com", "password": PASSWORD})  # same email, different case
    assert response.status_code == 409  # Conflict


def test_wrong_password_and_unknown_email_look_the_same(anon: TestClient) -> None:  # no hints for attackers
    anon.post("/auth/register", json={"email": "sara@example.com", "password": PASSWORD})  # a real account
    wrong_password = anon.post("/auth/login", data={"username": "sara@example.com", "password": "wrong-password"})  # real email, wrong password
    unknown_email = anon.post("/auth/login", data={"username": "nobody@example.com", "password": PASSWORD})  # email that doesn't exist
    assert wrong_password.status_code == unknown_email.status_code == 401  # both 401
    assert wrong_password.json() == unknown_email.json() == {"detail": "Incorrect email or password"}  # word for word the same


def test_password_is_stored_hashed(client: TestClient) -> None:  # the real password must never be in the database
    from app.database import SessionLocal  # open the test database directly
    from app.models import User  # the users table
    with SessionLocal() as db:  # look inside
        stored = db.query(User).first().password_hash  # what was saved
    assert stored != PASSWORD and stored.startswith("$argon2")  # a scrambled Argon2 hash, not the password


# ---- Security tests: no token, bad tokens ----

@pytest.mark.parametrize("method, path", [("get", "/tasks"), ("post", "/tasks"), ("get", "/clients"), ("post", "/planner/propose"), ("get", "/auth/me")])
def test_endpoints_need_login(anon: TestClient, method: str, path: str) -> None:  # every private endpoint, without a token
    response = anon.request(method.upper(), path)  # e.g. GET /tasks, with no token
    assert response.status_code == 401  # "who are you?"


def test_health_is_public(anon: TestClient) -> None:  # the health check must work without logging in
    assert anon.get("/health").status_code == 200  # hosting services need it


def test_rejects_fake_and_expired_tokens(client: TestClient, anon: TestClient) -> None:  # tokens can't be forged or reused forever
    user_id = client.get("/auth/me").json()["id"]  # a real user id
    forged = jwt.encode({"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, "wrong-secret-wrong-secret-wrong-secret", algorithm=ALGORITHM)  # signed with the WRONG secret
    expired = jwt.encode({"sub": str(user_id), "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}, JWT_SECRET, algorithm=ALGORITHM)  # right secret, but expired
    for token in [forged, expired, "not-a-token"]:  # each bad token
        assert anon.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401  # all rejected


def test_rejects_bad_registration(anon: TestClient) -> None:  # bad emails and weak passwords
    assert anon.post("/auth/register", json={"email": "not-an-email", "password": PASSWORD}).status_code == 422  # not an email
    assert anon.post("/auth/register", json={"email": "a@example.com", "password": "short"}).status_code == 422  # under 8 characters
    assert anon.post("/auth/register", json={"email": "a@example.com", "password": "x" * 129}).status_code == 422  # absurdly long


# ---- Security tests: users can't touch each other's data ----

def test_users_only_see_their_own_tasks(client: TestClient, other_user: TestClient) -> None:  # Ayesha's tasks are invisible to Omar
    task_id = client.post("/tasks", json={"title": "Ayesha's secret task"}).json()["id"]  # Ayesha makes a task
    assert other_user.get("/tasks").json() == []  # Omar's list is empty
    assert other_user.get(f"/tasks/{task_id}").status_code == 404  # 404, not 403: Omar can't even tell it exists
    assert other_user.patch(f"/tasks/{task_id}", json={"status": "done"}).status_code == 404  # can't change it
    assert other_user.delete(f"/tasks/{task_id}").status_code == 404  # can't delete it
    assert client.get(f"/tasks/{task_id}").json()["status"] == "todo"  # Ayesha's task is untouched


def test_users_only_see_their_own_clients(client: TestClient, other_user: TestClient) -> None:  # same for clients
    client_id = client.post("/clients", json={"name": "Bilal"}).json()["id"]  # Ayesha's client
    assert other_user.get("/clients").json() == []  # Omar sees none
    assert other_user.get(f"/clients/{client_id}").status_code == 404  # can't open it
    assert other_user.get(f"/clients/{client_id}/tasks").status_code == 404  # can't see its page
    assert other_user.delete(f"/clients/{client_id}").status_code == 404  # can't delete it


def test_cannot_use_another_users_client(client: TestClient, other_user: TestClient) -> None:  # can't attach tasks to someone else's client
    client_id = client.post("/clients", json={"name": "Bilal"}).json()["id"]  # Ayesha's client
    assert other_user.post("/tasks", json={"title": "Sneaky", "client_id": client_id}).status_code == 422  # create: rejected
    assert other_user.post("/planner/approve", json={"tasks": [{"title": "Sneaky", "client_id": client_id}]}).status_code == 422  # approve: rejected


def test_planner_only_sees_my_clients(client: TestClient, other_user: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # the AI is never told about other users' clients
    client.post("/clients", json={"name": "Bilal"})  # Ayesha's client
    seen = {}  # what the AI was given
    def spy(message, clients):  # a fake AI that remembers its input
        seen["clients"] = clients  # record the client list
        return AIPlan(tasks=[])  # no tasks
    monkeypatch.setattr(ai, "ask_ai", spy)  # swap it in
    other_user.post("/planner/propose", json={"message": "Bilal needs a reel"})  # Omar asks the planner
    assert seen["clients"] == []  # the AI never saw Ayesha's client list