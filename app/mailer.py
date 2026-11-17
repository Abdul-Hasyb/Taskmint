import html  # html.escape: task titles go into emails safely
import json  # turn our email into JSON for Brevo
import logging  # notes for the server log
import os  # read settings from the environment (.env)
import urllib.error  # errors from the web request
import urllib.request  # send a web request (built into Python, nothing to install)
from datetime import datetime, time, timedelta  # moments, clock times, gaps

from dotenv import load_dotenv  # read the .env file
from sqlalchemy import func, select, update  # builds queries
from sqlalchemy.orm import Session  # the type of a database conversation

from app import clock  # "now" and Pakistan time
from app.models import Reminder, Task, User  # the tables we read and update
from app.routers.reminders import MISSED_AFTER, as_utc, message_for  # the same rules and words as the pop-ups

load_dotenv()  # make sure .env is loaded
logger = logging.getLogger("taskmint.mailer")  # our notes show up as "taskmint.mailer" in the log

BREVO_URL = "https://api.brevo.com/v3/smtp/email"  # Brevo's "send one email" address
DAILY_CAP = int(os.getenv("EMAIL_DAILY_CAP", "20"))  # reminder emails per person per day, at most
APP_URL = os.getenv("APP_URL", "http://127.0.0.1:8000")  # the link inside the email


def enabled() -> bool:  # is email set up? (no key = no emails, and nothing breaks)
    return bool(os.getenv("BREVO_API_KEY") and os.getenv("EMAIL_FROM"))


def brevo_send(to: str, subject: str, html_body: str, text_body: str) -> bool:  # send ONE email through Brevo; True = accepted
    payload = {
        "sender": {"name": "Taskmint", "email": os.getenv("EMAIL_FROM", "")},  # must be a sender verified in Brevo
        "to": [{"email": to}],  # only ever the account's own email
        "subject": subject[:150],  # keep it short
        "htmlContent": html_body,
        "textContent": text_body,  # for email apps that don't show HTML
    }
    request = urllib.request.Request(BREVO_URL, data=json.dumps(payload).encode(), method="POST", headers={
        "api-key": os.getenv("BREVO_API_KEY", ""),  # the secret key from .env (never in the code)
        "content-type": "application/json", "accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # never wait forever
            return 200 <= response.status < 300  # 201 = Brevo accepted it
    except urllib.error.HTTPError as error:  # Brevo said no (bad key, unverified sender, limit...)
        logger.warning("Brevo refused the email: %s %s", error.code, error.read()[:300])
    except (urllib.error.URLError, TimeoutError) as error:  # no internet / Brevo down
        logger.warning("Could not reach Brevo: %s", error)
    return False


def build_email(kind: str, task: Task) -> tuple[str, str, str]:  # subject, HTML body, plain-text body
    subject = message_for(kind, task)  # e.g. "⏰ Gym at 8:00 PM, in 1 hour" (same words as the pop-up)
    title = html.escape(task.title)  # a title like "<script>" becomes harmless text
    when = ""
    if task.due_date:
        when = task.due_date.strftime("%a, %b %d").replace(" 0", " ")  # "Mon, Nov 16"
        if task.due_time:
            when += " · " + task.due_time.strftime("%I:%M %p").lstrip("0")  # "· 8:00 PM"
    html_body = f"""<div style="font-family:Segoe UI,Arial,sans-serif;background:#0c1311;padding:28px">
  <div style="max-width:480px;margin:auto;background:#141f1b;border:1px solid #2c8a63;border-radius:16px;padding:26px;color:#e9f2ee">
    <div style="font-size:22px;font-weight:700">Task<span style="color:#3ddc97">mint</span></div>
    <p style="color:#8ea39a;margin:18px 0 4px">{html.escape(subject.split(" ", 1)[0])} Reminder</p>
    <h2 style="margin:0 0 6px;font-size:22px">{title}</h2>
    <p style="color:#c4d2cc;margin:0 0 22px">{html.escape(when) or "On your list for today"}</p>
    <a href="{html.escape(APP_URL)}" style="display:inline-block;background:#3ddc97;color:#062015;text-decoration:none;font-weight:700;padding:12px 22px;border-radius:999px">Open Taskmint</a>
    <p style="color:#5d7068;font-size:12px;margin:26px 0 0">You get this because "Email me reminders" is on in Taskmint's Settings. Turn it off there any time.</p>
  </div>
</div>"""
    text_body = f"{subject}\n{when}\n\nOpen Taskmint: {APP_URL}\n\nTurn reminder emails off in Taskmint's Settings."
    return subject, html_body, text_body


def emails_sent_today(db: Session, user_id: int) -> int:  # how many reminder emails this person got today (Pakistan day)
    midnight = clock.to_utc(clock.local_today(), time(0, 0))
    return db.scalar(select(func.count()).select_from(Reminder).where(
        Reminder.user_id == user_id, Reminder.email_sent.is_(True), Reminder.emailed_at >= midnight)) or 0


def send_due_emails(db: Session, send=brevo_send) -> int:  # one round of the email job; returns how many went out
    now = clock.utc_now()
    rows = db.execute(  # due reminders not yet emailed, for people who switched emails on
        select(Reminder, Task, User).join(Task, Task.id == Reminder.task_id).join(User, User.id == Reminder.user_id)
        .where(Reminder.emailed_at.is_(None), Reminder.send_at <= now, User.email_reminders.is_(True), User.email_verified.is_(True))  # switch on AND address confirmed
        .order_by(Reminder.send_at).limit(500)
    ).all()
    newest: dict[int, tuple[Reminder, Task, User]] = {}  # one email per task: the newest due reminder
    for reminder, task, user in rows:
        claimed = db.execute(update(Reminder).where(Reminder.id == reminder.id, Reminder.emailed_at.is_(None)).values(emailed_at=now))  # "I'm handling this one"
        if claimed.rowcount and task.status != "done" and now - as_utc(reminder.send_at) <= MISSED_AFTER:  # still useful?
            newest[task.id] = (reminder, task, user)
    db.commit()  # save the claims first, so a crash can never send the same email twice
    sent = 0
    for reminder, task, user in newest.values():
        if emails_sent_today(db, user.id) >= DAILY_CAP:  # enough for today
            continue
        subject, html_body, text_body = build_email(reminder.kind, task)
        if send(user.email, subject, html_body, text_body):  # only to the account's own address
            db.execute(update(Reminder).where(Reminder.id == reminder.id).values(email_sent=True))
            sent += 1
        else:  # Brevo failed: un-claim it so the next minute can try again (until it's 2 hours old)
            db.execute(update(Reminder).where(Reminder.id == reminder.id).values(emailed_at=None))
        db.commit()
    return sent


def run_once() -> None:  # one round, with its own database session (called every minute)
    from app.database import SessionLocal  # imported here so tests can swap the database first
    with SessionLocal() as db:
        count = send_due_emails(db)
        if count:
            logger.info("Sent %s reminder email(s)", count)
