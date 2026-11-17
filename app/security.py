import os  # lets Python read environment variables
from datetime import datetime, timedelta, timezone  # tools for times and durations

import jwt  # PyJWT: creates and checks login tokens
from dotenv import load_dotenv  # reads the .env file
from fastapi import Depends, HTTPException, status  # FastAPI tools
from fastapi.security import OAuth2PasswordBearer  # reads "Authorization: Bearer <token>" from each request
from pwdlib import PasswordHash  # hashes passwords safely (Argon2)
from sqlalchemy.orm import Session  # the type of a database conversation

from app.database import get_db  # hands each request its own database session
from app.models import User  # the users TABLE

load_dotenv()  # read .env, so os.getenv can see JWT_SECRET

JWT_SECRET = os.getenv("JWT_SECRET")  # the secret that signs login tokens (from .env, never in code)
if not JWT_SECRET or len(JWT_SECRET) < 32:  # missing, or too short to be safe?
    raise RuntimeError("JWT_SECRET must be set in .env and be at least 32 characters.")  # stop with a clear message
ALGORITHM = "HS256"  # how tokens are signed
TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "60"))  # how long a login lasts before you must log in again

password_hash = PasswordHash.recommended()  # Argon2, today's recommended way to store passwords
DUMMY_HASH = password_hash.hash("dummy-password-for-timing")  # used when an email doesn't exist, so a wrong email takes as long as a wrong password
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")  # tells FastAPI (and /docs) where to log in

UNAUTHORIZED = HTTPException(  # the one error for every login problem (no hints for attackers)
    status_code=status.HTTP_401_UNAUTHORIZED,  # 401 = "who are you?"
    detail="Could not validate credentials",  # deliberately vague
    headers={"WWW-Authenticate": "Bearer"},  # tells the browser what kind of login is expected
)


def hash_password(password: str) -> str:  # turn a password into a one-way scrambled string
    return password_hash.hash(password)  # e.g. "$argon2id$v=19$m=65536..."; the real password can't be recovered from it


def verify_password(password: str, hashed: str) -> bool:  # does this password match the stored hash?
    return password_hash.verify(password, hashed)  # True or False


def create_access_token(user_id: int) -> str:  # make a signed login token for this user
    expires = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_MINUTES)  # when it stops working
    return jwt.encode({"sub": str(user_id), "exp": expires}, JWT_SECRET, algorithm=ALGORITHM)  # sub = which user; exp = expiry


def create_purpose_token(user_id: int, email: str, purpose: str, minutes: int) -> str:  # a one-job token (e.g. "verify" this email), NOT a login
    expires = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return jwt.encode({"sub": str(user_id), "em": email, "pur": purpose, "exp": expires}, JWT_SECRET, algorithm=ALGORITHM)  # pur = what it's for


def read_purpose_token(token: str, purpose: str) -> tuple[int, str] | None:  # (user id, email) if the token is valid for THIS job, else None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])  # signature + expiry
        if payload.get("pur") != purpose:  # a login token, or a token for another job
            return None
        return int(payload["sub"]), str(payload["em"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:  # every protected endpoint uses this
    try:  # the token might be fake, edited or expired
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])  # checks the signature AND the expiry
        user_id = int(payload["sub"])  # which user it belongs to
        if "pur" in payload:  # a one-job token (like an email link) can never be used to log in
            raise ValueError("not a login token")
    except (jwt.InvalidTokenError, KeyError, ValueError):  # bad signature, expired, missing/odd "sub", or wrong kind of token
        raise UNAUTHORIZED  # 401
    user = db.get(User, user_id)  # does that user still exist?
    if user is None:  # deleted, or never existed
        raise UNAUTHORIZED  # 401
    return user  # the logged-in user
