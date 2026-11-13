from fastapi.testclient import TestClient  # the fake browser type, used in type hints


def test_health(client: TestClient) -> None:  # the app says it's alive
    response = client.get("/health")  # send GET /health
    assert response.status_code == 200  # assert = "this must be true, or the test fails"
    assert response.json() == {"status": "ok"}  # the body is exactly this JSON


def test_create_task(client: TestClient) -> None:  # creating a task works and the server sets id/status
    response = client.post("/tasks", json={"title": "  Edit client reel  "})  # spaces around the title on purpose
    assert response.status_code == 201  # 201 Created
    task = response.json()  # turn the JSON body into a Python dict
    assert task["id"] == 1  # first task gets id 1
    assert task["title"] == "Edit client reel"  # spaces were trimmed
    assert task["status"] == "todo"  # every new task starts as todo


def test_list_and_get_task(client: TestClient) -> None:  # tasks can be listed and fetched one by one
    client.post("/tasks", json={"title": "First"})  # create task 1
    client.post("/tasks", json={"title": "Second"})  # create task 2
    assert len(client.get("/tasks").json()) == 2  # the list has 2 tasks
    response = client.get("/tasks/2")  # fetch task 2
    assert response.status_code == 200  # found
    assert response.json()["title"] == "Second"  # the right task came back


def test_get_missing_task_returns_404(client: TestClient) -> None:  # asking for a task that doesn't exist
    response = client.get("/tasks/99")  # there is no task 99
    assert response.status_code == 404  # 404 Not Found
    assert response.json() == {"detail": "Task not found"}  # with a clear message


def test_update_task_status(client: TestClient) -> None:  # PATCH changes only what was sent
    client.post("/tasks", json={"title": "Edit client reel"})  # create task 1
    response = client.patch("/tasks/1", json={"status": "done"})  # change only the status
    assert response.status_code == 200  # OK
    assert response.json()["status"] == "done"  # status changed
    assert response.json()["title"] == "Edit client reel"  # title untouched


def test_delete_task(client: TestClient) -> None:  # deleting works, and deleting twice gives 404
    client.post("/tasks", json={"title": "Edit client reel"})  # create task 1
    assert client.delete("/tasks/1").status_code == 204  # deleted, nothing sent back
    assert client.get("/tasks/1").status_code == 404  # it's gone
    assert client.delete("/tasks/1").status_code == 404  # deleting again: not found


def test_ids_are_never_reused(client: TestClient) -> None:  # the Day 2 duplicate-id bug must never come back
    client.post("/tasks", json={"title": "One"})  # id 1
    client.post("/tasks", json={"title": "Two"})  # id 2
    client.delete("/tasks/2")  # delete id 2
    response = client.post("/tasks", json={"title": "Three"})  # create a new task
    assert response.json()["id"] == 3  # gets 3, not 2 again


# ---- Security tests: bad or malicious input must be rejected with 422 ----

def test_rejects_empty_title(client: TestClient) -> None:  # empty and spaces-only titles
    assert client.post("/tasks", json={"title": ""}).status_code == 422  # empty
    assert client.post("/tasks", json={"title": "   "}).status_code == 422  # only spaces


def test_rejects_huge_title(client: TestClient) -> None:  # someone trying to flood memory
    response = client.post("/tasks", json={"title": "x" * 201})  # one character over the limit
    assert response.status_code == 422  # rejected


def test_rejects_faked_server_fields(client: TestClient) -> None:  # users can't set id or status themselves
    response = client.post("/tasks", json={"title": "hack", "id": 999, "status": "done"})  # trying to fake fields
    assert response.status_code == 422  # rejected: extra fields are forbidden


def test_rejects_wrong_types(client: TestClient) -> None:  # wrong data types in body and URL
    assert client.post("/tasks", json={"title": 123}).status_code == 422  # number instead of text
    assert client.get("/tasks/abc").status_code == 422  # text instead of a number in the URL


def test_rejects_invalid_updates(client: TestClient) -> None:  # bad PATCH requests
    client.post("/tasks", json={"title": "Edit client reel"})  # create task 1
    assert client.patch("/tasks/1", json={}).status_code == 422  # nothing to update
    assert client.patch("/tasks/1", json={"status": "finished"}).status_code == 422  # not an allowed status
    assert client.patch("/tasks/1", json={"title": None}).status_code == 422  # title can't be removed