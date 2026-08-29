from fastapi import APIRouter

from app.api.routes import chats, documents, memories, utils

api_router = APIRouter()
api_router.include_router(chats.router)
api_router.include_router(documents.router)
api_router.include_router(memories.router)
api_router.include_router(utils.router)
