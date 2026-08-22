"""YouTube cookie probing services.

yt-dlp stays inside the functions below: importing it is intentionally lazy
because it is expensive during application startup.
"""

from __future__ import annotations

KNOWN_BROWSERS = ["chrome", "safari", "firefox", "brave", "chromium", "edge", "opera", "vivaldi"]
PROBE_VIDEO_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def probe_browser_cookies(browser: str) -> dict:
    """Try to read YouTube cookies from one browser profile."""
    import yt_dlp

    try:
        opts = {
            "cookiesfrombrowser": (browser,),
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            jar = ydl.cookiejar
            yt_cookies = [c for c in jar if "youtube" in c.domain or "google" in c.domain]
            return {
                "name": browser,
                "available": True,
                "needs_permission": False,
                "has_youtube_cookies": len(yt_cookies) > 0,
            }
    except Exception as exc:
        error = str(exc)
        if "Operation not permitted" in error or "PermissionError" in error:
            return {
                "name": browser,
                "available": True,
                "needs_permission": True,
                "has_youtube_cookies": False,
            }
        return {
            "name": browser,
            "available": False,
            "needs_permission": False,
            "has_youtube_cookies": False,
        }


def test_cookies(browser: str | None, cookies_file: str | None) -> dict:
    """Probe YouTube with a browser profile or Netscape cookie file."""
    import yt_dlp

    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "socket_timeout": 15,
    }
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
    elif cookies_file:
        opts["cookiefile"] = cookies_file

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(PROBE_VIDEO_URL, download=False)
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:300]}
