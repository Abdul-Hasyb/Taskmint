import pytest  # the testing tool
from fastapi.testclient import TestClient  # sends fake requests to our app, no server needed

from app import main  # our app's code


@pytest.fixture(autouse=True)  # runs automatically before EVERY test
def reset_storage() -> None:  # give each test a clean, empty app
    main.tasks.clear()  # remove all tasks left over from the previous test
    main.next_id = 1  # restart the id counter


@pytest.fixture  # a helper that tests can ask for by name
def client() -> TestClient:  # hand each test a fake browser pointed at our app
    return TestClient(main.app)  # the test client