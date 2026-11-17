from datetime import datetime, time, timedelta, timezone  # moments, clock times, gaps

from fastapi import APIRouter, Depends, HTTPException, status  # APIRouter = a group of related endpoints
from sqlalchemy import delete, select  # builds DELETE and SELECT queries
from sqlalchemy.orm import Session  # the type of a database conversation

from app import clock  # "now" and Pakistan time (used as clock.x so tests can freeze time)
from app.database import get_db  # hands each request its own database session
from app.guard import limit  # rate limits
from app.models import Reminder, Task, User  # the reminders, tasks and users TABLES
from app.schemas import ReminderOut, ReminderUpcoming, SnoozeRequest  # what we send back / receive
from app.security import get_current_user  # "who is logged in?" (401 if nobody)

router = APIRouter(prefix="/reminders", tags=["reminders"])  # every endpoint here starts with /reminders

QUIET_START, QUIET_END = time(23, 0), time(8, 0)  # no reminders between 11 PM and 8 AM (Pakistan time)
DAY_TIMES = {"morning": time(9, 0), "afternoon": time(14, 0), "evening": time(20, 0)}  # for tasks with a day but no time
MISSED_AFTER = timedelta(hours=2)  # a reminder older than this is "missed" (laptop was off): don't pop it up late


def as_utc(moment: datetime) -> datetime:  # SQLite forgets the time zone; our times are always stored as UTC
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def in_quiet_hours(moment: datetime) -> bool:  # is this moment between 11 PM and 8 AM in Pakistan?
    t = moment.astimezone(clock.LOCAL_TZ).time()  # the clock time in Pakistan
    return t >= QUIET_START or t < QUIET_END


def reminder_times(task: Task) -> list[tuple[str, datetime]]:  # the reminders this task should get, from now on
    if task.status == "done":  # finished tasks get no reminders
        return []
    day = task.due_date or as_utc(task.created_at or clock.utc_now()).astimezone(clock.LOCAL_TZ).date()  # no due day = the day it was added
    if task.due_time is not None:  # a clock time: 1 hour before, at, 1 hour after
        due = clock.to_utc(day, task.due_time)
        times = [("before", due - timedelta(hours=1)), ("at", due), ("after", due + timedelta(hours=1))]
    else:  # only a day: morning, afternoon, evening
        times = [(kind, clock.to_utc(day, at)) for kind, at in DAY_TIMES.items()]
    now = clock.utc_now()
    return [(kind, at) for kind, at in times
            if at > now  # only future reminders
            and (kind == "at" or not in_quiet_hours(at))]  # quiet hours, except the exact time the user picked


def plan_reminders(db: Session, task: Task) -> None:  # (re)build a task's waiting reminders; the caller commits
    old = delete(Reminder).where(Reminder.task_id == task.id, Reminder.sent_at.is_(None))  # the old plan (not yet shown)
    if task.status != "done":  # a snooze I asked for stays, unless the task is finished
        old = old.where(Reminder.kind != "snooze")
    db.execute(old)  # drop it
    for kind, at in reminder_times(task):  # make the new plan
        db.add(Reminder(task_id=task.id, user_id=task.user_id, kind=kind, send_at=at))


def delete_reminders(db: Session, task_id: int) -> None:  # before deleting a task, its reminders go too
    db.execute(delete(Reminder).where(Reminder.task_id == task_id))


def clock_text(task: Task) -> str:  # "8:00 PM"
    return task.due_time.strftime("%I:%M %p").lstrip("0") if task.due_time else ""


def message_for(kind: str, task: Task) -> str:  # the words the user sees
    t = clock_text(task)
    return {
        "before": f"⏰ {task.title} at {t}, in 1 hour",
        "at": f"🔔 {task.title} is now ({t})",
        "after": f"❓ Did you finish \"{task.title}\"? It was due at {t}",
        "morning": f"📋 Today: {task.title}",
        "afternoon": f"Still to do: {task.title}",
        "evening": f"Last call today: {task.title}",
        "snooze": f"🔁 {task.title} (snoozed)",
    }[kind]


@router.get("/due")  # GET /reminders/due: reminders to pop up NOW (each one only once)
def due_reminders(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[ReminderOut]:
    now = clock.utc_now()
    rows = db.execute(  # my reminders whose time has come and that weren't handed out yet
        select(Reminder, Task).join(Task, Task.id == Reminder.task_id)
        .where(Reminder.user_id == user.id, Reminder.sent_at.is_(None), Reminder.send_at <= now)
        .order_by(Reminder.send_at)
    ).all()
    latest: dict[int, ReminderOut] = {}  # task id -> its newest due reminder
    for reminder, task in rows:  # oldest first
        reminder.sent_at = now  # mark it handed out, so it never pops up twice
        if task.status == "done" or now - as_utc(reminder.send_at) > MISSED_AFTER:  # finished, or too old to be useful
            continue  # skip quietly
        latest[task.id] = ReminderOut(task_id=task.id, kind=reminder.kind, title=task.title, message=message_for(reminder.kind, task))  # a newer one replaces an older one
    db.commit()  # save the "sent" marks
    return list(latest.values())[:10]  # one per task ("now" beats "in 1 hour"), and never flood the screen


@router.post("/snooze", status_code=status.HTTP_201_CREATED)  # POST /reminders/snooze: remind me again in N minutes
def snooze(request: SnoozeRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> ReminderUpcoming:
    limit(f"snooze:{user.id}", 60, 3600)  # 60 snoozes an hour is plenty
    task = db.scalar(select(Task).where(Task.id == request.task_id, Task.user_id == user.id))  # must be MY task
    if task is None:  # not mine, or doesn't exist
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    db.execute(delete(Reminder).where(Reminder.task_id == task.id, Reminder.kind == "snooze", Reminder.sent_at.is_(None)))  # one snooze at a time
    reminder = Reminder(task_id=task.id, user_id=user.id, kind="snooze", send_at=clock.utc_now() + timedelta(minutes=request.minutes))
    db.add(reminder)
    db.commit()
    return ReminderUpcoming(task_id=task.id, kind="snooze", send_at=as_utc(reminder.send_at))


@router.get("/upcoming")  # GET /reminders/upcoming: my next waiting reminders (for the 🔔 on tasks)
def upcoming_reminders(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[ReminderUpcoming]:
    rows = db.scalars(
        select(Reminder).where(Reminder.user_id == user.id, Reminder.sent_at.is_(None), Reminder.send_at > clock.utc_now())
        .order_by(Reminder.send_at).limit(50)
    ).all()
    return [ReminderUpcoming(task_id=r.task_id, kind=r.kind, send_at=as_utc(r.send_at)) for r in rows]
