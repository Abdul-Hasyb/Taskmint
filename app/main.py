import asyncio  # run the email job in the background, every minute
import logging  # notes for the server log
from contextlib import asynccontextmanager  # code that runs when the server starts and stops
from pathlib import Path  # build file paths that work on Windows and Linux

from fastapi import FastAPI  # the core of our web app
from fastapi.staticfiles import StaticFiles  # serves plain files (our dashboard page) from a folder

from app import guard, mailer  # the security guard at the door + reminder emails (Brevo)
from app.routers import auth, clients, planner, reminders, tasks  # the groups of endpoints, each in its own file

STATIC_DIR = Path(__file__).parent / "static"  # app/static, found next to this file (works from any folder)

logger = logging.getLogger("taskmint")


async def email_loop() -> None:  # forever: send due reminder emails, wait a minute, repeat
    while True:
        try:
            await asyncio.to_thread(mailer.run_once)  # in a side thread, so the website never freezes
        except Exception:  # one bad round must never stop the loop
            logger.exception("Reminder email round failed")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):  # runs once when the server starts, and once when it stops
    job = asyncio.create_task(email_loop()) if mailer.enabled() else None  # no Brevo key in .env = no email job
    if job is None:
        logger.warning("Reminder emails are OFF (BREVO_API_KEY / EMAIL_FROM not set in .env)")
    yield  # the server runs here
    if job:
        job.cancel()  # stop the loop when the server stops


app = FastAPI(title="Taskmint", version="0.8.0", lifespan=lifespan,
              docs_url="/docs" if guard.docs_enabled() else None, redoc_url=None,  # /docs can be switched off when live (ENABLE_DOCS=0)
              openapi_url="/openapi.json" if guard.docs_enabled() else None)
guard.install(app, STATIC_DIR)  # rate limits, size limit, security headers, friendly 500s (tables come from Alembic migrations)
app.include_router(auth.router)  # plug in /auth endpoints (register, login, me)
app.include_router(tasks.router)  # plug in /tasks endpoints
app.include_router(clients.router)  # plug in /clients endpoints
app.include_router(planner.router)  # plug in /planner endpoints (the AI)
app.include_router(reminders.router)  # plug in /reminders endpoints


@app.get("/health")  # when someone sends GET /health, run the function below
def health() -> dict[str, str]:  # returns a dictionary of text keys and text values
    return {"status": "ok"}  # FastAPI turns this into JSON: {"status": "ok"}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="dashboard")  # LAST: anything not matched above gets a file from app/static ("/" -> index.html)
