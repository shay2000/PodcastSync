# Phase 3 — macOS packaging & release engineering (R1–R7)

Files: `scripts/build_app.sh`, `scripts/build_backend.sh`, `.github/workflows/build-release.yml`, `pyproject.toml`, `requirements.txt`, `macos/PodcastSync/…`, `docs/CHANGELOG` setup (R2), `.github/dependabot.yml` (R5), `README.md` (R5).

Most tasks are macOS/CI-only (`[macOS]`). On the Linux handoff VPS, implement the Linux-testable pieces (R2 version-guard script + workflow text, R3 tests, R5 files) and prepare the `[macOS]` changes for review, clearly marked.

---

## R1 — `build_app.sh` hardening [macOS] [P0]

Verified failure-prone spots (current code `scripts/build_app.sh`):
1. **ffmpeg presence check is dead code** (`:100-107`): `FFMPEG_BIN="$(command -v ffmpeg 2>/dev/null || echo /opt/homebrew/bin/ffmpeg)"` always yields a non-empty string, so the `[ -z ... ]` guard never fires and a missing ffmpeg fails deep inside `bundle_macos_tool.sh` (`cp: /opt/homebrew/bin/ffmpeg: No such file or directory`).
   Fix:
   ```bash
   FFMPEG_BIN="$(command -v ffmpeg 2>/dev/null || true)"
   FFPROBE_BIN="$(command -v ffprobe 2>/dev/null || true)"
   if [ -z "$FFMPEG_BIN" ] || [ -z "$FFPROBE_BIN" ]; then
       echo "ERROR: ffmpeg and ffprobe are required to build. Install: brew install ffmpeg" >&2
       exit 1
   fi
   ```
2. **Nested codesign failures swallowed** (`:151-156,159-163` use `codesign ... || true`). Replace with strict signing that fails the build:
   ```bash
   sign() { codesign --sign "$SIGN_IDENTITY" --force "$1"; }
   ```
   and after all nested signs + the outer sign add verification:
   ```bash
   codesign --verify --deep --strict --verbose=2 "$APP_BUNDLE"
   spctl --assess --type execute "$APP_BUNDLE" || echo "note: spctl fails for ad-hoc (expected until notarized)"
   ```
   Keep the `ditto --norsrc` clean pass *before* the final outer sign (nested signatures live in `__LINKEDIT` and survive `--norsrc`).
3. **Stale-launcher fallback can ship yesterday’s binary** (`:30-32,73-81`). Make it opt-in:
   ```bash
   # Only reuse the previous launcher when explicitly allowed (never in CI).
   if [ "${PODCASTSYNC_ALLOW_LAUNCHER_FALLBACK:-0}" = "1" ]; then ... fi
   ```
   In CI, a Swift build failure must abort.
4. **`hdiutil attach` awk parsing** (`:196`): switch to `hdiutil attach -plist` + PlistBuddy, or constrain the awk to the filesystem column (`Apple_HFS|APFS`) + `/Volumes/`. Add `trap` cleanup: on any failure, `hdiutil detach -force "$MOUNT_POINT" 2>/dev/null || true` and remove `build/dmg-stage`.
5. After the outer sign and DMG build, gate with `codesign --verify --deep --strict` (above) and only then proceed.

**Tests/verification:** run `./scripts/build_app.sh` on macOS twice (second run clean); deliberately uninstall ffmpeg (or override PATH) and confirm the clear error at the top. Confirm a tampered nested binary fails the build instead of shipping.

---

## R2 — Version single-sourcing + release-tag guard [P0]

Verified coupling: version lives in `pyproject.toml:3` (0.2.0) and the git tag; `build_app.sh:11` reads pyproject; the workflow sets `PODCASTSYNC_VERSION=${RELEASE_TAG#v}` (`build-release.yml:71-72`) and Info.plist gets both `CFBundleShortVersionString` and `CFBundleVersion` = the tag string. No guard prevents a tag push with an un-bumped pyproject.

**Changes:**
1. `pyproject.toml` stays the single source of truth.
2. Add a consistency guard at the top of the release workflow (after `RELEASE_TAG` is set, `build-release.yml:29`):
   ```yaml
   - name: Check version consistency
     run: |
       PYPROJECT_VERSION="$(sed -nE 's/^version = "([^"]+)"/\1/p' pyproject.toml | head -1)"
       if [ "$PYPROJECT_VERSION" != "${RELEASE_TAG#v}" ]; then
         echo "::error::Tag $RELEASE_TAG does not match pyproject version $PYPROJECT_VERSION"
         exit 1
       fi
   ```
3. Remove the stale `default: v0.2.0` from `workflow_dispatch.inputs.release_tag` (`build-release.yml:12`) — make it required with no default (manual dispatch is only for re-running an existing release).
4. In `build_app.sh` Info.plist heredoc (`:125-128`): set `CFBundleShortVersionString` = semver, `CFBundleVersion` = the same for now (a build number can come later with auto-update; Phase 4 requires `CFBundleVersion` to increase monotonically per release — derive it from `git rev-list --count` once auto-update lands).
5. Add `retention-days: 30` to the artifact upload (`build-release.yml:90`).
6. Add a small `scripts/check_version.sh` (runs the same pyproject-vs-tag check) so it can be reused locally and by the Linux handoff.

**Tests/verification (Linux):** `scripts/check_version.sh v0.3.0` with `pyproject.toml` at 0.3.0 exits 0; with 0.2.0 exits non-zero. Update `pyproject.toml` version and `README` badges together (G3).

---

## R3 — Packaging drift guards + scheduler-bundle verification

1. `tests/test_packaging_inventory.py` (fully specified in Phase 1 T1) — land here if not already.
2. Add the APScheduler trigger modules to `--hidden-import` in `scripts/build_backend.sh` (see WS-B B11):
   ```
   --hidden-import apscheduler.triggers.interval
   --hidden-import apscheduler.triggers.date
   --hidden-import apscheduler.triggers.cron
   ```
3. `[macOS]` T4 packaged-backend smoke test in the workflow.
4. `backend/_resources.py`: keep as-is; note that `resource_path("static").is_dir()` is already guarded in `main.py:87-91` (warns, doesn’t crash).

---

## R4 — Info.plist polish [macOS]

`build_app.sh` Info.plist heredoc (`:113-143`): add
```xml
<key>NSHumanReadableCopyright</key>
<string>Copyright © 2026 Shay Prasad. MIT License.</string>
<key>LSApplicationCategoryType</key>
<string>public.app-category.entertainment</string>
```
and keep `LSMinimumSystemVersion 13.0`, `LSUIElement true`. (Do not add `NSPrincipalClass` — not needed for a SwiftUI `@main` MenuBarExtra app.) Verify with `plutil -lint` on the generated bundle’s Info.plist.

---

## R5 — Dependabot + dependency hygiene + README badges

1. `.github/dependabot.yml`:
   ```yaml
   version: 2
   updates:
     - package-ecosystem: "pip"
       directory: "/"
       schedule:
         interval: "monthly"
       groups:
         runtime: {patterns: ["*"]}
     - package-ecosystem: "github-actions"
       directory: "/"
       schedule:
         interval: "weekly"
   ```
2. Unify manifests (also flagged by WS-C S11): `pyproject.toml` `[project].dependencies` must equal `requirements.txt` runtime set. Add `mutagen>=1.47.0` to pyproject dependencies; align the yt-dlp floor (`pyproject` `>=2024.01.01` → `>=2026.01.01` to match requirements.txt — after confirming the packaged build is fine on that floor; or pick one floor and update both). Keep `pyinstaller` only in `requirements.txt` (build tool, dev-only) but note it in a comment.
3. `[DECISION]` Lockfile: add a `requirements.lock` (via `pip freeze` after a clean install, or pip-tools) for reproducible PyInstaller bundles. Recommended but optional for this handoff; if skipped, note it.
4. README badges (`:3-8`): replace static `v0.2.0` + fake “downloads 68.7MB” with dynamic shields:
   ```md
   ![Release](https://img.shields.io/github/v/release/shay2000/PodcastSync)
   ![Downloads](https://img.shields.io/github/downloads/shay2000/PodcastSync/total)
   ```
   (Arch-annotate once the R6 matrix lands.)
5. Pin workflow `runs-on: macos-14` explicitly (already done) and keep it; do not use `macos-latest`.

---

## R6 — arm64 + x86_64 release matrix [macOS, v1.1]

PyInstaller and SwiftPM are native-arch; no universal bundle in one pass. Add a matrix to `build-release.yml`:
```yaml
strategy:
  matrix:
    include:
      - os: macos-14      # arm64 (Apple Silicon)
        suffix: arm64
      - os: macos-13      # x86_64 (Intel)
        suffix: x86_64
```
Name artifacts `PodcastSync-<ver>-<arch>.dmg`; upload both to the release; README notes arch-specific downloads. `bundle_macos_tool.sh` already handles `/usr/local` (Intel) vs `/opt/homebrew` (ARM). This task can be deferred out of the handoff if the VPS phase is the priority.

---

## R7 — Notarization pipeline [macOS, budget-permitting — decision D1]

Full detail in the plan Appendix E. Summary of concrete changes (only when the owner has a Developer ID + paid program):
1. `scripts/build_app.sh`: `SIGN_IDENTITY="${PODCASTSYNC_SIGNING_IDENTITY:--}"`; when not `-`, the **outer** sign uses `--options runtime --timestamp`, nested signs stay ad-hoc (fine), and `|| true` is removed everywhere.
2. Add a verification + notarize + staple block after the DMG is created (guarded on `PODCASTSYNC_SIGNING_IDENTITY`):
   - `codesign --verify --deep --strict "$APP_BUNDLE"`
   - `xcrun notarytool submit "$DMG" --key "$APPLE_NOTARIZATION_API_KEY" --key-id "$APPLE_NOTARIZATION_API_KEY_ID" --issuer "$APPLE_NOTARIZATION_ISSUER_ID" --wait`
   - `xcrun stapler staple "$DMG"` then `xcrun stapler validate "$DMG"`
3. Workflow: add the keychain-import step (base64 `.p12` → `security import`, `set-key-partition-list`) using secrets `APPLE_DEVELOPER_ID_CERT_BASE64`, `APPLE_DEVELOPER_ID_CERT_PASSWORD`, `APPLE_NOTARIZATION_API_KEY`, `APPLE_NOTARIZATION_API_KEY_ID`, `APPLE_NOTARIZATION_ISSUER_ID`, `APPLE_TEAM_ID`.
4. Remove the now-redundant runtime `xattr -d com.apple.quarantine` self-clearing once notarized (keep until then).
Skip (mark `SKIPPED`) on the Linux handoff; produce the diff for owner review.

---

## Phase 3 Summary

- [ ] R1 build_app.sh hardening [macOS]
- [ ] R2 version single-sourcing + guard
- [ ] R3 packaging drift guards + scheduler bundle check
- [ ] R4 Info.plist polish [macOS]
- [ ] R5 dependabot + manifest unification + badges
- [ ] R6 arch matrix (v1.1)
- [ ] R7 notarization pipeline (D1)

Gate: Linux side — `scripts/check_version.sh`, inventory test, dependabot file parse; macOS side — `./scripts/build_app.sh` produces a DMG that passes `codesign --verify --deep --strict`.
