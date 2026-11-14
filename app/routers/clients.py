from fastapi import APIRouter, Depends, HTTPException, status  # APIRouter = a group of related endpoints
from sqlalchemy import func, select, update  # func.count = COUNT(...), update = UPDATE ... SET ...
from sqlalchemy.orm import Session  # the type of a database conversation

from app.database import get_db  # hands each request its own database session
from app.models import Client, Task  # the clients and tasks TABLES
from app.schemas import ClientCreate, ClientRead, ClientUpdate, TaskRead  # what users send and what we send back

router = APIRouter(prefix="/clients", tags=["clients"])  # every endpoint here starts with /clients; grouped as "clients" in /docs


def find_client_or_404(db: Session, client_id: int) -> Client:  # shared helper: get a client or send 404
    client = db.get(Client, client_id)  # look it up by its id
    if client is None:  # no such client?
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
def create_client(client_in: ClientCreate, db: Session = Depends(get_db)) -> ClientRead:  # body checked against ClientCreate
    client = Client(name=client_in.name, notes=client_in.notes)  # a new row
    db.add(client)  # put it in the "to save" pile
    db.commit()  # save permanently
    db.refresh(client)  # reload to get the id
    return to_read(db, client)  # send it back (open_tasks = 0)


@router.get("")  # GET /clients lists all clients
def list_clients(db: Session = Depends(get_db)) -> list[ClientRead]:  # each with their open-task count
    clients = db.scalars(select(Client).order_by(Client.name)).all()  # SELECT * FROM clients ORDER BY name
    return [to_read(db, client) for client in clients]  # convert each one


@router.get("/{client_id}")  # GET /clients/3 fetches client 3
def get_client(client_id: int, db: Session = Depends(get_db)) -> ClientRead:  # client_id must be a whole number
    return to_read(db, find_client_or_404(db, client_id))  # find it (or 404) and send it back


@router.get("/{client_id}/tasks")  # GET /clients/3/tasks = the client page: all of client 3's tasks
def list_client_tasks(client_id: int, db: Session = Depends(get_db)) -> list[TaskRead]:  # their tasks, oldest first
    find_client_or_404(db, client_id)  # 404 if the client doesn't exist
    tasks = db.scalars(select(Task).where(Task.client_id == client_id).order_by(Task.id)).all()  # their tasks
    return [TaskRead.model_validate(task) for task in tasks]  # convert each one


@router.patch("/{client_id}")  # PATCH /clients/3 changes client 3
def update_client(client_id: int, changes: ClientUpdate, db: Session = Depends(get_db)) -> ClientRead:  # body checked first
    client = find_client_or_404(db, client_id)  # find it (or 404)
    for field, value in changes.model_dump(exclude_unset=True).items():  # only the fields the user sent
        setattr(client, field, value)  # e.g. client.name = "Bilal Khan"
    db.commit()  # save
    db.refresh(client)  # reload
    return to_read(db, client)  # send it back


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)  # DELETE /clients/3 removes client 3
def delete_client(client_id: int, db: Session = Depends(get_db)) -> None:  # their tasks are KEPT, just without a client
    client = find_client_or_404(db, client_id)  # find it (or 404)
    db.execute(update(Task).where(Task.client_id == client_id).values(client_id=None))  # unlink their tasks first
    db.delete(client)  # then delete the client
    db.commit()  # both changes saved together