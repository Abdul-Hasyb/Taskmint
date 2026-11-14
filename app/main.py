from fastapi import FastAPI  # the core of our web app

from app.routers import auth, clients, planner, tasks  # the groups of endpoints, each in its own file

app = FastAPI(title="Taskmint", version="0.5.0")  # create the app; tables are created by Alembic migrations, not here
app.include_router(auth.router)  # plug in /auth endpoints (register, login, me)
app.include_router(tasks.router)  # plug in /tasks endpoints
app.include_router(clients.router)  # plug in /clients endpoints
app.include_router(planner.router)  # plug in /planner endpoints (the AI)


@app.get("/health")  # when someone sends GET /health, run the function below
def health() -> dict[str, str]:  # returns a dictionary of text keys and text values
    return {"status": "ok"}  # FastAPI turns this into JSON: {"status": "ok"}