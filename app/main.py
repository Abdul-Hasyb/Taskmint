from pathlib import Path  # build file paths that work on Windows and Linux

from fastapi import FastAPI  # the core of our web app
from fastapi.staticfiles import StaticFiles  # serves plain files (our dashboard page) from a folder

from app.routers import auth, clients, planner, tasks  # the groups of endpoints, each in its own file

STATIC_DIR = Path(__file__).parent / "static"  # app/static, found next to this file (works from any folder)

app = FastAPI(title="Taskmint", version="0.6.0")  # create the app; tables are created by Alembic migrations, not here
app.include_router(auth.router)  # plug in /auth endpoints (register, login, me)
app.include_router(tasks.router)  # plug in /tasks endpoints
app.include_router(clients.router)  # plug in /clients endpoints
app.include_router(planner.router)  # plug in /planner endpoints (the AI)


@app.get("/health")  # when someone sends GET /health, run the function below
def health() -> dict[str, str]:  # returns a dictionary of text keys and text values
    return {"status": "ok"}  # FastAPI turns this into JSON: {"status": "ok"}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="dashboard")  # LAST: anything not matched above gets a file from app/static ("/" -> index.html)
