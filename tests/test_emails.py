from datetime import datetime, timezone  # moments

import pytest  # the testing tool
from fastapi.testclient import TestClient  # the fake browser type

from app import clock, mailer  # the clock we freeze and the email code we test
from app.database import SessionLocal  # to run one round of the email job

PKT = clock.LOCAL_TZ  # Pakistan time


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch):  # a fake Brevo: emails land in this list instead of the internet
    sent: list[dict] = []
    state = {"now": datetime(2026, 11, 16, 6, 0, tzinfo=PKT).astimezone(timezone.utc), "fail": False}
    monkeypatch.setattr(clock, "utc_now", lambda: state["now"])  # frozen clock
    def fake_send(to, subject, html_body, text_body):
        if state["fail"]:
            return False  # pretend Brevo is down
        sent.append({"to": to, "subject": subject, "html": html_body})
        return True
    def run_at(hour: int, minute: int = 0) -> int:  # move the clock, then run one round of the job
        state["now"] = datetime(2026, 11, 16, hour, minute, tzinfo=PKT).astimezone(timezone.utc)
        with SessionLocal() as db:
            return mailer.send_due_emails(db, send=fake_send)
    return {"sent": sent, "run_at": run_at, "state": state}


def gym_at_8(client: TestClient) -> int:
    return client.post("/tasks", json={"title": "Gym", "due_date": "2026-11-16", "due_time": "20:00"}).json()["id"]


def test_switch_is_off_by_default(client: TestClient, outbox) -> None:
    assert client.get("/auth/me").json()["email_reminders"] is False  # nobody gets emails they didn't ask for
    gym_at_8(client)
    outbox["run_at"](19, 1)
    assert outbox["sent"] == []


def test_email_goes_to_my_own_address(client: TestClient, outbox) -> None:
    assert client.patch("/auth/me", json={"email_reminders": True}).json()["email_reminders"] is True  # switch it on
    gym_at_8(client)
    assert outbox["run_at"](19, 1) == 1
    assert outbox["sent"][0]["to"] == "ayesha@example.com"  # only ever the account's own email
    assert outbox["sent"][0]["subject"] == "⏰ Gym at 8:00 PM, in 1 hour"
    assert outbox["run_at"](19, 2) == 0  # never the same reminder twice


def test_one_email_per_task_and_none_when_done(client: TestClient, outbox) -> None:
    client.patch("/auth/me", json={"email_reminders": True})
    task_id = gym_at_8(client)
    outbox["run_at"](20, 1)  # server was off at 7: both "in 1 hour" and "now" are due
    assert [e["subject"] for e in outbox["sent"]] == ["🔔 Gym is now (8:00 PM)"]  # only the newest
    client.patch(f"/tasks/{task_id}", json={"status": "done"})
    outbox["run_at"](21, 1)
    assert len(outbox["sent"]) == 1  # no "did you finish?" because I did


def test_titles_are_escaped_in_the_email(client: TestClient, outbox) -> None:
    client.patch("/auth/me", json={"email_reminders": True})
    client.post("/tasks", json={"title": "<script>alert(1)</script>", "due_date": "2026-11-16", "due_time": "20:00"})
    outbox["run_at"](19, 1)
    assert "<script>" not in outbox["sent"][0]["html"]  # HTML in a title can't run inside the email
    assert "&lt;script&gt;" in outbox["sent"][0]["html"]


def test_failed_send_is_retried(client: TestClient, outbox) -> None:
    client.patch("/auth/me", json={"email_reminders": True})
    gym_at_8(client)
    outbox["state"]["fail"] = True
    assert outbox["run_at"](19, 1) == 0  # Brevo down
    outbox["state"]["fail"] = False
    assert outbox["run_at"](19, 2) == 1  # next minute: it goes out


def test_daily_cap(client: TestClient, outbox, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mailer, "DAILY_CAP", 2)
    client.patch("/auth/me", json={"email_reminders": True})
    for title in ["A", "B", "C"]:
        client.post("/tasks", json={"title": title, "due_date": "2026-11-16", "due_time": "20:00"})
    outbox["run_at"](19, 1)
    assert len(outbox["sent"]) == 2  # capped


def test_other_users_switch_is_theirs(client: TestClient, other_user: TestClient, outbox) -> None:
    other_user.patch("/auth/me", json={"email_reminders": True})  # Omar turns emails ON...
    gym_at_8(client)  # ...but this is Ayesha's task, and her switch is off
    outbox["run_at"](19, 1)
    assert outbox["sent"] == []


def test_settings_only_accepts_the_switch(client: TestClient) -> None:
    assert client.patch("/auth/me", json={"email_reminders": True, "email": "hacker@evil.com"}).status_code == 422  # no sneaky fields
    assert client.get("/auth/me").json()["email"] == "ayesha@example.com"


def test_test_email_needs_setup(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BREVO_API_KEY", raising=False)
    assert client.post("/auth/me/test-email").status_code == 503  # no key on the server: a clear message, no crash


def test_settings_need_login(anon: TestClient) -> None:
    assert anon.patch("/auth/me", json={"email_reminders": True}).status_code == 401
    assert anon.post("/auth/me/test-email").status_code == 401
