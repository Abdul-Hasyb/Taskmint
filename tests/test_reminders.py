from datetime import datetime, timedelta, timezone  # moments and gaps

import pytest  # the testing tool
from fastapi.testclient import TestClient  # the fake browser type

from app import clock  # we "freeze" clock.utc_now so tests don't depend on the real time

PKT = clock.LOCAL_TZ  # Pakistan time (UTC+5)


@pytest.fixture
def frozen(monkeypatch: pytest.MonkeyPatch):  # a clock we can set and move
    state = {"now": datetime(2026, 11, 16, 6, 0, tzinfo=PKT).astimezone(timezone.utc)}  # Monday 16 Nov, 6:00 AM in Pakistan
    monkeypatch.setattr(clock, "utc_now", lambda: state["now"])  # everyone asking clock.utc_now() gets our time
    def move_to(hour: int, minute: int = 0, day: int = 16) -> None:  # jump to another Pakistan time
        state["now"] = datetime(2026, 11, day, hour, minute, tzinfo=PKT).astimezone(timezone.utc)
    return move_to


def upcoming_kinds(client: TestClient) -> list[str]:  # the waiting reminders, in order
    return [r["kind"] for r in client.get("/reminders/upcoming").json()]


def local_times(client: TestClient) -> list[str]:  # when they will pop up, in Pakistan time ("19:00")
    return [datetime.fromisoformat(r["send_at"]).astimezone(PKT).strftime("%H:%M") for r in client.get("/reminders/upcoming").json()]


def test_task_with_a_time_gets_before_at_after(client: TestClient, frozen) -> None:
    client.post("/tasks", json={"title": "Gym", "due_date": "2026-11-16", "due_time": "20:00"})  # gym at 8 PM today
    assert upcoming_kinds(client) == ["before", "at", "after"]
    assert local_times(client) == ["19:00", "20:00", "21:00"]  # 1 hour before, at, 1 hour after


def test_task_with_only_a_day_gets_morning_afternoon_evening(client: TestClient, frozen) -> None:
    client.post("/tasks", json={"title": "Submit assignment", "due_date": "2026-11-17"})  # tomorrow, no time
    assert local_times(client) == ["09:00", "14:00", "20:00"]


def test_task_with_no_day_counts_as_today(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    morning = datetime.now(PKT).replace(hour=6, minute=0, second=0, microsecond=0)  # 6 AM on the real today (the task's added "today")
    monkeypatch.setattr(clock, "utc_now", lambda: morning.astimezone(timezone.utc))
    client.post("/tasks", json={"title": "Read a book"})  # no date at all
    assert local_times(client) == ["09:00", "14:00", "20:00"]  # the 3 day reminders, on the day it was added


def test_past_reminders_are_skipped(client: TestClient, frozen) -> None:
    frozen(19, 30)  # it's already 7:30 PM
    client.post("/tasks", json={"title": "Gym", "due_date": "2026-11-16", "due_time": "20:00"})
    assert upcoming_kinds(client) == ["at", "after"]  # "1 hour before" (7 PM) has passed


def test_quiet_hours(client: TestClient, frozen) -> None:
    client.post("/tasks", json={"title": "Early flight", "due_date": "2026-11-17", "due_time": "08:30"})
    assert upcoming_kinds(client) == ["at", "after"]  # 7:30 AM is quiet time: no "before"
    client.post("/tasks", json={"title": "Late call", "due_date": "2026-11-16", "due_time": "23:30"})
    late = [r["kind"] for r in client.get("/reminders/upcoming").json() if datetime.fromisoformat(r["send_at"]).astimezone(PKT).hour == 23]
    assert late == ["at"]  # 11:30 PM: the time I picked still rings; 10:30 PM "before" is fine; 12:30 AM "after" is quiet


def test_done_stops_reminders_and_undo_brings_them_back(client: TestClient, frozen) -> None:
    task_id = client.post("/tasks", json={"title": "Gym", "due_date": "2026-11-16", "due_time": "20:00"}).json()["id"]
    client.patch(f"/tasks/{task_id}", json={"status": "done"})
    assert upcoming_kinds(client) == []  # finished: nothing left
    client.patch(f"/tasks/{task_id}", json={"status": "todo"})
    assert upcoming_kinds(client) == ["before", "at", "after"]  # un-ticked: back again


def test_changing_the_time_moves_the_reminders(client: TestClient, frozen) -> None:
    task_id = client.post("/tasks", json={"title": "Gym", "due_date": "2026-11-16", "due_time": "20:00"}).json()["id"]
    client.patch(f"/tasks/{task_id}", json={"due_time": "18:00"})
    assert local_times(client) == ["17:00", "18:00", "19:00"]


def test_due_reminder_pops_up_once(client: TestClient, frozen) -> None:
    client.post("/tasks", json={"title": "Gym", "due_date": "2026-11-16", "due_time": "20:00"})
    assert client.get("/reminders/due").json() == []  # 6 AM: nothing yet
    frozen(19, 1)  # 7:01 PM
    due = client.get("/reminders/due").json()
    assert [r["kind"] for r in due] == ["before"]
    assert due[0]["message"] == "⏰ Gym at 8:00 PM, in 1 hour"  # ready-to-show text
    assert client.get("/reminders/due").json() == []  # already shown: never twice


def test_after_reminder_skipped_if_done(client: TestClient, frozen) -> None:
    task_id = client.post("/tasks", json={"title": "Gym", "due_date": "2026-11-16", "due_time": "20:00"}).json()["id"]
    frozen(20, 1)
    assert [r["kind"] for r in client.get("/reminders/due").json()] == ["at"]  # "in 1 hour" AND "now" are both due: only the newest shows
    client.patch(f"/tasks/{task_id}", json={"status": "done"})  # finished at 8:01
    frozen(21, 1)
    assert client.get("/reminders/due").json() == []  # no "did you finish?" because I did


def test_old_missed_reminders_are_not_shown_late(client: TestClient, frozen) -> None:
    client.post("/tasks", json={"title": "Gym", "due_date": "2026-11-16", "due_time": "10:00"})
    frozen(18, 0)  # laptop was off all day; it's 6 PM now
    assert client.get("/reminders/due").json() == []  # 9, 10 and 11 AM are hours old: skipped, not dumped on screen


def test_reminders_are_private(client: TestClient, other_user: TestClient, frozen) -> None:
    client.post("/tasks", json={"title": "Gym", "due_date": "2026-11-16", "due_time": "20:00"})
    frozen(19, 1)
    assert other_user.get("/reminders/due").json() == []  # Omar never sees Ayesha's reminders
    assert other_user.get("/reminders/upcoming").json() == []


def test_deleting_a_task_deletes_its_reminders(client: TestClient, frozen) -> None:
    task_id = client.post("/tasks", json={"title": "Gym", "due_date": "2026-11-16", "due_time": "20:00"}).json()["id"]
    assert client.delete(f"/tasks/{task_id}").status_code == 204
    assert client.get("/reminders/upcoming").json() == []


def test_reminders_need_login(anon: TestClient) -> None:
    assert anon.get("/reminders/due").status_code == 401
    assert anon.get("/reminders/upcoming").status_code == 401


def test_snooze(client: TestClient, other_user: TestClient, frozen) -> None:
    task_id = client.post("/tasks", json={"title": "Gym", "due_date": "2026-11-16", "due_time": "20:00"}).json()["id"]
    frozen(20, 0)
    client.get("/reminders/due")  # the 8 PM one shows
    assert client.post("/reminders/snooze", json={"task_id": task_id, "minutes": 10}).status_code == 201  # "remind me in 10 min"
    frozen(20, 11)
    due = client.get("/reminders/due").json()
    assert [r["kind"] for r in due] == ["snooze"] and due[0]["message"] == "🔁 Gym (snoozed)"
    assert client.post("/reminders/snooze", json={"task_id": task_id, "minutes": 1}).status_code == 422  # too short
    assert client.post("/reminders/snooze", json={"task_id": task_id, "minutes": 9999}).status_code == 422  # too long
    assert other_user.post("/reminders/snooze", json={"task_id": task_id}).status_code == 404  # not Omar's task


def test_done_cancels_snooze(client: TestClient, frozen) -> None:
    task_id = client.post("/tasks", json={"title": "Gym", "due_date": "2026-11-16", "due_time": "20:00"}).json()["id"]
    client.post("/reminders/snooze", json={"task_id": task_id, "minutes": 30})
    client.patch(f"/tasks/{task_id}", json={"status": "done"})
    assert upcoming_kinds(client) == []  # finished: the snooze is gone too
