import re  # find the 6-digit code inside the email
from datetime import timedelta  # move the clock forward

import pytest  # the testing tool
from fastapi.testclient import TestClient  # a fake browser

from app import clock, mailer  # the clock we move and the email code we fake
from app.main import app  # our app
from tests.conftest import PASSWORD  # the password every test user starts with

NEW = "Mango-Tree-42"  # the new password used below


@pytest.fixture
def inbox(monkeypatch: pytest.MonkeyPatch):  # a fake Brevo: emails land in this list instead of the internet
    sent: list[dict] = []
    monkeypatch.setenv("BREVO_API_KEY", "fake-key")  # make the server think email is set up
    monkeypatch.setenv("EMAIL_FROM", "taskmint@example.com")
    monkeypatch.setattr(mailer, "brevo_send", lambda to, subject, html_body, text_body: sent.append({"to": to, "subject": subject, "html": html_body, "text": text_body}) or True)
    return sent


def ask_code(browser: TestClient, email: str = "ayesha@example.com"):  # "Forgot password?" → email
    return browser.post("/auth/forgot-password", json={"email": email})


def code_in(mail: dict) -> str:  # the code from the email's plain text
    return re.search(r"\b(\d{6})\b", mail["text"]).group(1)


def reset(browser: TestClient, code: str, password: str = NEW, email: str = "ayesha@example.com"):
    return browser.post("/auth/reset-password", json={"email": email, "code": code, "password": password})


def can_log_in(password: str, email: str = "ayesha@example.com") -> bool:
    return TestClient(app).post("/auth/login", data={"username": email, "password": password}).status_code == 200


def test_the_whole_flow_works(client: TestClient, inbox) -> None:
    anon = TestClient(app)  # forgot password = NOT logged in
    assert ask_code(anon).status_code == 200
    assert len(inbox) == 1 and inbox[0]["to"] == "ayesha@example.com"  # only to the account's own address
    code = code_in(inbox[0])
    assert code not in inbox[0]["subject"]  # not shown on phone lock screens
    response = reset(anon, code)
    assert response.status_code == 200, response.text
    assert can_log_in(NEW) and not can_log_in(PASSWORD)  # new password in, old one out
    assert client.get("/auth/me").json()["email_verified"] is True  # the code proved the inbox is theirs


def test_unknown_email_gets_the_same_answer(client: TestClient, inbox) -> None:  # nobody can find out who has an account
    real = ask_code(TestClient(app), "ayesha@example.com")
    fake = ask_code(TestClient(app), "nobody@example.com")
    assert real.status_code == fake.status_code == 200 and real.json() == fake.json()
    assert [m["to"] for m in inbox] == ["ayesha@example.com"]  # but only the real one got an email


def test_wrong_code_is_refused(client: TestClient, inbox) -> None:
    ask_code(TestClient(app))
    wrong = "000000" if code_in(inbox[0]) != "000000" else "111111"
    assert reset(TestClient(app), wrong).status_code == 400
    assert can_log_in(PASSWORD)  # nothing changed


def test_five_wrong_codes_kill_the_code(client: TestClient, inbox) -> None:  # no guessing a 6-digit code
    ask_code(TestClient(app))
    real = code_in(inbox[0])
    wrongs = [c for c in ("000000", "111111", "222222", "333333", "444444", "555555") if c != real][:5]
    codes = [reset(TestClient(app), w).status_code for w in wrongs]
    assert codes == [400] * 5
    assert reset(TestClient(app), real).status_code == 400  # even the RIGHT code is dead now
    assert can_log_in(PASSWORD)


def test_code_expires_after_15_minutes(client: TestClient, inbox, monkeypatch: pytest.MonkeyPatch) -> None:
    start = clock.utc_now()
    monkeypatch.setattr(clock, "utc_now", lambda: start)
    ask_code(TestClient(app))
    monkeypatch.setattr(clock, "utc_now", lambda: start + timedelta(minutes=16))  # 16 minutes later
    assert reset(TestClient(app), code_in(inbox[0])).status_code == 400
    assert can_log_in(PASSWORD)


def test_code_works_only_once(client: TestClient, inbox) -> None:
    ask_code(TestClient(app))
    code = code_in(inbox[0])
    assert reset(TestClient(app), code).status_code == 200
    assert reset(TestClient(app), code, password="Another-Pass-77").status_code == 400  # replaying it does nothing
    assert can_log_in(NEW)


def test_new_code_replaces_the_old_one(client: TestClient, inbox) -> None:
    ask_code(TestClient(app))
    ask_code(TestClient(app))
    first, second = code_in(inbox[0]), code_in(inbox[1])
    if first != second:  # (1 in a million they're the same)
        assert reset(TestClient(app), first).status_code == 400
    assert reset(TestClient(app), second).status_code == 200


def test_one_accounts_code_cant_reset_another(client: TestClient, other_user: TestClient, inbox) -> None:
    ask_code(TestClient(app), "ayesha@example.com")
    assert reset(TestClient(app), code_in(inbox[0]), email="omar@example.com").status_code == 400  # Ayesha's code, Omar's account
    assert can_log_in(PASSWORD, "omar@example.com")


def test_weak_new_password_is_refused(client: TestClient, inbox) -> None:  # same rules as sign-up
    ask_code(TestClient(app))
    assert reset(TestClient(app), code_in(inbox[0]), password="password123").status_code == 422
    assert reset(TestClient(app), code_in(inbox[0]), password="short").status_code == 422


def test_code_must_be_six_digits(client: TestClient, inbox) -> None:
    for bad in ("12345", "1234567", "abcdef", "12 345", "' OR 1=1"):
        assert reset(TestClient(app), bad).status_code == 422


def test_no_mail_bombing(client: TestClient, inbox) -> None:  # 3 codes an hour per email
    codes = [ask_code(TestClient(app)).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    assert len(inbox) == 3


def test_reset_unlocks_a_locked_account(client: TestClient, inbox) -> None:  # forgot password AND locked out by wrong tries
    anon = TestClient(app)
    for _ in range(10):
        anon.post("/auth/login", data={"username": "ayesha@example.com", "password": "wrong-guess-1"})
    assert not can_log_in(PASSWORD)  # locked for 15 minutes
    ask_code(anon)
    assert reset(anon, code_in(inbox[0])).status_code == 200
    assert can_log_in(NEW)  # unlocked straight away


def test_no_email_setup_says_so(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BREVO_API_KEY", raising=False)
    assert ask_code(TestClient(app)).status_code == 503


def test_html_in_email_is_only_the_code(client: TestClient, inbox) -> None:
    ask_code(TestClient(app))
    assert "<script" not in inbox[0]["html"] and code_in(inbox[0]) in inbox[0]["html"]
