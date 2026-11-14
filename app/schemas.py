from datetime import datetime  # the date-and-time type
from typing import Literal  # lets us say "only these exact values are allowed"

from pydantic import BaseModel, ConfigDict, Field, model_validator  # tools for describing and validating data

TaskStatus = Literal["todo", "in_progress", "done"]  # the only statuses a task can have
STRICT = ConfigDict(extra="forbid", str_strip_whitespace=True)  # shared safety rules: reject unknown fields, trim spaces


class TaskCreate(BaseModel):  # what the user must SEND to create a task
    model_config = STRICT  # reject unknown fields; trim spaces from text

    title: str = Field(min_length=1, max_length=200)  # required; 1 to 200 characters
    description: str | None = Field(default=None, max_length=2000)  # optional; at most 2000 characters
    client_id: int | None = None  # optional: which client this task is for


class TaskUpdate(BaseModel):  # what the user may SEND to change a task; every field is optional
    model_config = STRICT  # same safety rules as TaskCreate

    title: str | None = Field(default=None, min_length=1, max_length=200)  # new title, if changing it
    description: str | None = Field(default=None, max_length=2000)  # new description, if changing it
    status: TaskStatus | None = None  # new status, if changing it
    client_id: int | None = None  # move the task to another client, or null to remove the client

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