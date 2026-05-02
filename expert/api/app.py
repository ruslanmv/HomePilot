from fastapi import FastAPI
from expert.api.chat import router as chat_router
from expert.api.sessions import router as sessions_router
from expert.api.uploads import router as uploads_router
from expert.api.streaming import router as streaming_router
from expert.api.history import router as history_router
from expert.settings import settings


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)

    @app.get("/health")
    async def health():
        return {"status": "ok", "app": settings.app_name}

    app.include_router(chat_router, prefix="/api")
    app.include_router(sessions_router, prefix="/api")
    app.include_router(uploads_router, prefix="/api")
    app.include_router(streaming_router, prefix="/api")
    app.include_router(history_router, prefix="/api")
    return app
