from contextlib import asynccontextmanager

from fastapi import FastAPI
from langchain_openai import OpenAIEmbeddings
from langgraph.store.postgres import AsyncPostgresStore

from app.agent.graph import build_graph
from app.agent.grounding import OpenAIGroundingValidator
from app.agent.memory import MemoryExtractor
from app.agent.memory_tool import create_search_memories_tool
from app.agent.tools import calculator
from app.api.main import api_router
from app.core.config import settings
from app.core.db import engine
from app.core.supabase import (
    create_supabase_auth_client,
    create_supabase_storage_client,
)
from app.models.document import EMBEDDING_DIMENSIONS
from app.rag.reranking import CohereReranker
from app.rag.retrieval import create_search_documents_tool
from app.rag.runner import DocumentIndexingRunner
from app.rag.web import create_search_web_tool
from app.storage.documents import DocumentStorage


@asynccontextmanager
async def lifespan(app: FastAPI):
    supabase_auth = create_supabase_auth_client()
    supabase_storage = create_supabase_storage_client()
    embeddings = OpenAIEmbeddings(
        model=settings.OPENAI_EMBEDDING_MODEL,
        dimensions=EMBEDDING_DIMENSIONS,
        api_key=settings.OPENAI_API_KEY,
        request_timeout=120,
        max_retries=1,
    )
    app.state.supabase_auth = supabase_auth
    document_storage = DocumentStorage(
        supabase_storage,
        settings.SUPABASE_STORAGE_BUCKET,
    )
    app.state.document_storage = document_storage
    reranker = CohereReranker(api_key=settings.COHERE_API_KEY)
    app.state.grounding_validator = OpenAIGroundingValidator(
        model=settings.OPENAI_GROUNDING_MODEL,
        api_key=settings.OPENAI_API_KEY,
    )
    app.state.memory_extractor = MemoryExtractor(
        model=settings.OPENAI_MEMORY_EXTRACTION_MODEL,
        api_key=settings.OPENAI_API_KEY,
    )
    indexing_runner = DocumentIndexingRunner.for_database(
        engine=engine,
        storage=document_storage,
        embeddings=embeddings,
        embedding_model=settings.OPENAI_EMBEDDING_MODEL,
    )
    app.state.indexing_runner = indexing_runner

    # The memory index embeds saved memories so they can be recalled by meaning.
    async with AsyncPostgresStore.from_conn_string(
        str(settings.DATABASE_URL),
        index={
            "dims": EMBEDDING_DIMENSIONS,
            "embed": embeddings,
            "fields": ["memory"],
        },
    ) as memory_index:
        app.state.memory_index = memory_index
        app.state.graph = build_graph(
            model=settings.OPENAI_MAIN_MODEL,
            api_key=settings.OPENAI_API_KEY,
            tools=[
                create_search_documents_tool(
                    engine=engine,
                    embeddings=embeddings,
                    reranker=reranker,
                ),
                create_search_web_tool(
                    api_key=settings.TAVILY_API_KEY,
                    engine=engine,
                ),
                create_search_memories_tool(),
                calculator,
            ],
            store=memory_index,
        )
        await indexing_runner.start()
        try:
            yield
        finally:
            await indexing_runner.stop()
            reranker.close()
            supabase_auth.auth.close()
            supabase_storage.auth.close()


app = FastAPI(
    title=settings.PROJECT_NAME,
    # The schema documents an internal contract, so only development exposes it.
    openapi_url=(
        f"{settings.API_PREFIX}/openapi.json"
        if settings.FASTAPI_ENV == "development"
        else None
    ),
    lifespan=lifespan,
)

app.include_router(api_router, prefix=settings.API_PREFIX)
