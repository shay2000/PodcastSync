"""Aggregate the API route modules under ``/api``."""

from fastapi import APIRouter

from backend.routes import cookies, settings, sources, status, sync, videos

router = APIRouter(prefix="/api")
router.include_router(sources.router)
router.include_router(videos.router)
router.include_router(sync.router)
router.include_router(status.router)
router.include_router(settings.router)
router.include_router(cookies.router)
