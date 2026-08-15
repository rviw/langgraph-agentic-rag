from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.main import api_router
from app.core.config import settings
from app.core.supabase import create_supabase_auth_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    supabase_auth = create_supabase_auth_client()
    app.state.supabase_auth = supabase_auth
    try:
        yield
    finally:
        supabase_auth.auth.close()


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
