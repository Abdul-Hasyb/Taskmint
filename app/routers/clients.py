from fastapi import APIRouter, Depends, HTTPException, status  # APIRouter = a group of related endpoints
from sqlalchemy import func, select, update  # func.count = COUNT(...), update = UPDATE ... SET ...
from sqlalchemy.orm import Session  # the type of a database conversation

from app.database import get_db  # hands each request its own database session
from app.models import Client, Task, User  # the clients, tasks and users TABLES
from app.schemas import ClientCreate, ClientRead, ClientUpdate, TaskRead  # what users send and what we send back
from app.security import get_current_user  # "who is logged in?" (401 if nobody)

router = APIRouter(prefix="/clients", tags=["clients"])  # every endpoint here starts with /clients


def find_client_or_404(db: Session, client_id: int, user: User) -> Client:  # get one of THIS user's clients, or 404
    client = db.scalar(select(Client).where(Client.id == client_id, Client.user_id == user.id))  # must match the id AND belong to this user
    if client is None:  # doesn't exist, or belongs to someone else (we don't say which)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")  # send 404
    return client  # found it


def count_open_tasks(db: Session, client_id: int) -> int:  # how many of this client's tasks are not done
    query = select(func.count()).select_from(Task).where(Task.client_id == client_id, Task.status != "done")  # SELECT COUNT(*) ... WHERE ...
    return db.scalar(query) or 0  # the number (0 if none)


def to_read(db: Session, client: Client) -> ClientRead:  # build the reply, including the open-task count
    reply = ClientRead.model_validate(client)  # copy the stored fields
    reply.open_tasks = count_open_tasks(db, client.id)  # add the calculated count
    return reply  # done


@router.post("", status_code=status.HTTP_201_CREATED)  # POST /clients creates a client
def create_client(client_in: ClientCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> ClientRead:
    client = Client(name=client_in.name, notes=client_in.notes, user_id=user.id)  # a new row, owned by this user
    db.add(client)  # put it in the "to save" pile
    db.commit()  # save permanently
    db.refresh(client)  # reload to get the id
    return to_read(db, client)  # send it back (open_tasks = 0)


@router.get("")  # GET /clients lists THIS user's clients
def list_clients(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[ClientRead]:
    clients = db.scalars(select(Client).where(Client.user_id == user.id).order_by(Client.name)).all()  # only MY clients, by name
    return [to_read(db, client) for client in clients]  # convert each one


@router.get("/{client_id}")  # GET /clients/3 fetches client 3 (only if it's mine)
def get_client(client_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> ClientRead:
    return to_read(db, find_client_or_404(db, client_id, user))  # find it (or 404) and send it back


@router.get("/{client_id}/tasks")  # GET /clients/3/tasks = the client page (only if it's mine)
def list_client_tasks(client_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[TaskRead]:
    find_client_or_404(db, client_id, user)  # 404 if the client isn't mine
    tasks = db.scalars(select(Task).where(Task.client_id == client_id, Task.user_id == user.id).order_by(Task.id)).all()  # their tasks
    return [TaskRead.model_validate(task) for task in tasks]  # convert each one


@router.patch("/{client_id}")  # PATCH /clients/3 changes client 3 (only if it's mine)
def update_client(client_id: int, changes: ClientUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> ClientRead:
    client = find_client_or_404(db, client_id, user)  # find it (or 404)
    for field, value in changes.model_dump(exclude_unset=True).items():  # only the fields the user sent
        setattr(client, field, value)  # e.g. client.name = "Bilal Khan"
    db.commit()  # save
    db.refresh(client)  # reload
    return to_read(db, client)  # send it back


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)  # DELETE /clients/3 removes client 3 (only if it's mine)
def delete_client(client_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    client = find_client_or_404(db, client_id, user)  # find it (or 404)
    db.execute(update(Task).where(Task.client_id == client_id).values(client_id=None))  # unlink their tasks first (tasks are kept)
    db.execute(update(Task).where(Task.assignee_id == client_id).values(assignee_id=None))  # tasks they were doing come back to me
    db.delete(client)  # then delete the client
    db.commit()  # both changes saved together
