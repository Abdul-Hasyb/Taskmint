from contextlib import asynccontextmanager  # lets us run code when the app starts and stops

from fastapi import Depends, FastAPI, HTTPException, status  # FastAPI tools; Depends = "give me this for each request"
from sqlalchemy import select  # builds SELECT queries ("read rows from a table")
from sqlalchemy.orm import Session  # the type of a database conversation

from app.database import Base, engine, get_db  # our database connection and helpers
from app.models import Task  # the tasks TABLE
from app.schemas import TaskCreate, TaskRead, TaskUpdate  # what users send and what we send back


@asynccontextmanager  # turns the function below into a start-up/shut-down handler
async def lifespan(app: FastAPI):  # runs once when the server starts
    Base.metadata.create_all(engine)  # create any tables that don't exist yet (existing ones are left alone)
    yield  # the app runs while we're paused here


app = FastAPI(title="Taskmint", version="0.2.0", lifespan=lifespan)  # create the app; version bumped for the database


def find_task_or_404(db: Session, task_id: int) -> Task:  # shared helper: get a task or send 404
    task = db.get(Task, task_id)  # look it up by its id (primary key)
    if task is None:  # no row with this id?
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")  # send 404
    return task  # found it


@app.get("/health")  # when someone sends GET /health, run the function below
def health() -> dict[str, str]:  # returns a dictionary of text keys and text values
    return {"status": "ok"}  # FastAPI turns this into JSON: {"status": "ok"}


@app.post("/tasks", status_code=status.HTTP_201_CREATED)  # POST /tasks creates a task; success = 201 Created
def create_task(task_in: TaskCreate, db: Session = Depends(get_db)) -> TaskRead:  # FastAPI validates the body AND opens a db session
    task = Task(title=task_in.title, description=task_in.description)  # a new row; id, status and created_at are filled automatically
    db.add(task)  # put it in the "to save" pile
    db.commit()  # save it permanently in the database
    db.refresh(task)  # reload it, so we get the id and created_at the database just set
    return TaskRead.model_validate(task)  # convert the database row into our response format


@app.get("/tasks")  # GET /tasks lists all tasks
def list_tasks(db: Session = Depends(get_db)) -> list[TaskRead]:  # returns a list of tasks
    rows = db.scalars(select(Task).order_by(Task.id)).all()  # SELECT * FROM tasks ORDER BY id
    return [TaskRead.model_validate(task) for task in rows]  # convert each row into our response format


@app.get("/tasks/{task_id}")  # GET /tasks/5 fetches task 5
def get_task(task_id: int, db: Session = Depends(get_db)) -> TaskRead:  # task_id must be a whole number
    return TaskRead.model_validate(find_task_or_404(db, task_id))  # find it (or 404) and send it back


@app.patch("/tasks/{task_id}")  # PATCH /tasks/5 changes some fields of task 5
def update_task(task_id: int, changes: TaskUpdate, db: Session = Depends(get_db)) -> TaskRead:  # body checked against TaskUpdate
    task = find_task_or_404(db, task_id)  # find it (or 404)
    for field, value in changes.model_dump(exclude_unset=True).items():  # only the fields the user actually sent
        setattr(task, field, value)  # e.g. task.status = "done"
    db.commit()  # save the changes
    db.refresh(task)  # reload the saved version
    return TaskRead.model_validate(task)  # send it back


@app.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)  # DELETE /tasks/5 removes task 5
def delete_task(task_id: int, db: Session = Depends(get_db)) -> None:  # 204 = done, nothing to send back
    task = find_task_or_404(db, task_id)  # find it (or 404)
    db.delete(task)  # mark it for deletion
    db.commit()  # delete it permanently