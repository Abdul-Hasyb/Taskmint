import os  # read settings from the environment (.env)
from datetime import datetime, timezone  # to know what day it is (UTC)

from fastapi import APIRouter, Depends, HTTPException, status  # APIRouter = a group of related endpoints
from pydantic import ValidationError  # raised when data doesn't match a model
from sqlalchemy import select  # builds SELECT queries
from sqlalchemy.orm import Session  # the type of a database conversation

from app import ai  # our Gemini helper (used as ai.ask_ai, so tests can swap it for a fake)
from app.database import get_db  # hands each request its own database session
from app.models import AIUsage, Client, Task, User  # the AI-usage, clients, tasks and users TABLES
from app.routers.tasks import check_client_exists  # reuse: a task can only point at a real client
from app.schemas import ApproveRequest, PlanRequest, PlanResponse, ProposedTask, TaskRead  # the forms
from app.security import get_current_user  # "who is logged in?" (401 if nobody)

router = APIRouter(prefix="/planner", tags=["planner"])  # every endpoint here starts with /planner
AI_DAILY_LIMIT = int(os.getenv("AI_DAILY_LIMIT", "20"))  # AI requests each user gets per day (default 20)


def today_usage(db: Session, user: User) -> AIUsage:  # get (or start) this user's counter for today
    today = datetime.now(timezone.utc).date()  # today's date in UTC, e.g. 2026-11-14
    usage = db.scalar(select(AIUsage).where(AIUsage.user_id == user.id, AIUsage.day == today))  # today's row, if it exists
    if usage is None:  # first AI request today
        usage = AIUsage(user_id=user.id, day=today, count=0)  # a fresh counter at 0 (a new day = a fresh limit)
        db.add(usage)  # into the "to save" pile
    return usage  # the counter


def use_ai_credit(db: Session, user: User) -> None:  # count one AI request, or refuse if the limit is reached
    usage = today_usage(db, user)  # today's counter
    if usage.count >= AI_DAILY_LIMIT:  # already used them all?
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=f"Daily AI limit reached ({AI_DAILY_LIMIT} per day). Try again tomorrow.")  # stop BEFORE calling Gemini
    usage.count += 1  # one more used
    db.commit()  # save NOW, so even a failed AI call still counts (no free retries for spammers)


@router.get("/usage")  # GET /planner/usage: how many AI requests I have left today
def usage(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, int]:  # login required
    used = today_usage(db, user).count  # how many I've used today (0 if none)
    return {"used": used, "limit": AI_DAILY_LIMIT, "remaining": max(AI_DAILY_LIMIT - used, 0)}  # e.g. {"used": 3, "limit": 20, "remaining": 17}


def normalise(text: str) -> str:  # make text easy to compare: lowercase, single spaces
    return " ".join(text.lower().split())  # "  Kal  TAK " -> "kal tak"


@router.post("/propose")  # POST /planner/propose: message in, suggested tasks out, NOTHING saved
def propose(request: PlanRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> PlanResponse:  # login required
    clients = db.execute(select(Client.id, Client.name).where(Client.user_id == user.id).order_by(Client.id)).all()  # only MY clients: [(1, "Bilal")]
    known_ids = {client_id for client_id, _ in clients}  # {1, 2}, to check the AI's answer against
    use_ai_credit(db, user)  # count this request (429 if today's limit is used up)
    try:  # the AI might be down or out of quota
        plan = ai.ask_ai(request.message, [(cid, name) for cid, name in clients])  # ask Gemini
    except ai.PlannerRateLimited:  # free quota used up
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="AI limit reached. Try again in a minute.")
    except ai.PlannerUnavailable:  # no key, no internet, or Gemini error
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="AI planner is unavailable right now.")

    message = normalise(request.message)  # the message, ready for comparing
    proposals: list[ProposedTask] = []  # the suggestions that pass every check
    for item in plan.tasks[:10]:  # never more than 10, whatever the AI says
        if not item.source_quote.strip() or normalise(item.source_quote) not in message:  # quote missing, or not really in the message?
            continue  # the AI made it up: drop it
        try:  # check it like a normal task (title length etc.)
            proposals.append(ProposedTask(  # build a checked suggestion
                title=item.title.strip(),  # trimmed title
                description=item.description,  # details
                client_id=item.client_id if item.client_id in known_ids else None,  # only a client that really exists
                source_quote=item.source_quote.strip(),  # the proof
            ))
        except ValidationError:  # e.g. an empty or 500-character title
            continue  # drop it
    return PlanResponse(tasks=proposals, dropped=len(plan.tasks) - len(proposals))  # suggestions + how many we threw away


@router.post("/approve", status_code=status.HTTP_201_CREATED)  # POST /planner/approve: save the tasks the user chose
def approve(request: ApproveRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[TaskRead]:  # login required
    for task_in in request.tasks:  # check EVERY task first...
        check_client_exists(db, task_in.client_id, user)  # ...so one bad (or someone else's) client stops the whole batch
    tasks = [Task(title=t.title, description=t.description, client_id=t.client_id, user_id=user.id) for t in request.tasks]  # the new rows, owned by this user
    db.add_all(tasks)  # all of them into the "to save" pile
    db.commit()  # save them together: all or nothing
    for task in tasks:  # reload each one...
        db.refresh(task)  # ...to get its id and created_at
    return [TaskRead.model_validate(task) for task in tasks]  # send them back
