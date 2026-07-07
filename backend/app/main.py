from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.admin import router as admin_router
from app.api.consumer import router as consumer_router
from app.core.config import settings
from app.core.database import init_db


STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(admin_router)
    app.include_router(consumer_router)

    @app.on_event("startup")
    def startup() -> None:
        init_db()

    @app.get("/")
    def root():
        if INDEX_FILE.exists():
            return FileResponse(INDEX_FILE)
        return {"ok": True, "app": settings.app_name}

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "app": settings.app_name}

    assets_dir = STATIC_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    return app


app = create_app()
