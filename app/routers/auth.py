from datetime import datetime  # moments in time

from fastapi import APIRouter, Depends, HTTPException, Request, status  # APIRouter = a group of related endpoints; Request = who is calling
from fastapi.responses import RedirectResponse  # send the browser to another page
from fastapi.security import OAuth2PasswordRequestForm  # the standard login form: username + password
from sqlalchemy import select  # builds SELECT queries
from sqlalchemy.exc import IntegrityError  # raised when the database refuses a duplicate
from sqlalchemy.orm import Session  # the type of a database conversation

from app.database import get_db  # hands each request its own database session
from app.guard import client_ip, limit  # rate limits
from app.models import User  # the users TABLE
from app import clock, mailer  # "now" (one clock the tests can freeze) and reminder emails (Brevo)
from app.schemas import Token, UserCreate, UserRead, UserSettings  # the forms
from app.security import DUMMY_HASH, create_access_token, create_purpose_token, get_current_user, hash_password, read_purpose_token, verify_password  # login tools

router = APIRouter(prefix="/auth", tags=["auth"])  # every endpoint here starts with /auth


@router.post("/register", status_code=status.HTTP_201_CREATED)  # POST /auth/register makes an account
def register(user_in: UserCreate, request: Request, db: Session = Depends(get_db)) -> UserRead:  # body checked against UserCreate
    limit(f"register:{client_ip(request)}", 5, 3600, "Too many new accounts from this network. Try again later.")  # 5 sign-ups an hour per IP (no bot armies)
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
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> Token:  # the standard form; "username" holds the email
    limit(f"login-ip:{client_ip(request)}", 10, 60, "Too many login attempts. Wait a minute and try again.")  # 10 tries a minute per IP
    limit(f"login-email:{form.username.strip().lower()[:254]}", 10, 900, "Too many login attempts for this account. Try again in 15 minutes.")  # 10 tries per 15 min per account, from ANY network
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
    if settings.email_reminders and not user.email_verified:  # emails only to an address its owner has confirmed
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verify your email first (Settings → Send verification email).")
    user.email_reminders = settings.email_reminders  # flip the switch
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)


@router.post("/me/test-email")  # POST /auth/me/test-email: send ONE test email to MY address
def test_email(user: User = Depends(get_current_user)) -> dict[str, str]:
    if not mailer.enabled():  # no Brevo key on the server
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Email isn't set up on the server yet (BREVO_API_KEY / EMAIL_FROM).")
    if not user.email_verified:  # never email an address nobody has confirmed
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verify your email first.")
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


@router.post("/me/send-verification")  # POST /auth/me/send-verification: email me a "this address is mine" link
def send_verification(user: User = Depends(get_current_user)) -> dict[str, str]:
    if user.email_verified:
        return {"status": "already verified", "to": user.email}
    if not mailer.enabled():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Email isn't set up on the server yet (BREVO_API_KEY / EMAIL_FROM).")
    limit(f"verify-mail:{user.id}", 3, 3600, "We've sent 3 verification emails this hour. Check your inbox and Spam, or try again later.")  # no mail-bombing
    token = create_purpose_token(user.id, user.email, "verify", minutes=24 * 60)  # the link works for 24 hours
    link = f"{mailer.APP_URL}/auth/verify?token={token}"
    ok = mailer.brevo_send(user.email, "✅ Confirm your email for Taskmint",
        f"<div style='font-family:Segoe UI,Arial,sans-serif'><h2>Task<span style='color:#3ddc97'>mint</span></h2>"
        f"<p>Click to confirm this email is yours:</p><p><a href='{link}' style='background:#3ddc97;color:#062015;padding:12px 22px;border-radius:999px;text-decoration:none;font-weight:700'>Confirm my email</a></p>"
        f"<p style='color:#777;font-size:12px'>The link works for 24 hours. If you didn't sign up for Taskmint, ignore this email.</p></div>",
        f"Confirm your email for Taskmint: {link}\n(The link works for 24 hours. If you didn't sign up, ignore this email.)")
    if not ok:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Brevo didn't accept the email. Check the API key and the sender.")
    return {"status": "sent", "to": user.email}


@router.get("/verify")  # GET /auth/verify?token=...: the link inside the email
def verify_email(token: str, db: Session = Depends(get_db)) -> RedirectResponse:
    found = read_purpose_token(token[:2000], "verify")  # only a valid, unexpired "verify" token
    user = db.get(User, found[0]) if found else None
    if user is None or user.email != found[1]:  # unknown user, or the token was for an older email
        return RedirectResponse("/?verified=0", status_code=303)
    user.email_verified = True
    db.commit()
    return RedirectResponse("/?verified=1", status_code=303)  # back to Taskmint, which shows "Email verified ✅"
