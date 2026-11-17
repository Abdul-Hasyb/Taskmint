"""Set a new password for a Taskmint account, from your own computer (owner-only tool).

Run from the taskmint folder:  python -m scripts.set_password
It uses DATABASE_URL from .env, so it changes the SAME database the live site uses.
"""
from getpass import getpass  # type a password without it showing on screen

from pydantic import ValidationError  # the error our password rules raise

from app.database import SessionLocal  # a conversation with the database
from app.models import User  # the users table
from app.schemas import UserCreate  # reuse the sign-up rules (8+ chars, not common, etc.)
from app.security import hash_password  # Argon2, the same as sign-up


def main() -> None:
    with SessionLocal() as db:  # open the database (closed automatically at the end)
        emails = [u.email for u in db.query(User).order_by(User.id)]  # every account, oldest first
        print("Accounts:", *[f"  {n}. {e}" for n, e in enumerate(emails, 1)], sep="\n")  # in case you forgot which email you used
        email = input("\nEmail to reset: ").strip().lower()
        user = db.query(User).filter(User.email == email).first()  # find that account
        if user is None:
            print("No account with that email. Nothing changed.")
            return
        new = getpass("New password (hidden): ")  # nothing appears while you type: that's normal
        if new != getpass("Type it again: "):  # catch typos
            print("The two passwords don't match. Nothing changed.")
            return
        try:
            UserCreate(email=email, password=new)  # same rules as sign-up: 8+ chars, not common, not your email name
        except ValidationError as error:
            print("Not accepted:", error.errors()[0]["msg"].removeprefix("Value error, "))
            return
        user.password_hash = hash_password(new)  # store only the scrambled version, never the password itself
        db.commit()  # save
        print(f"Done. Log in as {email} with your new password.")


if __name__ == "__main__":  # only when run directly
    main()
