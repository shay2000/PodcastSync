# Phase 6 — Public VPS / Docker deployment (V1–V7) — unlocks Overcast

Goal (owner request): run the PodcastSync backend on an **Oracle Cloud VPS** (Linux) in Docker behind HTTPS so Overcast (and any internet podcast client) can subscribe. The macOS app remains the local control surface; the backend is pure Python and runs anywhere.

Why this enables Overcast (verified): Overcast subscribes by having its own servers crawl every feed URL on the public internet. A LAN `http://192.168.x.x:8642` feed is unreachable — but `https://podcast.example.com/feed/1.xml` is crawled normally. Downcast/Apple Podcasts also fetch on-device, so they work both on the LAN and here. No XML change is required; reachability + correct advertised URLs are the fix.

**Security posture:** going public replaces the “trusted LAN” model. WS-C must be merged (at minimum the Host allow-list part of C3, plus C4 origin consistency) before this phase is exposed. Terminate TLS at a reverse proxy; do not expose uvicorn’s port publicly.

---

## V1 — `PUBLIC_URL` configuration

- **Priority:** P1 · Size: M · Linux-testable.
- **Changes:**
  1. `backend/config.py`: add `public_url: str = ""`. Read from env `PODCASTSYNC_PUBLIC_URL` in `from_env`; allow a DB override key `public_url` in `load_from_db`.
  2. Add helper:
     ```python
     @property
     def public_url_host(self) -> str:
         if not self.public_url:
             return ""
         from urllib.parse import urlparse
         return (urlparse(self.public_url).hostname or "").lower()
     ```
  3. `routes/feeds.py` base selection (C4): when `public_url` is set, use it for feed self-link + enclosure URLs; otherwise the request-derived base. Same base used for the `/feeds` list (`feeds.py:41`).
  4. `backend/static/js/api.js` `buildFeedUrl` (`:40-42`): prefer the server’s advertised public origin. Expose `public_url` (or an effective `base_url`) through `GET /api/settings` (`routes/settings.py` `settings_to_response` + `models.SettingsResponse`): replace the LAN-IP-only `base_url` computation with `public_url or f"http://{lan_ip}:{port}"`; the JS already uses `settings.base_url` when on localhost.
  5. `main.py` startup log: print the effective public URL when set.
- **Tests:** `test_public_url_feed_links` — set env `PODCASTSYNC_PUBLIC_URL=https://pod.example.com` before lifespan; feed self-link + enclosures carry `https://pod.example.com`; without it they use the request host. Settings response `base_url` reflects `public_url`.
- **Verify:** `curl -H 'Host: podcast.example.com'` locally returns feed URLs on that origin only when public_url is configured (Host allow-list in C3 also gates it).

---

## V2 — Proxy-awareness

- **Priority:** P1 · Size: S · Linux-testable.
- **Change:** run uvicorn with `--proxy-headers --forwarded-allow-ips '*'` when behind a trusted proxy, or add to `backend/main.py`:
  ```python
  # Only when PODCASTSYNC_TRUST_PROXY is set (Phase 6)
  from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
  app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["127.0.0.1"])
  ```
  Simplest: the Docker CMD uses `uvicorn backend.main:app --proxy-headers --forwarded-allow-ips 127.0.0.1`. This makes `request.base_url` reflect `X-Forwarded-Proto/Host` so feed/audio URLs are HTTPS + the public host even when `public_url` is not set.
- **Docs:** note in the compose file that Caddy/nginx must send `X-Forwarded-Proto` and `X-Forwarded-Host`.
- **Test:** a unit test asserting `request.base_url` picks up `X-Forwarded-*` when the flag is on (construct via `httpx` with headers through ASGITransport is not representative — instead assert the middleware presence in `main.py` when env set, or rely on the Phase-6 manual curl behind a real proxy).

---

## V3 — Docker packaging

- **Priority:** P1 · Size: M · Linux-testable (this is the handoff’s home turf).
- **Files:**
  1. `Dockerfile`:
     ```dockerfile
     FROM python:3.12-slim AS base
     RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
         && rm -rf /var/lib/apt/lists/*
     WORKDIR /app
     COPY requirements.txt .
     RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir uvicorn[standard]
     COPY backend ./backend
     ENV PODCASTSYNC_DB=/data/podcastsync.db \
         PODCASTSYNC_STORAGE=/data/PodcastMirror \
         PODCASTSYNC_PORT=8642
     RUN useradd -m -u 10001 podcastsync && mkdir -p /data && chown -R podcastsync /app /data
     USER podcastsync
     EXPOSE 8642
     CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8642", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]
     ```
     (Migration runs automatically in lifespan startup.)
  2. `docker-compose.yml`:
     ```yaml
     services:
       podcastsync:
         build: .
         container_name: podcastsync
         restart: unless-stopped
         ports:
           - "127.0.0.1:8642:8642"          # never publish to 0.0.0.0
         environment:
           - PODCASTSYNC_PUBLIC_URL=${PODCASTSYNC_PUBLIC_URL:?set to https://your.domain}
           - YOUTUBE_API_KEY=${YOUTUBE_API_KEY:-}
           - PODCASTSYNC_POLL_INTERVAL=${PODCASTSYNC_POLL_INTERVAL:-30}
           - PODCASTSYNC_API_TOKEN=${PODCASTSYNC_API_TOKEN:-}   # set to a long random value
         volumes:
           - podcastsync-data:/data
         healthcheck:
           test: ["CMD", "curl", "-fsS", "http://127.0.0.1:8642/api/status"]
           interval: 30s
           timeout: 5s
           retries: 3
     volumes:
       podcastsync-data:
     ```
     (Curl must be installed in the image for the healthcheck, or use python: `python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8642/api/status', timeout=3).status==200 else 1)"` — prefer the python one-liner to avoid adding curl.)
  3. Reverse proxy example `deploy/caddy/Caddyfile`:
     ```
     podcast.example.com {
         reverse_proxy 127.0.0.1:8642
     }
     ```
     (Caddy auto-provisions Let’s Encrypt TLS and sends the forwarding headers uvicorn needs.)
- **Verify (Linux):** `docker compose up -d --build`; `docker compose exec podcastsync python -m pytest tests/ -q` (optional); `curl http://127.0.0.1:8642/api/status` from the host; external curl to port 8642 blocked by the `127.0.0.1:` binding + instance firewall.

---

## V4 — Public security hardening (P0 once exposed)

Do **not** expose until at least: WS-C C1, C2, C3 part 1 (Host allow-list), C4, C5, C6 are merged. Then:
1. Set `PODCASTSYNC_API_TOKEN` to a long random value in compose (C3 part 2 enforcement ON). Without it, anyone on the internet can trigger syncs, delete sources/files, swap the API key, and point downloads at arbitrary folders.
2. Uvicorn bound to `127.0.0.1` inside compose (above); only 80/443 open on the Oracle VCN Security List + instance firewall (`ufw allow 22/tcp; ufw allow 80,443/tcp; ufw enable`); do not open 8642.
3. TLS via Caddy (auto Let’s Encrypt). Never plain HTTP for a public feed (podcast clients and iOS ATS strongly prefer HTTPS).
4. Rate-limit/drop abuse: consider `nginx` `limit_req` on `/api/*` behind the proxy if bot noise appears; document as optional.
5. Keep the DB and storage on the named volume only; back up `/data` (e.g. `docker compose exec` sqlite `.backup`, or a nightly `sqlite3 /data/podcastsync.db ".backup /backups/..."` cron).
- **Verify:** from the VPS’s *public* IP, `curl http://<public-ip>:8642/api/status` times out/refused; `curl https://podcast.example.com/api/status` without token → 401 (token ON); with token → 200; feed and audio URLs are `https://podcast.example.com/...`.

---

## V5 — Cookies on a headless server

- Browser-cookie extraction (`cookies_from_browser`) cannot work on Linux (no Safari/Chrome profile access on the server). Document + support the Netscape `cookies_file` path only:
  - The downloader already prefers `cookies_file_path` when `cookies_from_browser` is empty (`manager.py:89-95`).
  - Set it via `PATCH /api/settings` (`cookies_file_path`) pointing at a file mounted into the container (`./cookies.txt:/data/cookies.txt:ro`), or document the settings endpoint.
  - Note: the cookie file is a secret — mount read-only, never bake into the image, add `.env`/`cookies.txt` to `.gitignore`.
- **Verify:** with a Netscape `cookies.txt` mounted and `PODCASTSYNC_API_TOKEN` set, `POST /api/cookies/test` returns `{"status":"ok"}` (or a clear error); downloads that previously hit `[AUTH_REQUIRED]` succeed.

---

## V6 — Operational docs (Oracle Cloud specifics)

Add a README section “Run on a server (Docker)”:
- Oracle Cloud Always Free: Ampere A1 (ARM) or AMD micro instance; Ubuntu 22.04/24.04; attach a public IP; open 80/443 in the VCN **Security List** (and the instance `ufw`); free-tier egress (~10 TB/mo on A1) is ample for podcast audio.
- Install Docker + compose; set a DNS A record `podcast.example.com → <public-ip>`; run compose; Caddy obtains TLS automatically.
- Subscribe in Overcast/Apple Podcasts to `https://podcast.example.com/feed/<source-id>.xml`; note Local Network permission is irrelevant when accessing a public URL from a phone.
- Operations: logs (`docker compose logs -f`), backups (V4.5), updates (`docker compose pull && docker compose up -d` after a new image), and the security note that the app has no user accounts — guard with the token and TLS.

---

## V7 — Feed-URL ergonomics

- When `public_url` is set, the web UI should always show the **public** feed URL (grid RSS copy + detail feed URL row), even when the admin opens the UI via localhost/SSH tunnel. This is achieved by V1 (settings `base_url` = public_url) — double-check `api.js:40-42` (localhost → `settings.base_url`) and the detail row population (`actions/sources.js:61-64`) both use it.
- The “Copy Feed URL” feature must work over the LAN UI too (Phase 2 U1 fallback) — combine manual checks.
- **Verify:** from localhost with public_url set, copy RSS gives `https://podcast.example.com/feed/N.xml`.

---

## Phase 6 Summary

- [ ] V1 PUBLIC_URL config
- [ ] V2 proxy-awareness
- [ ] V3 Dockerfile/compose/Caddy
- [ ] V4 public security hardening + firewall
- [ ] V5 cookies on headless server
- [ ] V6 Oracle VPS operational docs
- [ ] V7 feed-URL ergonomics

Gate: on an Oracle VPS, `docker compose up -d` → Overcast and Apple Podcasts subscribe to the public HTTPS feed and download episodes; direct access to uvicorn’s port is blocked; `/api/*` mutations require the token.
