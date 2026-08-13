from sqlalchemy import Column, Table, Uuid
from sqlmodel import SQLModel

# Marks tables that another system owns, so migrations never try to manage them.
EXTERNALLY_MANAGED = "externally_managed"

# Supabase Auth owns this table. It is declared only so application foreign keys
# can reference the authenticated user.
AUTH_USERS_TABLE = Table(
    "users",
    SQLModel.metadata,
    Column("id", Uuid(), primary_key=True),
    schema="auth",
    info={EXTERNALLY_MANAGED: True},
)
