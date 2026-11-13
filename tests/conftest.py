import os  # lets us set environment variables

os.environ["DATABASE_URL"] = "sqlite://"  # tests use a throwaway in-memory database, NEVER the real Supabase one (must run before importing the app)

import pytest  # the testing tool  # noqa: E402 (imports after the line above on purpose)
from fastapi.testclient import TestClient  # sends fake requests to our app, no server needed  # noqa: E402

from app.database import Base, engine  # the test database connection and table definitions  # noqa: E402
from app.main import app  # our app  # noqa: E402


@pytest.fixture(autouse=True)  # runs automatically before EVERY test
def fresh_database():  # give each test a clean, empty database
    Base.metadata.create_all(engine)  # create the tables
    yield  # the test runs here
    Base.metadata.drop_all(engine)  # delete the tables afterwards, so the next test starts empty


@pytest.fixture  # a helper that tests can ask for by name
def client() -> TestClient:  # hand each test a fake browser pointed at our app
    return TestClient(app)  # the test client