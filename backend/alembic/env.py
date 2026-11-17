"""Alembic environment. Migrations are hand-written (no autogenerate), so no
target metadata. Uses the connection handed over by app.db.init_db(), or the
app's engine when run from the CLI."""
from alembic import context

config = context.config


def run_migrations() -> None:
    connection = config.attributes.get("connection")
    if connection is None:
        from app.db import engine_db
        with engine_db.begin() as connection:
            context.configure(connection=connection, target_metadata=None)
            with context.begin_transaction():
                context.run_migrations()
        return
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()


run_migrations()
