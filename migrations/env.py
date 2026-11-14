from logging.config import fileConfig  # sets up Alembic's log messages

from alembic import context  # Alembic's view of the current migration run
from sqlalchemy import engine_from_config, pool  # tools to open a database connection

from app.database import DATABASE_URL, Base  # our database address (from .env) and the table definitions' parent
import app.models  # noqa: F401  (loads every table class, so Alembic can see them)

config = context.config  # the settings from alembic.ini
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))  # use the address from .env, never one written in alembic.ini

if config.config_file_name is not None:  # if alembic.ini exists...
    fileConfig(config.config_file_name)  # ...use its logging settings

target_metadata = Base.metadata  # what the database SHOULD look like (from models.py); autogenerate compares against this


def run_migrations_offline() -> None:  # writes the SQL to the screen instead of running it (rarely used)
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)  # settings for offline mode
    with context.begin_transaction():  # wrap everything in one transaction
        context.run_migrations()  # produce the SQL


def run_migrations_online() -> None:  # connects to the database and applies the changes (the normal way)
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)  # a one-off connection
    with connectable.connect() as connection:  # open it (closed automatically at the end)
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=connection.dialect.name == "sqlite")  # batch mode lets SQLite change tables too
        with context.begin_transaction():  # all changes succeed together or none do
            context.run_migrations()  # apply the changes


if context.is_offline_mode():  # did someone ask for offline mode?
    run_migrations_offline()  # yes
else:  # no (the normal case)
    run_migrations_online()  # connect and migrate