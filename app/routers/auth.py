from datetime import datetime  # moments in time

from fastapi import APIRouter, Depends, HTTPException, status  # APIRouter = a group of related endpoints
from fastapi.security import OAuth2PasswordRequestForm  # the standard login form: username + password
from sqlalchemy import select  # builds SELECT queries
from sqlalchemy.exc import IntegrityError  # raised when the database refuses a duplicate
from sqlalchemy.orm import Session  # the type of a database conversation

from app.database import get_db  # hands each request its own database session
from app.models import User  # the users TABLE
from app import clock, mailer  # "now" (one clock the tests can freeze) and reminder emails (Brevo)
from app.schemas import Token, UserCreate, UserRead, UserSettings  # the forms
from app.security import DUMMY_HASH, create_access_token, get_current_user, hash_password, verify_password  # login tools

router = APIRouter(prefix="/auth", tags=["auth"])  # every endpoint here starts with /auth


@router.post("/register", status_code=status.HTTP_201_CREATED)  # POST /auth/register makes an account
def register(user_in: UserCreate, db: Session = Depends(get_db)) -> UserRead:  # body checked against UserCreate
    user = User(email=user_in.email.lower(), password_hash=hash_password(user_in.password))  # store the email in lowercase and ONLY the hash
    db.add(user)  # put it in the "to save" pile
    try:  # the email might already be taken
        db.commit()  # save it
    except IntegrityError:  # the database's unique rule said no
        db.rollback()  # undo the failed save
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")  # 409 Conflict
    db.refresh(user)  # reload to get the id
    return UserRead.model_validate(user)  # send back id, email, created_at (never the hash)


@router.post("/login")  # POST /auth/login: email + password in, token out
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> Token:  # the standard form; "username" holds the email
    user = db.scalar(select(User).where(User.email == form.username.strip().lower()))  # find the account by email
    if user is None:  # no such email...
        verify_password(form.password, DUMMY_HASH)  # ...still spend the same time checking, so attackers can't tell which emails exist
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})
    if not verify_password(form.password, user.password_hash):  # wrong password?
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})  # same message on purpose
    return Token(access_token=create_access_token(user.id))  # the login token


@router.get("/me")  # GET /auth/me: who am I logged in as?
def me(user: User = Depends(get_current_user)) -> UserRead:  # needs a valid token
    return UserRead.model_validate(user)  # the logged-in user


LAST_TEST: dict[int, datetime] = {}  # user id -> when they last sent a test email (kept in memory)


@router.patch("/me")  # PATCH /auth/me: change my settings (only the "email me reminders" switch for now)
def update_me(settings: UserSettings, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> UserRead:
    user.email_reminders = settings.email_reminders  # flip the switch
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)


@router.post("/me/test-email")  # POST /auth/me/test-email: send ONE test email to MY address
def test_email(user: User = Depends(get_current_user)) -> dict[str, str]:
    if not mailer.enabled():  # no Brevo key on the server
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Email isn't set up on the server yet (BREVO_API_KEY / EMAIL_FROM).")
    now = clock.utc_now()
    last = LAST_TEST.get(user.id)
    if last and (now - last).total_seconds() < 60:  # at most one test a minute (no spamming through Brevo)
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Wait a minute before sending another test email.")
    LAST_TEST[user.id] = now
    ok = mailer.brevo_send(user.email, "🔔 Taskmint test email",  # only ever to the logged-in account's own address
        "<div style='font-family:Segoe UI,Arial,sans-serif'><h2>Task<span style='color:#3ddc97'>mint</span></h2><p>Reminder emails work! 🎉</p></div>",
        "Taskmint: reminder emails work!")
    if not ok:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Brevo didn't accept the email. Check the API key and that the sender is verified.")
    return {"status": "sent", "to": user.email}
