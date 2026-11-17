from fastapi.testclient import TestClient  # a fake browser

from app.main import app  # our app

NEW_USER = {"password": "correct-horse-battery"}  # every sign-up below uses this password


def sign_ups(headers_for) -> list[int]:  # try 6 sign-ups, each with its own headers; return the status codes
    browser = TestClient(app)
    return [browser.post("/auth/register", json={"email": f"bot{n}@example.com", **NEW_USER}, headers=headers_for(n)).status_code for n in range(6)]


def test_fake_forwarded_for_does_not_dodge_the_limit():  # an attacker writes a new fake IP on every request
    codes = sign_ups(lambda n: {"X-Forwarded-For": f"9.9.9.{n}"})
    assert codes.count(201) == 5 and codes[-1] == 429  # we ignore X-Forwarded-For, so it's still the same visitor


def test_header_is_ignored_unless_we_turn_it_on():  # locally, nobody can pick their own IP with True-Client-IP
    codes = sign_ups(lambda n: {"True-Client-IP": f"9.9.9.{n}"})
    assert codes[-1] == 429


def test_live_header_tells_visitors_apart(monkeypatch):  # live on Render: Cloudflare's True-Client-IP is the real visitor
    monkeypatch.setenv("CLIENT_IP_HEADER", "True-Client-IP")
    codes = sign_ups(lambda n: {"True-Client-IP": f"9.9.9.{n}"})
    assert codes == [201] * 6  # six different people, so nobody is blocked


def test_live_header_still_limits_one_visitor(monkeypatch):
    monkeypatch.setenv("CLIENT_IP_HEADER", "True-Client-IP")
    codes = sign_ups(lambda n: {"True-Client-IP": "9.9.9.9"})
    assert codes.count(201) == 5 and codes[-1] == 429  # one person, still 5 an hour


def test_junk_in_the_header_is_ignored(monkeypatch):  # not an IP address: treated as if the header wasn't there
    monkeypatch.setenv("CLIENT_IP_HEADER", "True-Client-IP")
    codes = sign_ups(lambda n: {"True-Client-IP": f"not-an-ip-{n}"})
    assert codes[-1] == 429
