# The security audit, kept as tests: every attack we tried before going live runs on every `pytest`.
import base64  # build a forged token by hand
import json  # build a forged token by hand

import pytest  # the testing tool
from fastapi.testclient import TestClient  # the fake browser type

from app import ai  # the Gemini helper we replace with a fake
from app.ai import AIPlan  # the shape of a Gemini answer
from app.main import app  # our app
from app.routers import clients as clients_router, tasks as tasks_router  # to lower the caps in tests

PASSWORD = "correct-horse-battery"


def login_form(email: str, password: str) -> dict:
    return {"username": email, "password": password}


# ---- logins ----

def test_brute_force_login_is_stopped(client: TestClient, anon: TestClient) -> None:
    codes = [anon.post("/auth/login", data=login_form("ayesha@example.com", f"guess-{i}-xx")).status_code for i in range(15)]
    assert codes[:9].count(401) == 9  # the first tries get the normal "wrong password" (login fixture used 1 of the 10)
    assert codes[-1] == 429  # then: "too many attempts", no matter what


def test_lockout_is_per_account_too(client: TestClient, anon: TestClient) -> None:
    from app.guard import limiter
    for i in range(12):  # 12 wrong guesses, each "from a different network"
        limiter.hits.pop("login-ip:testclient", None)  # pretend the IP changes every time
        anon.post("/auth/login", data=login_form("ayesha@example.com", f"guess-{i}-xx"))
    limiter.hits.pop("login-ip:testclient", None)
    assert anon.post("/auth/login", data=login_form("ayesha@example.com", PASSWORD)).status_code == 429  # the account itself is paused for 15 min


def test_mass_sign_up_is_stopped(anon: TestClient) -> None:
    codes = [anon.post("/auth/register", json={"email": f"bot{i}@example.com", "password": PASSWORD}).status_code for i in range(8)]
    assert codes.count(201) == 5 and codes[-1] == 429  # 5 accounts an hour per network


@pytest.mark.parametrize("password", ["password123", "12345678", "aaaaaaaa", "abababab", "pakistan123", "newperson99"])
def test_weak_passwords_are_refused(anon: TestClient, password: str) -> None:
    assert anon.post("/auth/register", json={"email": "newperson@example.com", "password": password}).status_code == 422


def test_forged_tokens_are_refused(client: TestClient, anon: TestClient) -> None:
    b64 = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    none_alg = b64({"alg": "none", "typ": "JWT"}) + "." + b64({"sub": "1", "exp": 9999999999}) + "."
    real = client.headers["Authorization"].split()[1].split(".")
    edited = real[0] + "." + b64({"sub": "2", "exp": 9999999999}) + "." + real[2]  # someone else's id, old signature
    for token in [none_alg, edited, "abc.def.ghi"]:
        assert anon.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


# ---- changing the URL ----

def test_changing_the_url_never_shows_someone_elses_data(client: TestClient, other_user: TestClient) -> None:
    task_id = client.post("/tasks", json={"title": "secret plan"}).json()["id"]
    person_id = client.post("/clients", json={"name": "Bilal"}).json()["id"]
    for method, url in [("GET", f"/tasks/{task_id}"), ("PATCH", f"/tasks/{task_id}"), ("DELETE", f"/tasks/{task_id}"),
                        ("GET", f"/clients/{person_id}"), ("GET", f"/clients/{person_id}/tasks"), ("DELETE", f"/clients/{person_id}")]:
        response = other_user.request(method, url, json={"title": "hacked"} if method == "PATCH" else None)
        assert response.status_code == 404, (method, url)  # "not found": they can't even tell it exists
    assert client.get(f"/tasks/{task_id}").json()["title"] == "secret plan"  # untouched


@pytest.mark.parametrize("url", ["/tasks/99999999999999999999", "/tasks/0", "/tasks/-5", "/tasks/abc", "/clients/99999999999999999999",
                                 "/tasks?client_id=99999999999999999999", "/tasks?assignee_id=-1"])
def test_weird_ids_are_a_clean_422_not_a_crash(client: TestClient, url: str) -> None:
    assert client.get(url).status_code == 422  # used to be a 500 for the huge number


def test_huge_ids_in_the_body_are_refused(client: TestClient) -> None:
    assert client.post("/tasks", json={"title": "x", "client_id": 99999999999999999999}).status_code == 422
    assert client.post("/reminders/snooze", json={"task_id": 99999999999999999999}).status_code == 422


@pytest.mark.parametrize("url", ["/.env", "/..%2f.env", "/%2e%2e/%2e%2e/.env", "/app/clock.py", "/static/../.env", "/../requirements.txt"])
def test_secret_files_cannot_be_reached(anon: TestClient, url: str) -> None:
    assert anon.get(url).status_code == 404


# ---- floods and big requests ----

def test_api_flood_is_slowed_down(client: TestClient) -> None:
    codes = [client.get("/tasks").status_code for _ in range(310)]  # login used a few; 300 a minute per IP
    assert codes[0] == 200 and codes[-1] == 429
    assert client.get("/health").status_code == 200  # the server is fine


def test_huge_request_is_refused_before_reading(client: TestClient) -> None:
    response = client.post("/tasks", content=b'{"title":"' + b"x" * 1_200_000 + b'"}', headers={"Content-Type": "application/json"})
    assert response.status_code == 413


def test_too_many_tasks(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks_router, "MAX_TASKS", 3)
    codes = [client.post("/tasks", json={"title": f"t{i}"}).status_code for i in range(4)]
    assert codes == [201, 201, 201, 409]


def test_too_many_people(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clients_router, "MAX_PEOPLE", 2)
    codes = [client.post("/clients", json={"name": f"p{i}"}).status_code for i in range(3)]
    assert codes == [201, 201, 409]


def test_unverified_accounts_get_only_3_ai_requests(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai, "ask_ai", lambda message, clients: AIPlan(tasks=[]))
    codes = [client.post("/planner/propose", json={"message": "kal gym jana ha"}).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]  # fake accounts can't drain the AI


# ---- what the browser is told ----

def test_security_headers(anon: TestClient) -> None:
    headers = anon.get("/").headers
    assert headers["X-Frame-Options"] == "DENY" and headers["X-Content-Type-Options"] == "nosniff"
    csp = headers["Content-Security-Policy"]
    assert "script-src 'sha256-" in csp and "frame-ancestors 'none'" in csp and "unsafe-eval" not in csp  # only OUR script may run


def test_crash_shows_no_internals(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    browser = TestClient(app, raise_server_exceptions=False)  # behave like a real server
    browser.headers.update(client.headers)  # same logged-in user
    monkeypatch.setattr(tasks_router, "find_task_or_404", lambda *a: (_ for _ in ()).throw(RuntimeError("database password is hunter2")))
    response = browser.get("/tasks/1")
    assert response.status_code == 500
    assert "hunter2" not in response.text and "Traceback" not in response.text  # nothing internal leaks
    assert response.json()["detail"] == "Something went wrong on our side. Please try again."


def test_xss_and_sql_text_is_stored_as_plain_text(client: TestClient) -> None:
    for title in ["'; DROP TABLE tasks; --", "<script>alert(1)</script>", "<img src=x onerror=alert(1)>"]:
        assert client.post("/tasks", json={"title": title}).json()["title"] == title  # kept exactly as text
    assert len(client.get("/tasks").json()) == 3  # the table is fine
