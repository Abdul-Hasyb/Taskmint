import pytest  # the testing tool
from fastapi.testclient import TestClient  # the fake browser type

from app import ai  # the Gemini helper we're going to replace with a fake
from app.ai import AIPlan, AITask  # the shapes a real Gemini answer has

MESSAGE = "Salam bhai, kal tak 60 sec reel bhej dena. Aur thumbnail bhi bana dena please"  # a typical client message


def fake_ai(monkeypatch: pytest.MonkeyPatch, *tasks: AITask) -> None:  # make ai.ask_ai return a fixed answer, no internet, no quota used
    monkeypatch.setattr(ai, "ask_ai", lambda message, clients: AIPlan(tasks=list(tasks)))  # swap in a fake for this test only


def test_propose_returns_tasks_with_source_quotes(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ai(monkeypatch,  # the AI "answers" with two good tasks
        AITask(title="Edit 60s reel", description="Due tomorrow", client_id=None, source_quote="kal tak 60 sec reel bhej dena"),
        AITask(title="Design thumbnail", description=None, client_id=None, source_quote="thumbnail bhi bana dena"))
    response = client.post("/planner/propose", json={"message": MESSAGE})  # ask the planner
    assert response.status_code == 200  # worked
    body = response.json()  # the answer
    assert [t["title"] for t in body["tasks"]] == ["Edit 60s reel", "Design thumbnail"]  # both kept
    assert body["dropped"] == 0  # nothing thrown away
    assert client.get("/tasks").json() == []  # NOTHING was saved: proposals only


def test_drops_tasks_with_made_up_quotes(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # the anti-hallucination check
    fake_ai(monkeypatch,
        AITask(title="Edit 60s reel", description=None, client_id=None, source_quote="60 sec reel"),  # real quote
        AITask(title="Send invoice", description=None, client_id=None, source_quote="please send the invoice"))  # NOT in the message
    body = client.post("/planner/propose", json={"message": MESSAGE}).json()  # ask the planner
    assert [t["title"] for t in body["tasks"]] == ["Edit 60s reel"]  # the invented task is gone
    assert body["dropped"] == 1  # and it's counted


def test_unknown_client_from_ai_is_removed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # the AI can't invent clients
    bilal = client.post("/clients", json={"name": "Bilal"}).json()["id"]  # a real client
    fake_ai(monkeypatch,
        AITask(title="Edit reel", description=None, client_id=bilal, source_quote="reel"),  # real client: kept
        AITask(title="Thumbnail", description=None, client_id=999, source_quote="thumbnail"))  # fake client: removed
    tasks = client.post("/planner/propose", json={"message": MESSAGE}).json()["tasks"]  # ask the planner
    assert [t["client_id"] for t in tasks] == [bilal, None]  # 999 became None


def test_approve_saves_chosen_tasks(client: TestClient) -> None:  # approving saves exactly what the user sends
    response = client.post("/planner/approve", json={"tasks": [{"title": "Edit 60s reel"}, {"title": "Design thumbnail"}]})
    assert response.status_code == 201  # created
    assert [t["title"] for t in client.get("/tasks").json()] == ["Edit 60s reel", "Design thumbnail"]  # both saved


def test_approve_is_all_or_nothing(client: TestClient) -> None:  # one bad task stops the whole batch
    response = client.post("/planner/approve", json={"tasks": [{"title": "Good task"}, {"title": "Bad", "client_id": 999}]})
    assert response.status_code == 422  # rejected
    assert client.get("/tasks").json() == []  # and NOT even the good one was saved


def test_ai_down_returns_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # the AI fails: a clean error, no crash
    def broken(message, clients):  # a fake AI that always fails
        raise ai.PlannerUnavailable("down")  # like Gemini being unreachable
    monkeypatch.setattr(ai, "ask_ai", broken)  # swap it in
    response = client.post("/planner/propose", json={"message": MESSAGE})  # ask the planner
    assert response.status_code == 503  # Service Unavailable
    assert response.json() == {"detail": "AI planner is unavailable right now."}  # safe message, no secrets


def test_ai_rate_limited_returns_429(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # free quota used up
    def limited(message, clients):  # a fake AI that's out of quota
        raise ai.PlannerRateLimited()  # like Gemini answering 429
    monkeypatch.setattr(ai, "ask_ai", limited)  # swap it in
    assert client.post("/planner/propose", json={"message": MESSAGE}).status_code == 429  # passed on as 429


def test_missing_key_returns_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # no key in .env: clear error, no call made
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)  # pretend .env has no key
    assert client.post("/planner/propose", json={"message": MESSAGE}).status_code == 503  # unavailable


# ---- Security tests ----

def test_rejects_huge_message(client: TestClient) -> None:  # stops someone burning our AI quota with a huge message
    assert client.post("/planner/propose", json={"message": "x" * 4001}).status_code == 422  # one over the limit


def test_rejects_too_many_tasks_on_approve(client: TestClient) -> None:  # stops someone saving hundreds of tasks in one go
    tasks = [{"title": f"Task {n}"} for n in range(11)]  # 11 tasks
    assert client.post("/planner/approve", json={"tasks": tasks}).status_code == 422  # max is 10