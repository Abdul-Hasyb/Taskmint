import os  # lets Python read environment variables

from dotenv import load_dotenv  # reads the .env file into environment variables
from sqlalchemy import MetaData, create_engine, text  # create_engine = the connection to the database; text = raw SQL; MetaData = table settings
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker  # tools for tables and conversations with the database
from sqlalchemy.pool import StaticPool  # keeps ONE shared connection (needed for the tests' in-memory database)

load_dotenv()  # read .env, so os.getenv can see DATABASE_URL

DATABASE_URL = os.getenv("DATABASE_URL")  # the database address + password, from .env (never written in code)
if not DATABASE_URL:  # .env missing or the line is empty?
    raise RuntimeError("DATABASE_URL is not set. Add it to your .env file.")  # stop with a clear message

if DATABASE_URL.startswith("sqlite"):  # the tests use a tiny throwaway SQLite database in memory
    engine = create_engine(  # SQLite needs two special settings to work with FastAPI and tests
        DATABASE_URL,  # e.g. "sqlite://" = in memory, gone when the tests finish
        connect_args={"check_same_thread": False},  # allow FastAPI's worker threads to share it
        poolclass=StaticPool,  # every part of the app sees the same in-memory database
    )
else:  # the real database (Supabase PostgreSQL)
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)  # pre_ping re-checks old connections before use

SessionLocal = sessionmaker(bind=engine, autoflush=False)  # a factory that makes one "conversation" with the database


NAMING_CONVENTION = {  # gives every index and link between tables a predictable name, so migrations can find and change them later
    "ix": "ix_%(column_0_label)s",  # indexes: ix_tasks_client_id
    "uq": "uq_%(table_name)s_%(column_0_name)s",  # unique rules
    "ck": "ck_%(table_name)s_%(constraint_name)s",  # check rules
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",  # foreign keys: fk_tasks_client_id_clients
    "pk": "pk_%(table_name)s",  # primary keys
}


class Base(DeclarativeBase):  # every table class will inherit from this
    metadata = MetaData(naming_convention=NAMING_CONVENTION)  # use the naming rules above


def get_db():  # FastAPI calls this for every request that needs the database
    db: Session = SessionLocal()  # open a conversation with the database
    try:  # hand it to the endpoint...
        yield db  # ...the endpoint uses it here...
    finally:  # ...and no matter what happens (even an error)...
        db.close()  # ...close the conversation, so connections don't leak


if __name__ == "__main__":  # only runs when this file is run directly: python -m app.database
    with engine.connect() as connection:  # open a connection (closed automatically at the end)
        result = connection.execute(text("SELECT 1")).scalar()  # the simplest possible question: "what is 1?"
        print("Connected! The database answered:", result)  # if we get here, the connection works
        print("Database type:", engine.dialect.name, engine.dialect.server_version_info)  # e.g. postgresql (17, 4)