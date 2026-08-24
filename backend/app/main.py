from contextlib import asynccontextmanager

from fastapi import FastAPI
from langchain_openai import OpenAIEmbeddings

from app.agent.graph import build_graph
from app.agent.tools import calculator
from app.api.main import api_router
from app.core.config import settings
from app.core.db import engine
from app.core.supabase import (
    create_supabase_auth_client,
    create_supabase_storage_client,
)
from app.models.document import EMBEDDING_DIMENSIONS
from app.rag.runner import DocumentIndexingRunner
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
    app.state.graph = build_graph(
        model=settings.OPENAI_MAIN_MODEL,
        api_key=settings.OPENAI_API_KEY,
        tools=[calculator],
    )
    indexing_runner = DocumentIndexingRunner.for_database(
        engine=engine,
        storage=document_storage,
        embeddings=embeddings,
        embedding_model=settings.OPENAI_EMBEDDING_MODEL,
    )
    app.state.indexing_runner = indexing_runner
    await indexing_runner.start()
    try:
        yield
    finally:
        await indexing_runner.stop()
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
