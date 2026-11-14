import pytest  # the testing tool
from fastapi.testclient import TestClient  # the fake browser type

from app import ai  # the Gemini helper we replace with a fake
from app.ai import AIPlan  # the shape of a Gemini answer
from app.routers import planner  # to lower the daily limit just for these tests

MESSAGE = {"message": "kal tak reel bhej dena"}  # any valid message


@pytest.fixture  # setup that each test below asks for by name
def tiny_limit(monkeypatch: pytest.MonkeyPatch) -> list[str]:  # limit = 2, and a fake AI that records each call
    calls: list[str] = []  # every message the fake AI receives
    monkeypatch.setattr(planner, "AI_DAILY_LIMIT", 2)  # only 2 requests a day in these tests
    monkeypatch.setattr(ai, "ask_ai", lambda message, clients: calls.append(message) or AIPlan(tasks=[]))  # fake AI: note the call, answer "no tasks"
    return calls  # the test can check how many times the AI was really called


def test_usage_starts_at_zero(client: TestClient, tiny_limit: list[str]) -> None:
    assert client.get("/planner/usage").json() == {"used": 0, "limit": 2, "remaining": 2}  # nothing used yet


def test_limit_blocks_and_ai_is_not_called(client: TestClient, tiny_limit: list[str]) -> None:
    assert client.post("/planner/propose", json=MESSAGE).status_code == 200  # 1st: allowed
    assert client.post("/planner/propose", json=MESSAGE).status_code == 200  # 2nd: allowed
    response = client.post("/planner/propose", json=MESSAGE)  # 3rd: over the limit
    assert response.status_code == 429  # refused
    assert "Daily AI limit reached" in response.json()["detail"]  # with a clear message
    assert len(tiny_limit) == 2  # Gemini was only called twice: the 3rd never cost anything
    assert client.get("/planner/usage").json() == {"used": 2, "limit": 2, "remaining": 0}  # counter is right


def test_limit_is_per_user(client: TestClient, other_user: TestClient, tiny_limit: list[str]) -> None:
    client.post("/planner/propose", json=MESSAGE)  # Ayesha uses both of hers
    client.post("/planner/propose", json=MESSAGE)
    assert client.post("/planner/propose", json=MESSAGE).status_code == 429  # Ayesha is blocked...
    assert other_user.post("/planner/propose", json=MESSAGE).status_code == 200  # ...but Omar still has his own 2


def test_failed_ai_call_still_counts(client: TestClient, monkeypatch: pytest.MonkeyPatch, tiny_limit: list[str]) -> None:
    def broken(message: str, clients: list) -> AIPlan:  # an AI that always fails
        raise ai.PlannerUnavailable()
    monkeypatch.setattr(ai, "ask_ai", broken)  # swap it in
    assert client.post("/planner/propose", json=MESSAGE).status_code == 503  # the AI failed...
    assert client.get("/planner/usage").json()["used"] == 1  # ...but it still counted (no free retries)


def test_bad_message_does_not_use_a_credit(client: TestClient, tiny_limit: list[str]) -> None:
    assert client.post("/planner/propose", json={"message": ""}).status_code == 422  # rejected at the door
    assert client.get("/planner/usage").json()["used"] == 0  # so nothing was counted


def test_usage_needs_login(anon: TestClient) -> None:
    assert anon.get("/planner/usage").status_code == 401  # no login, no answer
