import os  # lets us set environment variables

os.environ["DATABASE_URL"] = "sqlite://"  # tests use a throwaway in-memory database, NEVER the real Supabase one (must run before importing the app)
os.environ["JWT_SECRET"] = "test-secret-only-for-tests-at-least-32-characters"  # a fake signing secret, only for tests

import pytest  # the testing tool  # noqa: E402 (imports after the lines above on purpose)
from fastapi.testclient import TestClient  # sends fake requests to our app, no server needed  # noqa: E402

from app.database import Base, engine  # the test database connection and table definitions  # noqa: E402
from app.main import app  # our app  # noqa: E402

PASSWORD = "correct-horse-battery"  # the password every test user gets


@pytest.fixture(autouse=True)  # runs automatically before EVERY test
def fresh_database():  # give each test a clean, empty database
    Base.metadata.create_all(engine)  # create the tables
    yield  # the test runs here
    Base.metadata.drop_all(engine)  # delete the tables afterwards, so the next test starts empty


def logged_in_as(email: str) -> TestClient:  # register an account, log in, and return a fake browser that sends its token
    browser = TestClient(app)  # a fresh fake browser
    assert browser.post("/auth/register", json={"email": email, "password": PASSWORD}).status_code == 201  # make the account
    token = browser.post("/auth/login", data={"username": email, "password": PASSWORD}).json()["access_token"]  # log in
    browser.headers["Authorization"] = f"Bearer {token}"  # send the token with every request from now on
    return browser  # ready to use


@pytest.fixture  # a helper that tests can ask for by name
def client() -> TestClient:  # the default fake browser: already logged in as Ayesha
    return logged_in_as("ayesha@example.com")  # so the older tests keep working unchanged


@pytest.fixture  # a second, separate user
def other_user() -> TestClient:  # logged in as Omar, to prove users can't see each other's data
    return logged_in_as("omar@example.com")  # a different account


@pytest.fixture  # a browser that is NOT logged in
def anon() -> TestClient:  # no token at all
    return TestClient(app)  # plain fake browser