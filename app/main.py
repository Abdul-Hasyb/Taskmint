from fastapi import FastAPI  # import the FastAPI class, the core of our web app

app = FastAPI(title="FlowPilot", version="0.1.0")  # create the app; title and version show on the /docs page


@app.get("/health")  # when someone sends GET /health, run the function below
def health() -> dict[str, str]:  # returns a dictionary of text keys and text values
    return {"status": "ok"}  # FastAPI turns this into JSON: {"status": "ok"}

from datetime import datetime, timezone  # tools for working with dates and times
from typing import Literal  # lets us say "only these exact values are allowed"

from fastapi import FastAPI, HTTPException, status  # FastAPI app, error responses, status-code names
from pydantic import BaseModel, ConfigDict, Field, model_validator  # tools for describing and validating data

app = FastAPI(title="FlowPilot", version="0.1.0")  # create the app; title and version show on the /docs page

TaskStatus = Literal["todo", "in_progress", "done"]  # the only statuses a task can have


class TaskCreate(BaseModel):  # what the user must SEND to create a task
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)  # reject unknown fields; trim spaces from text

    title: str = Field(min_length=1, max_length=200)  # required; 1 to 200 characters
    description: str | None = Field(default=None, max_length=2000)  # optional; at most 2000 characters


class TaskUpdate(BaseModel):  # what the user may SEND to change a task; every field is optional
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)  # same safety rules as TaskCreate

    title: str | None = Field(default=None, min_length=1, max_length=200)  # new title, if changing it
    description: str | None = Field(default=None, max_length=2000)  # new description, if changing it
    status: TaskStatus | None = None  # new status, if changing it

    @model_validator(mode="after")  # runs after the fields above are checked
    def at_least_one_field(self) -> "TaskUpdate":  # make sure the update actually changes something
        if not self.model_fields_set:  # did the user send zero fields?
            raise ValueError("Send at least one field to update")  # yes: reject with 422
        if "title" in self.model_fields_set and self.title is None:  # did they try to set the title to null?
            raise ValueError("title cannot be null")  # a task must always have a title
        return self  # all good


class TaskRead(BaseModel):  # what the API SENDS BACK for a task
    id: int  # the task's unique number
    title: str  # the task's title
    description: str | None  # the task's description, or None if there isn't one
    status: TaskStatus  # one of: todo, in_progress, done
    created_at: datetime  # when the task was created (UTC time)


tasks: dict[int, TaskRead] = {}  # temporary storage: task id -> task (lost when the server restarts)
next_id = 1  # the id the next new task will get; only ever goes up


@app.get("/health")  # when someone sends GET /health, run the function below
def health() -> dict[str, str]:  # returns a dictionary of text keys and text values
    return {"status": "ok"}  # FastAPI turns this into JSON: {"status": "ok"}


@app.post("/tasks", status_code=status.HTTP_201_CREATED)  # POST /tasks creates a task; success = 201 Created
def create_task(task_in: TaskCreate) -> TaskRead:  # FastAPI checks the request body against TaskCreate first
    global next_id  # we change next_id, which lives outside this function
    task = TaskRead(  # build the full task from what the user sent plus what the server decides
        id=next_id,  # the server picks the id, never the user
        title=task_in.title,  # from the request
        description=task_in.description,  # from the request
        status="todo",  # every new task starts as "todo"
        created_at=datetime.now(timezone.utc),  # the current time in UTC
    )
    tasks[task.id] = task  # save it in storage under its id
    next_id += 1  # move the counter up for the next task
    return task  # FastAPI turns it into JSON and sends it back


@app.get("/tasks")  # GET /tasks lists all tasks
def list_tasks() -> list[TaskRead]:  # returns a list of tasks
    return list(tasks.values())  # every saved task, as a list


@app.get("/tasks/{task_id}")  # GET /tasks/5 fetches task 5; {task_id} is read from the URL
def get_task(task_id: int) -> TaskRead:  # FastAPI checks task_id is a whole number first
    if task_id not in tasks:  # is there a task with this id?
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")  # no: send 404
    return tasks[task_id]  # yes: send it back


@app.patch("/tasks/{task_id}")  # PATCH /tasks/5 changes some fields of task 5
def update_task(task_id: int, changes: TaskUpdate) -> TaskRead:  # FastAPI checks the body against TaskUpdate first
    if task_id not in tasks:  # is there a task with this id?
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")  # no: send 404
    updates = changes.model_dump(exclude_unset=True)  # only the fields the user actually sent
    updated_task = tasks[task_id].model_copy(update=updates)  # a copy of the task with those fields changed
    tasks[task_id] = updated_task  # save the new version
    return updated_task  # send it back


@app.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)  # DELETE /tasks/5 removes task 5; success = 204
def delete_task(task_id: int) -> None:  # 204 means "done, nothing to send back"
    if task_id not in tasks:  # is there a task with this id?
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")  # no: send 404
    del tasks[task_id]  # remove it from storage