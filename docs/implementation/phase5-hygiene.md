# Phase 5 — Repo sanitisation, docs & release cut (G1–G7)

Files: repo history, `.gitignore`, `README.md`, `HANDOFF.md`, `debug_app.sh`, `backend/test_fetch.py`, new community files, `.github/workflows/*`, `pyproject.toml`, `AGENTS.md`.

Audit-established facts (verified): ~324 MB of build artifacts in pushed history (`venv.x86_old/` + `macos/PodcastSync/.build/`, incl. real machine paths in `pyvenv.cfg`/shebangs), still reachable from tag `v0.1.0`; a stray planning doc on remote branch `refactor/structural-cleanup`; 7 commits authored as `shayprasad@Shays-MBP.mynet`; no secrets/DBs/DMGs ever tracked; 91 tracked source files; LICENSE (MIT) present.

---

## G1 — History rewrite (decision D4) [P0, owner-coordinated]

**Default recommended: rewrite before going public.** The repo is single-maintainer with no forks visible.

Steps (perform on a clone, NOT the live checkout; verify thoroughly before force-push):
```bash
git clone --mirror <origin> /tmp/podcastsync-mirror.git
cd /tmp/podcastsync-mirror.git
# Install git-filter-repo: brew install git-filter-repo  (macOS)  |  pip install git-filter-repo  (Linux)
git filter-repo \
  --path venv.x86_old/ --path macos/PodcastSync/.build/ \
  --invert-paths \
  --mailmap <(printf 'shayprasad@Shays-MBP.mynet shayprasad@gmail.com\n')
# mailmap normalizes the machine-derived author email to the public one.
```
Then re-create the rewritten tag and update the remote:
```bash
git tag -f v0.1.0 <rewritten-commit-that-was-v0.1.0>   # resolve from filter-repo's report
git remote set-url origin https://github.com/shay2000/PodcastSync.git
git push origin --force --all --tags
```
Verify afterwards:
- `git clone` fresh → `du -sh .git` is small (no 324 MB blobs).
- `git log --all -p | grep -c "/Users/shayprasad"` → 0.
- No `venv.x86_old` or `.build` paths anywhere: `git rev-list --objects --all | grep -E "venv.x86_old|\.build/"` → empty.
- Optionally add to `.git/config` push protection notes; enable GitHub secret scanning + push protection in settings (G5).
- **`[DECISION]`** If the owner declines a rewrite (D4(a)), accept that every clone downloads ~325 MB and old history discloses the machine path; at minimum document it in README and skip G1.

---

## G2 — Remote branch cleanup

- Delete remote branch `refactor/structural-cleanup` (contains `can-you-plan-a-partitioned-book.md` and planning PRs): `git push origin --delete refactor/structural-cleanup` after ensuring main contains everything needed (merge PRs #1-#4 already landed). Archive the planning doc content locally if still wanted.

---

## G3 — Docs & ignore-file fixes

1. `HANDOFF.md`: replace the example path `cd "<repo root, e.g. ~/Documents/Side Projects:Hobbies/Coding/PodcastSync>"` (`:64` and the build section `:90`) with a neutral `~/dev/PodcastSync`. Decide whether HANDOFF ships publicly at all — `[DECISION]` recommend keeping (it is operationally useful) but genericized; if it stays, note it is a maintainer doc.
2. `debug_app.sh`: parametrize the app path (`APP_PATH="${1:-/Applications/PodcastSync.app}"`), reword the Python check to note it is only for rebuilds and check `python3.12`, and add a comment that it is for unpacked-bundle debugging only (it boots the backend on 8642 and can collide with a running instance).
3. `backend/test_fetch.py:1` docstring: “CLI test script for M1” → “Manual CLI test script (requires live YouTube access)”.
4. `.gitignore`: add `*.db-wal`, `*.db-shm`, `*.db-journal`, `*.sqlite3`, `.pytest_cache/`, `.coverage`, `.ruff_cache/`; remove the now-obsolete `venv.x86_old/` entry post-rewrite (keep `venv/`, `.venv/`).
5. README: dynamic badges (R5), real clone URL, the Security paragraph (threat model + LAN-only disclaimer), current Gatekeeper wording for ad-hoc builds (“Open Anyway” via System Settings → Privacy & Security on modern macOS; per-release reset), and the Overcast wording from A9. Update the static “How it works”/file-location table to not imply `0.0.0.0:8642` is a user-facing URL.
6. `AGENTS.md`: update “Known gotchas & risks” — remove fixed items (rolling delete inversion, migration fragility as described, dependency drift after R5, `?v=` manual busting after U13); document new invariants (auth/token mode, `PUBLIC_URL`, updater manifest, migration 004/005, feed newest-first). Add pointers to `docs/IMPLEMENTATION_SPEC.md`.

---

## G4 — Community & legal files

Add:
- `SECURITY.md` — threat model (LAN-only default; untrusted-LAN guests; DNS rebinding; what happens if publicly exposed per Phase 6), what is protected vs not, current mitigations (Host allow-list, optional token), and a vulnerability-reporting path (`github.com/shay2000/PodcastSync/security/advisories/new`).
- `CONTRIBUTING.md` — dev setup (`./scripts/dev.sh`), tests (`python -m pytest tests/ -q`), ruff, the hermetic-suite rules (no network in tests, lockstep stub warning), conventions from `AGENTS.md`, PR expectations (CHANGELOG entry, tests with fixes), and the release process pointer.
- `CHANGELOG.md` — Keep a Changelog format; backfill from `git log` (v0.1.0, v0.2.0, Unreleased = this program’s changes); release notes derive from it (Phase 3 R2).
- `.github/ISSUE_TEMPLATE/bug_report.yml` — fields: macOS version + arch, installed from DMG vs dev, what happened, backend log excerpt, feed URL behaviour; `feature_request.yml`.
- `.github/PULL_REQUEST_TEMPLATE.md` — checklist: tests pass, no secrets/artifacts, CHANGELOG updated, spec phase task id referenced.
- `.github/dependabot.yml` (Phase 3 R5), optional `.github/CODEOWNERS`.
- Confirm the GitHub repo “License” setting = MIT (matches `LICENSE`).

---

## G5 — GitHub settings (manual, documented here for the owner)

- Branch protection on `main`: require a PR, require `ci.yml` checks to pass, require linear-ish history (optional), and **tag protection** for `v*`.
- Enable secret scanning + push protection; optionally code scanning (Python) on `main`.
- Delete/archive `refactor/structural-cleanup` (G2).
- Document the release flow in README/CONTRIBUTING: bump `pyproject.toml` + CHANGELOG in one commit → tag `vX.Y.Z` → workflow builds/tests/publishes DMG + zip + sha256 + `latest.json`.

---

## G6 — Final QA sweep

On the Linux VPS: `git clone` the handoff branch fresh; `venv` setup; full pytest + ruff; boot backend; exercise the Phase-0 curl checks from the master spec; `docker compose up` (Phase 6) end-to-end. On macOS (if available): `./scripts/build_app.sh`, install the DMG on a clean machine, verify boot + a real sync + feed in Apple Podcasts/Downcast, and (Phase 4) an update install. Record results in the PR.

---

## G7 — Cut v0.3.0

1. `pyproject.toml` version → 0.3.0; CHANGELOG `[Unreleased]` → `[0.3.0]` with the date.
2. Commit + tag `v0.3.0`; push tag → release workflow runs tests, builds, publishes DMG + sha256 + update assets + `latest.json`.
3. Post-release checks: release page artifacts present; fresh-clone dev + build follow docs; `AGENTS.md` current; update `README` badges resolve.

---

## Phase 5 Summary

- [ ] G1 history rewrite (D4)
- [ ] G2 branch cleanup
- [ ] G3 docs/.gitignore fixes
- [ ] G4 community/legal files
- [ ] G5 GitHub settings
- [ ] G6 final QA sweep
- [ ] G7 v0.3.0 cut

Gate: clean clone is small; `git log` free of machine paths/artifacts; CI green on the tag; release assets present; README/HANDOFF/SECURITY accurate for strangers.
