"""FastAPI application — entry point for the PodcastSync backend."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend._resources import resource_path
from backend.config import Settings
from backend.database import DatabaseManager
from backend.downloader import DownloadManager, sync_source
from backend.fetcher.orchestrator import FetcherOrchestrator
from backend.scheduler import create_scheduler
from backend.routes.api import router as api_router
from backend.routes.feeds import router as feeds_router
from backend.routes.audio import router as audio_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    # --- Startup ---
    settings = Settings.from_env()

    db = DatabaseManager(settings.db_path)
    db.initialize()

    # Merge DB-stored settings
    db_settings = db.get_all_settings()
    settings.load_from_db(db_settings)

    orchestrator = FetcherOrchestrator(api_key=settings.youtube_api_key)
    download_manager = DownloadManager(
        storage_path=settings.storage_path,
        db=db,
        max_concurrent=settings.max_concurrent_downloads,
        settings=settings,
    )

    # Store on app state for route access
    app.state.settings = settings
    app.state.db = db
    app.state.orchestrator = orchestrator
    app.state.download_manager = download_manager

    # Set up scheduler
    async def poll_all_sources():
        logger.info("Scheduled poll starting...")
        sources = db.get_enabled_sources()
        for source in sources:
            try:
                await sync_source(source["id"], db, orchestrator, download_manager)
            except Exception:
                logger.exception("Scheduled sync failed for source %d", source["id"])
        logger.info("Scheduled poll complete")

    scheduler = create_scheduler(settings.poll_interval_minutes, poll_all_sources)
    scheduler.start()
    app.state.scheduler = scheduler

    logger.info("PodcastSync started — %s", settings.base_url)
    logger.info("  API key configured: %s", bool(settings.youtube_api_key))
    logger.info("  Storage: %s", settings.storage_path)
    logger.info("  Poll interval: %d minutes", settings.poll_interval_minutes)

    yield

    # --- Shutdown ---
    scheduler.shutdown(wait=False)
    db.close()
    logger.info("PodcastSync stopped")


app = FastAPI(title="PodcastSync", lifespan=lifespan)

# Mount routes
app.include_router(api_router)
app.include_router(feeds_router)
app.include_router(audio_router)

# Mount static files (web UI) — served at root, MUST be last
static_dir = resource_path("static")
if static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
else:
    logger.warning("Static web UI directory not found at %s", static_dir)


def run():
    """Entry point for `podcastsync` console script."""
    import uvicorn
    settings = Settings.from_env()
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.server_port,
        log_level="info",
    )


if __name__ == "__main__":
    run()
