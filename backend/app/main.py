from fastapi import FastAPI

from app.api.main import api_router
from app.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    # The schema documents an internal contract, so only development exposes it.
    openapi_url=(
        f"{settings.API_PREFIX}/openapi.json"
        if settings.FASTAPI_ENV == "development"
        else None
    ),
)

app.include_router(api_router, prefix=settings.API_PREFIX)
