from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import create_engine, pool
from sqlmodel import SQLModel

from app import models  # noqa: F401  (import registers the application tables)
from app.core.config import settings
from app.models.auth import EXTERNALLY_MANAGED

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata

# The LangGraph store owns these tables and applies its own setup routine.
LANGGRAPH_TABLES = frozenset(
    {
        "store",
        "store_migrations",
        "store_vectors",
        "vector_migrations",
    }
)


def include_object(
    object_: Any,
    _name: str | None,
    type_: str,
    _reflected: bool,
    _compare_to: object | None,
) -> bool:
    """Exclude tables owned by Supabase Auth and by the LangGraph store."""

    owning_table = object_ if type_ == "table" else getattr(object_, "table", None)
    if owning_table is None:
        return True
    if owning_table.info.get(EXTERNALLY_MANAGED) or owning_table.schema == "auth":
        return False
    return not (
        owning_table.schema in (None, "public")
        and owning_table.name in LANGGRAPH_TABLES
    )


def run_migrations_offline() -> None:
    context.configure(
        url=settings.sqlalchemy_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        settings.sqlalchemy_database_url,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
