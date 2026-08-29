"""Create the LangGraph store tables the memory index needs.

Run from the database bootstrap script. Application startup never migrates.
"""

import asyncio

from langgraph.store.postgres import AsyncPostgresStore

from app.core.config import settings
from app.models.document import EMBEDDING_DIMENSIONS


async def bootstrap_memory_store(*, database_url: str) -> None:
    async with AsyncPostgresStore.from_conn_string(
        database_url,
        index={
            # Setup only creates tables, so no provider call is made here.
            "dims": EMBEDDING_DIMENSIONS,
            "embed": lambda _texts: [],
            "fields": ["memory"],
        },
    ) as store:
        await store.setup()


def main() -> None:
    asyncio.run(bootstrap_memory_store(database_url=str(settings.DATABASE_URL)))


if __name__ == "__main__":
    main()
