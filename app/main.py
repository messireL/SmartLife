from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.api import router as api_router
from app.api.web import router as web_router
from app.core.config import get_settings
from app.db.init_db import init_db

settings = get_settings()
app = FastAPI(title=settings.app_name, version=settings.app_version)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(web_router)
app.include_router(api_router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def root_health():
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "provider": settings.smartlife_provider,
        "timezone": settings.timezone,
    }
