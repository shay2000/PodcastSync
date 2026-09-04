# Phase 4 — Auto-update feature (AU1–AU8)

Goal (owner request): *push a tagged release to the repo → installed PodcastSync menu bar apps detect it, offer it, download + verify it, and install + relaunch with one click.*

User data never travels with updates: DB (`~/.podcastsync`) and audio storage (`~/PodcastMirror`/custom dirs) live outside the `.app` bundle and are untouched.

Context that shapes this design:
- Current builds are **ad-hoc signed, not notarized** (decision D1 default (a)). Fully silent background installs are only frictionless with notarization. Stage A keeps the one-time Gatekeeper “Open Anyway” per release but removes the “manually check GitHub” step.
- The Swift launcher already knows how to start/stop the backend and health-check `/api/status` — reuse that machinery.
- The backend is embedded in the `.app`; updating the app updates everything.
- Overcast/LAN notes don’t affect updates.

---

## AU1 — Publish update metadata from CI (manifest + per-arch zips)

- **Priority:** P1 · Size: M · Linux-testable (workflow file + script); final effect needs a release.
- **What to add:**
  1. A manifest template committed at `scripts/release/latest.json.template`:
     ```json
     {
       "version": "{{VERSION}}",
       "build": {{BUILD}},
       "minOSVersion": "13.0",
       "date": "{{DATE}}",
       "notes_url": "https://github.com/shay2000/PodcastSync/releases/tag/v{{VERSION}}",
       "assets": [
         {"arch": "arm64", "kind": "app-zip", "url": "https://github.com/shay2000/PodcastSync/releases/download/v{{VERSION}}/PodcastSync-{{VERSION}}-arm64.zip", "sha256": "{{ARM64_ZIP_SHA256}}", "size": {{ARM64_ZIP_SIZE}}},
         {"arch": "arm64", "kind": "dmg", "url": "https://github.com/shay2000/PodcastSync/releases/download/v{{VERSION}}/PodcastSync-{{VERSION}}-arm64.dmg", "sha256": "{{ARM64_DMG_SHA256}}", "size": {{ARM64_DMG_SIZE}}}
       ]
     }
     ```
     (Add `x86_64` entries when R6 lands. `build` = monotonic integer; use `git rev-list --count HEAD`.)
  2. A small filler script `scripts/make_manifest.sh <dist-dir>` (bash + python3; Linux-testable with fake files) that computes sha256 + sizes and renders the JSON.
  3. `build-release.yml`: after “Build app and DMG”, also produce the zip:
     ```yaml
     - name: Stage update assets
       run: |
         mkdir -p build/update
         ditto -c -k --sequesterRsrc --keepParent build/PodcastSync.app build/update/PodcastSync-${{ env.PODCASTSYNC_VERSION }}-arm64.zip
         mv build/PodcastSync.dmg build/update/PodcastSync-${{ env.PODCASTSYNC_VERSION }}-arm64.dmg
         shasum -a 256 build/update/PodcastSync-${{ env.PODCASTSYNC_VERSION }}-arm64.dmg | cut -d' ' -f1 > build/update/dmg.sha256
         PODCASTSYNC_VERSION="${{ env.PODCASTSYNC_VERSION }}" \
           BUILD="${{ github.run_number }}" \
           ./scripts/make_manifest.sh build/update
     ```
     Upload `build/update/*` as artifacts and `gh release upload` the dmg, zip, sha256 files, and `latest.json`. Also upload `latest.json` to a stable URL the updater can fetch without GitHub’s API rate limit — recommended: commit-time mirror to a `release/` path on the repo (`gh api` to upload as a release asset named `latest.json` with `--clobber` means the URL is `…/releases/download/vX.Y.Z/latest.json` which changes per version — NOT stable). For a stable URL use GitHub Pages (`/release/latest.json` on `gh-pages`) or raw on a branch. `[DECISION]` Default: mirror `latest.json` to `gh-pages`/`release/latest.json` via a tiny extra job; if Pages is not desired, the updater falls back to the GitHub API `releases/latest` endpoint (rate-limited to 60/hr unauthenticated — fine for a personal app that checks every 6 h, but Pages is cleaner).
- **Test:** `scripts/make_manifest.sh` renders valid JSON with correct sha256/size for dummy files.

---

## AU2 — Swift `Updater` service [macOS]

New file `macos/PodcastSync/Sources/Updater.swift`. Requirements:
- `@MainActor final class Updater: ObservableObject` published state: `updateAvailable: Bool`, `availableVersion: String?`, `checkState` (idle/checking/downloading/installing/error), `progress: Double`, `errorMessage: String?`.
- **Check policy:** on app launch, then every 6 h (Timer), plus a manual “Check for Updates…” menu item. Skip entirely if the app is running from the repo `.build` dir (dev mode — detect via a compile-time flag or absence of `Bundle.main.resourceURL`-style bundle path containing `Contents/Resources/backend`).
- **Fetch:** GET the stable manifest URL (AU1). `URLSession` with `timeoutIntervalForRequest = 20`, HTTPS only. Parse `version`, compare semver against `Bundle.main`’s `CFBundleShortVersionString` using a small `compareVersions(a, b)` (numeric dotted compare, ignore prerelease unless beta channel later).
- **Wire into `PodcastSyncApp`:** menu item “Check for Updates…” (shortcut `u`), and when `updateAvailable` a highlighted row “Update available — vX.Y.Z” that opens the update panel; disable while backend `isRunning` mid-sync is irrelevant (updates only apply at install time, but don’t offer while `active_downloads > 0` on the backend to avoid surprising the user mid-download — check `/api/status` first).
- **Unit tests (macOS CI job):** pure `compareVersions` table; the state machine with a stubbed session (inject a protocol `ManifestFetching`); malformed manifest → error state.

---

## AU3 — Menu bar + panel UX [macOS]

- Menu: badge row with version, “Release Notes” link (`notes_url`), “Download & Install”, “Remind Me Later”, and “Check for Updates…”.
- Optional small SwiftUI window/panel for progress: reuse the existing app’s SwiftUI; keep it minimal — a menu-based progress row is acceptable for v1 (menu bar apps live in the menu). Prefer the menu row: `Downloading… 42%` with the user able to cancel.
- Accessibility: expose state via the existing `statusText`-style live region if present; keep it simple.

---

## AU4 — Download + verify [macOS]

- Download the matching-arch `app-zip` asset to `~/Library/Caches/com.podcastsync.app/PodcastSync-<ver>-<arch>.zip` (stream to disk, update `progress`).
- Verify **sha256** against the manifest; verify the zip contains `PodcastSync.app/Contents/Info.plist` with `CFBundleShortVersionString == availableVersion`; abort + error toast on mismatch and delete the partial file.
- Never trust a manifest over plain HTTP; the manifest URL must be HTTPS.

---

## AU5 — Install & relaunch [macOS]

Two install locations:
1. **User-writable bundle** (app in `~/Applications`, or the user owns `/Applications/PodcastSync.app` — test with `FileManager.isWritableFile(atPath:)` on the bundle’s parent + bundle): 
   - `backend.stop()` (SIGTERM + wait, existing `BackendProcess.stop()`).
   - Stage the new bundle: unzip to a temp dir, `replaceItemAt(newBundleURL, withItemAt: oldBundleURL)` (or remove old then move new).
   - Relaunch via `NSWorkspace.shared.openApplication(at: …)` (or `open -a`) and `NSApp.terminate(nil)`.
2. **Not user-writable** (admin-owned `/Applications`): **do not** attempt privilege escalation in v1. Reveal the downloaded DMG/zip in Finder with a modal: “Move the new PodcastSync to your Applications folder to finish updating.” (Honest, safe, still one manual step — this is the Gatekeeper-constrained reality of ad-hoc signing.)

Guard rails (AU7) apply before any install: only install when the app was launched from a writable location; never install while backend downloads are active; keep a copy of the previous bundle (`~/Library/Caches/com.podcastsync.app/last-good/`) until the new one has launched once (cleanup on next successful boot).

---

## AU6 — Tests for the updater state machine [macOS CI]

Node-style unit tests aren’t applicable (Swift). Add to the macOS CI job (`ci.yml` or the release workflow): build `swift test`? The package is an executable target without test target — add a `Tests/` directory + a `UpdaterTests` target in `Package.swift` (or extract `compareVersions`/manifest decoding into a small framework target `PodcastSyncCore` with unit tests, leaving the app target thin). Cover: version compare table; manifest decode incl. missing-fields and wrong-arch; sha256 mismatch → abort with no install; correct-arch selection; “up to date” path when version equals current.

---

## AU7 — Guard rails

1. Never auto-install without an explicit user click.
2. Require macOS ≥ 13 (same as the app).
3. Defer the update *offer* while `/api/status` reports `active_downloads > 0` or `download_queue_size > 0`.
4. Ignore prerelease versions in the manifest unless a beta channel is introduced later.
5. Preserve user data (never touch `~/.podcastsync`, storage dirs).
6. Atomic replace: never delete the running bundle before the replacement is fully staged and verified.
7. The updater must not depend on the backend running (it’s a Swift-side feature).

---

## AU8 — Sparkle migration (staged, post-notarization)

- Deferred until decision D1(b) (Developer ID + notarization). When adopted: embed Sparkle, generate an EdDSA keypair, generate `appcast.xml` from the **same** release metadata that feeds `latest.json` (single source of truth in CI — add a `make_appcast.sh` that consumes the manifest data), per-arch feed items, Sparkle handles download/verify/privilege-install/relaunch and scheduled checks.
- Do not build AU8 now. Document the schema so `latest.json` → appcast mapping stays trivial (`version/build/date/notes_url/arch/sha256`).

---

## Phase 4 Summary

- [ ] AU1 manifest + CI publishing (zips, sha256, latest.json)
- [ ] AU2 Swift Updater service
- [ ] AU3 menu bar + panel UX
- [ ] AU4 download + sha256 verify
- [ ] AU5 install & relaunch (user-writable + Finder fallback)
- [ ] AU6 updater unit tests (macOS CI)
- [ ] AU7 guard rails
- [ ] AU8 Sparkle migration (deferred, schema-compatible)

Gate (macOS): cut a test tag v0.3.0, install the v0.3.0 DMG, push v0.4.0 → “Check for Updates” finds it, Update downloads/verifies/installs/relaunches with data intact. Linux: manifest script + schema + workflow text reviewed.
