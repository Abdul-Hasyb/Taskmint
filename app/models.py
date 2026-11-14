from datetime import date, datetime, timezone  # tools for working with dates and times (date = just a day, no time)

from sqlalchemy import Date, DateTime, ForeignKey, String, UniqueConstraint  # column types; ForeignKey = "points at another table"; UniqueConstraint = "no two rows with the same values"
from sqlalchemy.orm import Mapped, mapped_column  # tools for describing a table's columns

from app.database import Base  # the parent class every table inherits from


def utc_now() -> datetime:  # the current time in UTC
    return datetime.now(timezone.utc)  # used as the default for created_at


class User(Base):  # one row in the "users" table = one account
    __tablename__ = "users"  # the table's name inside the database
    __table_args__ = {"sqlite_autoincrement": True}  # tests' SQLite: never reuse deleted ids

    id: Mapped[int] = mapped_column(primary_key=True)  # unique number, picked by the database
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)  # login email; unique = no two accounts with the same email
    password_hash: Mapped[str] = mapped_column(String(255))  # the SCRAMBLED password; the real one is never stored
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)  # when the account was made


class Client(Base):  # one row in the "clients" table = one client (Bilal, Sara, a gym brand...)
    __tablename__ = "clients"  # the table's name inside the database
    __table_args__ = {"sqlite_autoincrement": True}  # tests' SQLite: never reuse deleted ids

    id: Mapped[int] = mapped_column(primary_key=True)  # unique number, picked by the database
    name: Mapped[str] = mapped_column(String(100))  # the client's name, at most 100 characters
    notes: Mapped[str | None] = mapped_column(String(1000))  # optional notes, e.g. "prefers WhatsApp voice notes"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)  # set automatically
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)  # whose client this is (required)


class Task(Base):  # one row in the "tasks" table = one task
    __tablename__ = "tasks"  # the table's name inside the database
    __table_args__ = {"sqlite_autoincrement": True}  # tests' SQLite: never reuse deleted ids (PostgreSQL already never does)

    id: Mapped[int] = mapped_column(primary_key=True)  # unique number; the database picks it automatically
    title: Mapped[str] = mapped_column(String(200))  # required text, at most 200 characters
    description: Mapped[str | None] = mapped_column(String(2000))  # optional text, at most 2000 characters
    status: Mapped[str] = mapped_column(String(20), default="todo")  # todo / in_progress / done; starts as todo
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)  # set automatically on insert
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), index=True)  # which client this task is for (optional)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)  # whose task this is (required)


class AIUsage(Base):  # one row in the "ai_usage" table = how many AI requests one user made on one day
    __tablename__ = "ai_usage"  # the table's name inside the database
    __table_args__ = (UniqueConstraint("user_id", "day"), {"sqlite_autoincrement": True})  # only ONE counter row per user per day

    id: Mapped[int] = mapped_column(primary_key=True)  # unique number, picked by the database
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)  # whose counter this is
    day: Mapped[date] = mapped_column(Date)  # which day (UTC) the counter is for
    count: Mapped[int] = mapped_column(default=0)  # how many AI requests so far that day
