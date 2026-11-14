import pytest  # the testing tool
from fastapi.testclient import TestClient  # the fake browser type

from app import ai  # the Gemini helper we replace with a fake
from app.ai import AIPlan, AITask  # the shapes a Gemini answer has


def add_person(client: TestClient, name: str) -> int:  # put someone on my People list, return their id
    return client.post("/clients", json={"name": name}).json()["id"]


def test_assign_a_task(client: TestClient) -> None:
    bilal = add_person(client, "Bilal")
    task = client.post("/tasks", json={"title": "Edit reel", "assignee_id": bilal}).json()  # Bilal does it
    assert task["assignee_id"] == bilal


def test_filter_by_assignee(client: TestClient) -> None:
    bilal, ahmad = add_person(client, "Bilal"), add_person(client, "Ahmad")
    client.post("/tasks", json={"title": "Edit reel", "assignee_id": bilal})
    client.post("/tasks", json={"title": "Thumbnail", "assignee_id": ahmad})
    client.post("/tasks", json={"title": "My own task"})  # nobody = me
    assert [t["title"] for t in client.get(f"/tasks?assignee_id={ahmad}").json()] == ["Thumbnail"]  # only Ahmad's work


def test_reassign_and_take_back(client: TestClient) -> None:
    bilal, ahmad = add_person(client, "Bilal"), add_person(client, "Ahmad")
    task_id = client.post("/tasks", json={"title": "Edit reel", "assignee_id": bilal}).json()["id"]
    assert client.patch(f"/tasks/{task_id}", json={"assignee_id": ahmad}).json()["assignee_id"] == ahmad  # give it to Ahmad
    assert client.patch(f"/tasks/{task_id}", json={"assignee_id": None}).json()["assignee_id"] is None  # take it back myself


def test_cannot_assign_to_someone_not_on_my_list(client: TestClient, other_user: TestClient) -> None:
    omars_person = other_user.post("/clients", json={"name": "Sara"}).json()["id"]  # on ANOTHER user's list
    assert client.post("/tasks", json={"title": "x", "assignee_id": omars_person}).status_code == 422  # not mine: refused
    assert client.post("/tasks", json={"title": "x", "assignee_id": 999}).status_code == 422  # doesn't exist: refused
    task_id = client.post("/tasks", json={"title": "x"}).json()["id"]
    assert client.patch(f"/tasks/{task_id}", json={"assignee_id": omars_person}).status_code == 422


def test_removing_a_person_gives_their_tasks_back_to_me(client: TestClient) -> None:
    bilal = add_person(client, "Bilal")
    task_id = client.post("/tasks", json={"title": "Edit reel", "assignee_id": bilal}).json()["id"]
    client.delete(f"/clients/{bilal}")  # Bilal leaves the list
    assert client.get(f"/tasks/{task_id}").json()["assignee_id"] is None  # the task is kept, and it's mine again


def test_planner_assigns_work_to_people(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    bilal, ahmad = add_person(client, "Bilal"), add_person(client, "Ahmad")
    monkeypatch.setattr(ai, "ask_ai", lambda message, clients: AIPlan(tasks=[
        AITask(title="Edit reel", description=None, client_id=None, assignee_id=bilal, source_quote="Bilal reel edit karega"),
        AITask(title="Make thumbnail", description=None, client_id=None, assignee_id=ahmad, source_quote="Ahmad thumbnail banaye ga"),
        AITask(title="Invented", description=None, client_id=None, assignee_id=999, source_quote="kal tak"),  # someone not on my list
    ]))
    tasks = client.post("/planner/propose", json={"message": "Bilal reel edit karega, Ahmad thumbnail banaye ga kal tak"}).json()["tasks"]
    assert [t["assignee_id"] for t in tasks] == [bilal, ahmad, None]  # real people kept; the unknown id becomes "me"
    saved = client.post("/planner/approve", json={"tasks": [{k: t[k] for k in ("title", "description", "client_id", "assignee_id", "due_date", "due_time")} for t in tasks]}).json()
    assert [t["assignee_id"] for t in saved] == [bilal, ahmad, None]  # and saved that way


def test_approve_refuses_someone_elses_person(client: TestClient, other_user: TestClient) -> None:
    omars_person = other_user.post("/clients", json={"name": "Sara"}).json()["id"]
    assert client.post("/planner/approve", json={"tasks": [{"title": "x", "assignee_id": omars_person}]}).status_code == 422
