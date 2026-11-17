from datetime import date, datetime, time  # date = a day, datetime = a moment, time = a clock time
from typing import Annotated, Literal  # lets us say "only these exact values are allowed"

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator  # tools for describing and validating data; EmailStr checks emails

TaskStatus = Literal["todo", "in_progress", "done"]  # the only statuses a task can have
DbId = Annotated[int, Field(ge=1, le=2_147_483_647)]  # an id the database can hold (1 .. 2,147,483,647); anything else = 422, not a crash
STRICT = ConfigDict(extra="forbid", str_strip_whitespace=True)  # shared safety rules: reject unknown fields, trim spaces


class TaskCreate(BaseModel):  # what the user must SEND to create a task
    model_config = STRICT  # reject unknown fields; trim spaces from text

    title: str = Field(min_length=1, max_length=200)  # required; 1 to 200 characters
    description: str | None = Field(default=None, max_length=2000)  # optional; at most 2000 characters
    client_id: DbId | None = None  # optional: who this task is FROM or about (e.g. the client who asked)
    assignee_id: DbId | None = None  # optional: who DOES it (someone on my People list); None = me
    due_date: date | None = None  # optional: the day it's due, e.g. "2026-11-16"
    due_time: time | None = None  # optional: the time it's due, e.g. "20:00" (needs a due_date)

    @model_validator(mode="after")  # runs after the fields above are checked
    def time_needs_a_day(self) -> "TaskCreate":  # "8 PM" alone makes no sense without a day
        if self.due_time is not None and self.due_date is None:  # a time but no day?
            raise ValueError("due_time needs a due_date")  # reject with 422
        return self  # all good


class TaskUpdate(BaseModel):  # what the user may SEND to change a task; every field is optional
    model_config = STRICT  # same safety rules as TaskCreate

    title: str | None = Field(default=None, min_length=1, max_length=200)  # new title, if changing it
    description: str | None = Field(default=None, max_length=2000)  # new description, if changing it
    status: TaskStatus | None = None  # new status, if changing it
    client_id: DbId | None = None  # move the task to another client, or null to remove the client
    assignee_id: DbId | None = None  # give it to someone else, or null to take it back myself
    due_date: date | None = None  # a new due day, or null to remove it (also removes the time)
    due_time: time | None = None  # a new due time, or null for "sometime that day"

    @model_validator(mode="after")  # runs after the fields above are checked
    def at_least_one_field(self) -> "TaskUpdate":  # make sure the update actually changes something
        if not self.model_fields_set:  # did the user send zero fields?
            raise ValueError("Send at least one field to update")  # yes: reject with 422
        if "title" in self.model_fields_set and self.title is None:  # did they try to set the title to null?
            raise ValueError("title cannot be null")  # a task must always have a title
        return self  # all good


class TaskRead(BaseModel):  # what the API SENDS BACK for a task
    model_config = ConfigDict(from_attributes=True)  # allow building this from a database row

    id: int  # the task's unique number
    title: str  # the task's title
    description: str | None  # the task's description, or None
    status: TaskStatus  # one of: todo, in_progress, done
    created_at: datetime  # when the task was created
    client_id: int | None  # the client's id, or None if the task has no client
    assignee_id: int | None  # who does it, or None = me
    completed_at: datetime | None  # when it was ticked done, or None
    due_date: date | None  # the day it's due, or None
    due_time: time | None  # the time it's due, or None


class ClientCreate(BaseModel):  # what the user must SEND to create a client
    model_config = STRICT  # reject unknown fields; trim spaces

    name: str = Field(min_length=1, max_length=100)  # required; 1 to 100 characters
    notes: str | None = Field(default=None, max_length=1000)  # optional; at most 1000 characters


class ClientUpdate(BaseModel):  # what the user may SEND to change a client
    model_config = STRICT  # same safety rules

    name: str | None = Field(default=None, min_length=1, max_length=100)  # new name, if changing it
    notes: str | None = Field(default=None, max_length=1000)  # new notes, if changing them

    @model_validator(mode="after")  # runs after the fields above are checked
    def at_least_one_field(self) -> "ClientUpdate":  # make sure the update actually changes something
        if not self.model_fields_set:  # zero fields sent?
            raise ValueError("Send at least one field to update")  # reject with 422
        if "name" in self.model_fields_set and self.name is None:  # trying to remove the name?
            raise ValueError("name cannot be null")  # a client must always have a name
        return self  # all good


class ClientRead(BaseModel):  # what the API SENDS BACK for a client
    model_config = ConfigDict(from_attributes=True)  # allow building this from a database row

    id: int  # the client's unique number
    name: str  # the client's name
    notes: str | None  # notes, or None
    created_at: datetime  # when the client was added
    open_tasks: int = 0  # how many of their tasks are not done yet (calculated, not stored)


class PlanRequest(BaseModel):  # what the user SENDS to the AI planner
    model_config = STRICT  # reject unknown fields; trim spaces

    message: str = Field(min_length=1, max_length=4000)  # the client's message; capped so no one can send a novel and burn our AI quota


class ProposedTask(BaseModel):  # one task the AI suggests (NOT saved yet)
    title: str = Field(min_length=1, max_length=200)  # same limits as a real task
    description: str | None = Field(default=None, max_length=2000)  # same limits as a real task
    client_id: DbId | None = None  # which client, or None
    assignee_id: DbId | None = None  # who should do it, or None = me
    due_date: date | None = None  # the day the AI worked out ("kal" -> tomorrow), or None
    due_time: time | None = None  # the time the AI worked out ("8 baje" -> 20:00), or None
    source_quote: str  # the exact words from the message this task came from


class PlanResponse(BaseModel):  # what the planner SENDS BACK
    tasks: list[ProposedTask]  # the suggestions that passed our checks
    dropped: int  # how many of the AI's suggestions we threw away because they failed our checks


class ApproveRequest(BaseModel):  # what the user SENDS to save the tasks they chose
    model_config = STRICT  # reject unknown fields

    tasks: list[TaskCreate] = Field(min_length=1, max_length=10)  # 1 to 10 tasks, each checked like a normal new task


COMMON_PASSWORDS = {  # the passwords attackers try first (a short list; a real app would check a much bigger one)
    "password", "password1", "password12", "password123", "password1234", "passw0rd", "12345678", "123456789", "1234567890",
    "qwerty123", "qwertyuiop", "1q2w3e4r", "1qaz2wsx", "abc12345", "abcd1234", "iloveyou", "11111111", "00000000",
    "12341234", "87654321", "welcome1", "welcome123", "letmein1", "admin123", "administrator", "sunshine1", "football1",
    "baseball1", "princess1", "dragon123", "monkey123", "pakistan", "pakistan1", "pakistan123", "karachi123", "lahore123",
    "taskmint", "taskmint1", "taskmint123", "computer", "internet", "starwars", "whatever", "trustno1",
}


class UserCreate(BaseModel):  # what someone SENDS to register
    model_config = STRICT  # reject unknown fields; trim spaces

    email: EmailStr  # must look like a real email address
    password: str = Field(min_length=8, max_length=128)  # at least 8 characters; capped so no one can send a 10 MB "password" to slow the server

    @model_validator(mode="after")  # runs after email and password are checked
    def not_a_weak_password(self) -> "UserCreate":  # refuse passwords attackers try first
        pw = self.password.lower()
        if pw in COMMON_PASSWORDS:  # on every "most common passwords" list
            raise ValueError("That password is too common. Pick something harder to guess.")
        if len(set(pw)) <= 2:  # "aaaaaaaa", "abababab"
            raise ValueError("That password is too simple. Mix different letters and numbers.")
        if self.email.split("@")[0].lower() in pw:  # contains the email's name ("ali123" for ali@...)
            raise ValueError("Your password shouldn't contain your email name.")
        return self


class UserRead(BaseModel):  # what the API SENDS BACK about a user (never the password or its hash)
    model_config = ConfigDict(from_attributes=True)  # allow building this from a database row

    id: int  # the user's number
    email: str  # their email
    created_at: datetime  # when they registered
    email_verified: bool = False  # did they click the verification link?
    email_reminders: bool = False  # the "email me reminders" switch


class Token(BaseModel):  # what /auth/login SENDS BACK
    access_token: str  # the signed login token
    token_type: str = "bearer"  # tells the client to send it as "Authorization: Bearer <token>"


class ReminderOut(BaseModel):  # a reminder that is due NOW (what the browser pops up)
    task_id: int  # which task
    kind: str  # before / at / after / morning / afternoon / evening
    title: str  # the task's title
    message: str  # ready-to-show text, e.g. "⏰ Gym at 8:00 PM, in 1 hour"


class ReminderUpcoming(BaseModel):  # a reminder still waiting (shown as 🔔 on tasks)
    task_id: int  # which task
    kind: str  # which of the 3
    send_at: datetime  # when it will pop up (UTC)


class SnoozeRequest(BaseModel):  # what POST /reminders/snooze RECEIVES
    model_config = STRICT  # no unknown fields
    task_id: DbId  # which task
    minutes: int = Field(default=10, ge=5, le=240)  # remind again in 5 minutes to 4 hours (no spam, no forever)


class UserSettings(BaseModel):  # what PATCH /auth/me RECEIVES
    model_config = STRICT  # no unknown fields (nobody can sneak in "email" or "password_hash")
    email_reminders: bool  # turn reminder emails on or off
