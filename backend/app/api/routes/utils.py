from fastapi import APIRouter

router = APIRouter(prefix="/utils", tags=["utils"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Report that the process is serving requests."""

    return {"status": "ok"}
