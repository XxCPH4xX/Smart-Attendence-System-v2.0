from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from backend.api import router
from backend.biometrics import VisionService
from backend.config import get_settings
from backend.db import make_engine, session_factory


class BodyLimit:
    def __init__(self, app, limit=32_000_000):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        size = 0

        async def limited_receive():
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > self.limit:
                from starlette.exceptions import HTTPException

                raise HTTPException(413, "Request body is too large")
            return message

        await self.app(scope, limited_receive, send)


def create_app(settings=None, engine=None):
    settings = settings or get_settings()
    Path("data").mkdir(mode=0o700, exist_ok=True)
    database = engine or make_engine(settings.database_url)
    vision = VisionService(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        vision.close()
        database.dispose()

    app = FastAPI(title="Smart Attendance API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.sessions = session_factory(database)
    app.state.vision = vision
    app.add_middleware(BodyLimit)
    app.include_router(router)

    @app.middleware("http")
    async def response_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(IntegrityError)
    async def conflict(request, error):
        return JSONResponse(
            status_code=409, content={"detail": "Duplicate record or conflicting reference"}
        )

    @app.exception_handler(StaleDataError)
    async def stale(request, error):
        return JSONResponse(
            status_code=409, content={"detail": "Record changed; refresh and retry"}
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
