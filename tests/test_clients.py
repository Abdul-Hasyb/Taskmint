from fastapi.testclient import TestClient  # the fake browser type, used in type hints


def make_client(client: TestClient, name: str = "Bilal") -> int:  # helper: create a client and return its id
    response = client.post("/clients", json={"name": name})  # create it
    assert response.status_code == 201  # it must work
    return response.json()["id"]  # hand back the new id


def test_create_and_list_clients(client: TestClient) -> None:  # clients can be created and listed
    response = client.post("/clients", json={"name": "  Sara  ", "notes": "Podcast edits"})  # spaces on purpose
    assert response.status_code == 201  # created
    assert response.json()["name"] == "Sara"  # spaces trimmed
    assert response.json()["open_tasks"] == 0  # no tasks yet
    make_client(client, "Bilal")  # a second client
    names = [c["name"] for c in client.get("/clients").json()]  # list them
    assert names == ["Bilal", "Sara"]  # sorted by name


def test_task_belongs_to_client(client: TestClient) -> None:  # a task can be linked to a client
    bilal = make_client(client)  # create Bilal
    response = client.post("/tasks", json={"title": "60s reel", "client_id": bilal})  # task for Bilal
    assert response.status_code == 201  # created
    assert response.json()["client_id"] == bilal  # linked
    assert len(client.get(f"/clients/{bilal}/tasks").json()) == 1  # shows on Bilal's page


def test_open_tasks_count(client: TestClient) -> None:  # the client page counts unfinished work
    bilal = make_client(client)  # create Bilal
    for title in ["Reel 1", "Reel 2", "Thumbnail"]:  # three tasks
        client.post("/tasks", json={"title": title, "client_id": bilal})  # ids 1, 2, 3
    client.patch("/tasks/1", json={"status": "done"})  # finish one
    assert client.get(f"/clients/{bilal}").json()["open_tasks"] == 2  # two still open


def test_filter_tasks_by_status_and_client(client: TestClient) -> None:  # GET /tasks?status=...&client_id=...
    bilal, sara = make_client(client, "Bilal"), make_client(client, "Sara")  # two clients
    client.post("/tasks", json={"title": "Bilal reel", "client_id": bilal})  # task 1
    client.post("/tasks", json={"title": "Sara podcast", "client_id": sara})  # task 2
    client.patch("/tasks/2", json={"status": "done"})  # Sara's is done
    assert [t["title"] for t in client.get(f"/tasks?client_id={sara}").json()] == ["Sara podcast"]  # only Sara's
    assert [t["title"] for t in client.get("/tasks?status=todo").json()] == ["Bilal reel"]  # only unfinished


def test_move_and_unlink_task(client: TestClient) -> None:  # PATCH can change or remove a task's client
    bilal, sara = make_client(client, "Bilal"), make_client(client, "Sara")  # two clients
    client.post("/tasks", json={"title": "Reel", "client_id": bilal})  # task 1 for Bilal
    assert client.patch("/tasks/1", json={"client_id": sara}).json()["client_id"] == sara  # moved to Sara
    assert client.patch("/tasks/1", json={"client_id": None}).json()["client_id"] is None  # no client now


def test_deleting_client_keeps_tasks(client: TestClient) -> None:  # deleting a client must not delete their work
    bilal = make_client(client)  # create Bilal
    client.post("/tasks", json={"title": "Reel", "client_id": bilal})  # task 1
    assert client.delete(f"/clients/{bilal}").status_code == 204  # client deleted
    task = client.get("/tasks/1").json()  # the task...
    assert task["title"] == "Reel" and task["client_id"] is None  # ...still exists, just without a client


def test_missing_client_returns_404(client: TestClient) -> None:  # asking for a client that doesn't exist
    assert client.get("/clients/99").status_code == 404  # no client 99
    assert client.get("/clients/99/tasks").status_code == 404  # no page for client 99 either


# ---- Security tests ----

def test_rejects_task_for_fake_client(client: TestClient) -> None:  # can't link a task to a client that doesn't exist
    response = client.post("/tasks", json={"title": "Reel", "client_id": 999})  # client 999 doesn't exist
    assert response.status_code == 422  # rejected
    assert response.json()["detail"] == "Client 999 does not exist"  # with a clear message


def test_rejects_bad_client_input(client: TestClient) -> None:  # empty, huge or faked client data
    assert client.post("/clients", json={"name": "   "}).status_code == 422  # only spaces
    assert client.post("/clients", json={"name": "x" * 101}).status_code == 422  # too long
    assert client.post("/clients", json={"name": "Bilal", "id": 5}).status_code == 422  # faking the id
    assert client.post("/clients", json={"name": "Bilal", "open_tasks": 0}).status_code == 422  # faking a calculated field