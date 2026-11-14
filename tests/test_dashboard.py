from fastapi.testclient import TestClient  # the fake browser type


def test_dashboard_page_is_served(anon: TestClient) -> None:  # the page itself needs no login (it shows the login form)
    response = anon.get("/")  # open the home page
    assert response.status_code == 200  # it loads
    assert "text/html" in response.headers["content-type"]  # it's a web page
    assert "Taskmint" in response.text  # and it's ours


def test_api_still_works_next_to_the_page(anon: TestClient) -> None:  # the page must not hide the API
    assert anon.get("/health").json() == {"status": "ok"}  # health still answers
    assert anon.get("/tasks").status_code == 401  # API still needs login
    assert anon.get("/docs").status_code == 200  # /docs still there
