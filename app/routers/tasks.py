from fastapi import APIRouter, Depends, HTTPException, Query, status  # APIRouter = a group of related endpoints; Query = settings for ?filters
from sqlalchemy import select  # builds SELECT queries
from sqlalchemy.orm import Session  # the type of a database conversation

from app.database import get_db  # hands each request its own database session
from app.models import Client, Task  # the tasks and clients TABLES
from app.schemas import TaskCreate, TaskRead, TaskStatus, TaskUpdate  # what users send and what we send back

router = APIRouter(prefix="/tasks", tags=["tasks"])  # every endpoint here starts with /tasks; grouped as "tasks" in /docs


def find_task_or_404(db: Session, task_id: int) -> Task:  # shared helper: get a task or send 404
    task = db.get(Task, task_id)  # look it up by its id
    if task is None:  # no row with this id?
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")  # send 404
    return task  # found it


def check_client_exists(db: Session, client_id: int | None) -> None:  # a task can only point at a real client
    if client_id is not None and db.get(Client, client_id) is None:  # an id was given, but no such client?
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Client {client_id} does not exist")  # reject


@router.post("", status_code=status.HTTP_201_CREATED)  # POST /tasks creates a task; success = 201 Created
def create_task(task_in: TaskCreate, db: Session = Depends(get_db)) -> TaskRead:  # body checked against TaskCreate
    check_client_exists(db, task_in.client_id)  # stop here if the client id is fake
    task = Task(title=task_in.title, description=task_in.description, client_id=task_in.client_id)  # a new row
    db.add(task)  # put it in the "to save" pile
    db.commit()  # save it permanently
    db.refresh(task)  # reload it to get the id and created_at
    return TaskRead.model_validate(task)  # send it back


@router.get("")  # GET /tasks lists tasks; optional filters: /tasks?status=todo&client_id=3
def list_tasks(
    status_filter: TaskStatus | None = Query(default=None, alias="status"),  # ?status=todo (named status_filter inside, so it doesn't clash with FastAPI's "status")
    client_id: int | None = None,  # ?client_id=3
    db: Session = Depends(get_db),  # the database session
) -> list[TaskRead]:  # returns a list of tasks
    query = select(Task).order_by(Task.id)  # start with: all tasks, oldest first
    if status_filter is not None:  # ?status=... given?
        query = query.where(Task.status == status_filter)  # keep only that status
    if client_id is not None:  # ?client_id=... given?
        query = query.where(Task.client_id == client_id)  # keep only that client's tasks
    return [TaskRead.model_validate(task) for task in db.scalars(query).all()]  # run it and convert each row


@router.get("/{task_id}")  # GET /tasks/5 fetches task 5
def get_task(task_id: int, db: Session = Depends(get_db)) -> TaskRead:  # task_id must be a whole number
    return TaskRead.model_validate(find_task_or_404(db, task_id))  # find it (or 404) and send it back


@router.patch("/{task_id}")  # PATCH /tasks/5 changes some fields of task 5
def update_task(task_id: int, changes: TaskUpdate, db: Session = Depends(get_db)) -> TaskRead:  # body checked first
    task = find_task_or_404(db, task_id)  # find it (or 404)
    updates = changes.model_dump(exclude_unset=True)  # only the fields the user actually sent
    if "client_id" in updates:  # moving the task to a client?
        check_client_exists(db, updates["client_id"])  # that client must exist (null is fine)
    for field, value in updates.items():  # apply each change
        setattr(task, field, value)  # e.g. task.status = "done"
    db.commit()  # save the changes
    db.refresh(task)  # reload the saved version
    return TaskRead.model_validate(task)  # send it back


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)  # DELETE /tasks/5 removes task 5
def delete_task(task_id: int, db: Session = Depends(get_db)) -> None:  # 204 = done, nothing to send back
    task = find_task_or_404(db, task_id)  # find it (or 404)
    db.delete(task)  # mark it for deletion
    db.commit()  # delete it permanently