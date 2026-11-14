import pytest  # the testing tool
from fastapi.testclient import TestClient  # the fake browser type

from app import ai  # the Gemini helper we replace with a fake
from app.ai import AIPlan, AITask  # the shapes a Gemini answer has
from app.clock import local_today  # today on the users' clock


def test_task_with_due_date_and_time(client: TestClient) -> None:
    task = client.post("/tasks", json={"title": "Gym", "due_date": "2026-11-16", "due_time": "20:00"}).json()  # create it
    assert task["due_date"] == "2026-11-16"  # the day is saved
    assert task["due_time"] == "20:00:00"  # the time is saved


def test_due_is_optional(client: TestClient) -> None:
    task = client.post("/tasks", json={"title": "Read a book"}).json()  # no due date at all
    assert task["due_date"] is None and task["due_time"] is None  # fine


def test_time_without_day_is_rejected(client: TestClient) -> None:
    assert client.post("/tasks", json={"title": "Gym", "due_time": "20:00"}).status_code == 422  # "8 PM" of which day?


def test_bad_dates_are_rejected(client: TestClient) -> None:
    assert client.post("/tasks", json={"title": "Gym", "due_date": "2026-02-30"}).status_code == 422  # no 30th of February
    assert client.post("/tasks", json={"title": "Gym", "due_date": "kal"}).status_code == 422  # not a date
    assert client.post("/tasks", json={"title": "Gym", "due_date": "2026-11-16", "due_time": "25:00"}).status_code == 422  # no 25 o'clock


def test_update_due_and_remove_it(client: TestClient) -> None:
    task_id = client.post("/tasks", json={"title": "Gym"}).json()["id"]  # a task with no due date
    changed = client.patch(f"/tasks/{task_id}", json={"due_date": "2026-11-16", "due_time": "07:30"}).json()  # give it one
    assert (changed["due_date"], changed["due_time"]) == ("2026-11-16", "07:30:00")
    cleared = client.patch(f"/tasks/{task_id}", json={"due_date": None}).json()  # remove the day...
    assert (cleared["due_date"], cleared["due_time"]) == (None, None)  # ...and the time goes with it


def test_update_time_without_day_is_rejected(client: TestClient) -> None:
    task_id = client.post("/tasks", json={"title": "Gym"}).json()["id"]  # no due date
    assert client.patch(f"/tasks/{task_id}", json={"due_time": "20:00"}).status_code == 422  # a time with no day
    assert client.get(f"/tasks/{task_id}").json()["due_time"] is None  # nothing was saved


def fake_ai(monkeypatch: pytest.MonkeyPatch, *tasks: AITask) -> None:  # make the AI answer with fixed tasks
    monkeypatch.setattr(ai, "ask_ai", lambda message, clients: AIPlan(tasks=list(tasks)))


def test_planner_passes_due_dates_through(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ai(monkeypatch, AITask(title="Go to the gym", description=None, client_id=None, due_date="2026-11-16", due_time="20:00", source_quote="kal 8 baje gym"))
    task = client.post("/planner/propose", json={"message": "kal 8 baje gym jana ha"}).json()["tasks"][0]  # ask the planner
    assert (task["due_date"], task["due_time"]) == ("2026-11-16", "20:00:00")  # the AI's day and time came through
    saved = client.post("/planner/approve", json={"tasks": [{k: task[k] for k in ("title", "description", "client_id", "due_date", "due_time")}]}).json()[0]  # approve it
    assert (saved["due_date"], saved["due_time"]) == ("2026-11-16", "20:00:00")  # and they were saved


def test_planner_ignores_nonsense_dates(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ai(monkeypatch, AITask(title="Go to the gym", description=None, client_id=None, due_date="kal", due_time="25:99", source_quote="gym"))
    task = client.post("/planner/propose", json={"message": "gym jana ha"}).json()["tasks"][0]  # the AI sent rubbish dates
    assert (task["due_date"], task["due_time"]) == (None, None)  # ignored, no crash, task still kept


def test_planner_time_without_day_means_today(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ai(monkeypatch, AITask(title="Call mom", description=None, client_id=None, due_date=None, due_time="21:00", source_quote="9 baje call"))
    task = client.post("/planner/propose", json={"message": "9 baje call karni ha"}).json()["tasks"][0]
    assert task["due_date"] == local_today().isoformat()  # "9 baje" alone = today


def test_completed_at_is_set_and_cleared(client: TestClient) -> None:  # the charts need to know WHEN a task was finished
    task_id = client.post("/tasks", json={"title": "Gym"}).json()["id"]
    assert client.get(f"/tasks/{task_id}").json()["completed_at"] is None  # not done yet
    done = client.patch(f"/tasks/{task_id}", json={"status": "done"}).json()
    assert done["completed_at"] is not None  # ticked: the time is saved
    again = client.patch(f"/tasks/{task_id}", json={"title": "Gym (legs)"}).json()  # editing the title...
    assert again["completed_at"] == done["completed_at"]  # ...doesn't change when it was finished
    undone = client.patch(f"/tasks/{task_id}", json={"status": "todo"}).json()
    assert undone["completed_at"] is None  # un-ticked: cleared
