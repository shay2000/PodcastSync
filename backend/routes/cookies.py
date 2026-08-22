"""Cookie detection and validation API routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

from backend.services.cookies import KNOWN_BROWSERS, probe_browser_cookies, test_cookies

router = APIRouter()


@router.get("/cookies/detect")
async def detect_cookies() -> dict:
    """Detect installed browsers and whether their YouTube cookies are readable."""
    loop = asyncio.get_event_loop()
    results = []
    for browser in KNOWN_BROWSERS:
        results.append(await loop.run_in_executor(None, probe_browser_cookies, browser))
    return {"browsers": results}


@router.post("/cookies/test")
async def test_configured_cookies(request: Request) -> dict:
    """Test configured or explicitly selected cookies against YouTube."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    settings = request.app.state.settings
    browser = body.get("browser", settings.cookies_from_browser) or None
    cookies_file = body.get("cookies_file", settings.cookies_file_path) or None
    if not browser and not cookies_file:
        return {"status": "error", "message": "No browser or cookie file configured"}

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, test_cookies, browser, cookies_file)
