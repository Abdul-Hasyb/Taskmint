from fastapi import APIRouter, Depends, HTTPException, Query, status  # APIRouter = a group of related endpoints; Query = settings for ?filters
from sqlalchemy import select  # builds SELECT queries
from sqlalchemy.orm import Session  # the type of a database conversation

from app.database import get_db  # hands each request its own database session
from app.models import Client, Task, User, utc_now  # the tasks, clients and users TABLES; utc_now = the time right now
from app.routers.reminders import delete_reminders, plan_reminders  # the 3-reminders rules
from app.schemas import TaskCreate, TaskRead, TaskStatus, TaskUpdate  # what users send and what we send back
from app.security import get_current_user  # "who is logged in?" (401 if nobody)

router = APIRouter(prefix="/tasks", tags=["tasks"])  # every endpoint here starts with /tasks; grouped as "tasks" in /docs


def find_task_or_404(db: Session, task_id: int, user: User) -> Task:  # get one of THIS user's tasks, or 404
    task = db.scalar(select(Task).where(Task.id == task_id, Task.user_id == user.id))  # must match the id AND belong to this user
    if task is None:  # doesn't exist, or belongs to someone else (we don't say which)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")  # send 404
    return task  # found it


def check_client_exists(db: Session, client_id: int | None, user: User) -> None:  # a task can only point at one of THIS user's clients
    if client_id is None:  # no client given: fine
        return  # nothing to check
    if db.scalar(select(Client.id).where(Client.id == client_id, Client.user_id == user.id)) is None:  # not theirs, or doesn't exist
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Client {client_id} does not exist")  # reject


@router.post("", status_code=status.HTTP_201_CREATED)  # POST /tasks creates a task; success = 201 Created
def create_task(task_in: TaskCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> TaskRead:  # login required
    check_client_exists(db, task_in.client_id, user)  # stop here if the client isn't theirs
    check_client_exists(db, task_in.assignee_id, user)  # same for the person doing it
    task = Task(**task_in.model_dump(), user_id=user.id)  # every field the user sent (title, due_date...), owned by this user
    db.add(task)  # put it in the "to save" pile
    db.commit()  # save it permanently
    db.refresh(task)  # reload it to get the id and created_at
    plan_reminders(db, task)  # its 3 reminders
    db.commit()  # save them
    return TaskRead.model_validate(task)  # send it back


@router.get("")  # GET /tasks lists THIS user's tasks; optional filters: /tasks?status=todo&client_id=3
def list_tasks(
    status_filter: TaskStatus | None = Query(default=None, alias="status"),  # ?status=todo
    client_id: int | None = None,  # ?client_id=3
    assignee_id: int | None = None,  # ?assignee_id=4 = only tasks that person is doing
    db: Session = Depends(get_db),  # the database session
    user: User = Depends(get_current_user),  # the logged-in user
) -> list[TaskRead]:  # returns a list of tasks
    query = select(Task).where(Task.user_id == user.id).order_by(Task.id)  # start with: only MY tasks, oldest first
    if status_filter is not None:  # ?status=... given?
        query = query.where(Task.status == status_filter)  # keep only that status
    if client_id is not None:  # ?client_id=... given?
        query = query.where(Task.client_id == client_id)  # keep only that client's tasks
    if assignee_id is not None:  # ?assignee_id=... given?
        query = query.where(Task.assignee_id == assignee_id)  # keep only the tasks that person is doing
    return [TaskRead.model_validate(task) for task in db.scalars(query).all()]  # run it and convert each row


@router.get("/{task_id}")  # GET /tasks/5 fetches task 5 (only if it's mine)
def get_task(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> TaskRead:
    return TaskRead.model_validate(find_task_or_404(db, task_id, user))  # find it (or 404) and send it back


@router.patch("/{task_id}")  # PATCH /tasks/5 changes some fields of task 5 (only if it's mine)
def update_task(task_id: int, changes: TaskUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> TaskRead:
    task = find_task_or_404(db, task_id, user)  # find it (or 404)
    updates = changes.model_dump(exclude_unset=True)  # only the fields the user actually sent
    if "client_id" in updates:  # moving the task to a client?
        check_client_exists(db, updates["client_id"], user)  # that client must be theirs (null is fine)
    if "assignee_id" in updates:  # giving the task to someone?
        check_client_exists(db, updates["assignee_id"], user)  # they must be on MY People list
    for field, value in updates.items():  # apply each change
        setattr(task, field, value)  # e.g. task.status = "done"
    if "status" in updates:  # status changed?
        if task.status == "done" and task.completed_at is None:  # just finished
            task.completed_at = utc_now()  # remember WHEN (the charts count this)
        elif task.status != "done":  # un-ticked, or back to in progress
            task.completed_at = None  # not finished any more
    if "due_date" in updates and updates["due_date"] is None:  # due date removed?
        task.due_time = None  # then the time goes too
    if task.due_time is not None and task.due_date is None:  # a time but no day?
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="due_time needs a due_date")  # nothing saved
    plan_reminders(db, task)  # new time or ticked done? re-plan (done = no more reminders)
    db.commit()  # save the changes
    db.refresh(task)  # reload the saved version
    return TaskRead.model_validate(task)  # send it back


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)  # DELETE /tasks/5 removes task 5 (only if it's mine)
def delete_task(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    task = find_task_or_404(db, task_id, user)  # find it (or 404)
    delete_reminders(db, task.id)  # its reminders go first (they point at it)
    db.delete(task)  # mark it for deletion
    db.commit()  # delete it permanently
