# Verification — 8 November 2026

## Passed

- `npm run build`: TypeScript compilation and Vite production bundle.
- `cargo check --manifest-path src-tauri/Cargo.toml`: native Tauri host compiled.
- `npm run tauri build -- --bundles app`: release Apple Silicon `.app`, approximately 97 MiB, including Python runtime and native Python dependencies.
- `.venv/bin/python -m pytest -q`: **24 passed**. One upstream FastAPI/Starlette warning about the httpx test transport; no failed tests.
- Packaged PyInstaller onedir backend started independently, `/health` returned HTTP 200; wrong token returned 401.
- Opened `.app` from Finder. Observed the native window, dashboard, connected local backend, navigation and New Episode form.
- Through the actual native Open dialog selected a project-owned PNG, observed its thumbnail, filled valid YouTube fields and saved `Local validation draft`. Observed Episode Details with three DAG branches and the real creation log. No download consent was granted; no external production was started.
- Read-only inspection confirmed 1 episode and 11 persisted tasks in the application's SQLite database.
- Application was closed cleanly through its Quit shortcut before final archive creation.
- Real FFmpeg tests exercised all three audio modes with exact short durations, crossfades and peak verification, plus 1080p H.264/AAC assembly and sampled decoding.
- A separate **real 3600.0-second stereo WAV** stress test completed using synthetic tones (test input only): -18.01 LUFS, -14.18 dBTP, sample peak 0.1953421831, no clipping. Final WAV was removed after verification to avoid retaining a gigabyte of test audio. Its processing JSON is included with the deliverables.

Automated tests cover URL/domain rejection, model validation, hashtag format, path traversal/symlink escape, task claims and parallelism, retries/cancellation/approval gates, approval and dependency tampering, restart handling without trusting PIDs, Herdr pane-before-agent contract, idle without artifact rejection, YouTube pagination/cache using an HTTP mock, process timeouts/identity, API auth/persistence, actual image/audio import, media byte ranges and locked approved music.

## Environment blockers / unverified integrations

- Installed `Herdr.app` does not supply the required TUI CLI on PATH. Existing `~/.local/bin/herdr-core` reports `hc 0.1.18` and rejects `agent` and `status`; it is not silently substituted for the documented Herdr TUI. Real agent execution remains unverified. The adapter fails clearly and links installation instructions.
- Codex executable exists; provider login/model image capabilities have not been exercised. Gemini is absent from PATH. No user credentials were read or generated.
- YouTube Data API key has not been configured, and no copyrighted reference was downloaded. Pagination/cache are tested with controlled API responses, not claimed as a live channel analysis.
- Unity 6000.6.5f1 is installed. A real batch project creation attempt produced licensing errors: no entitlement groups/free entitlements; `com.unity.editor.headless` not found. It reached the configured timeout. C# compilation and image rendering are therefore **not verified**. Unity logs are not included because they contain machine/license identifiers; error handling includes the local log for the user.
- `npm run tauri build` generated `.app` but the DMG stage failed with `hdiutil: create failed - Device not configured`. App-only build subsequently passed. DMG configuration remains available for a normal macOS environment.
- GUI initially failed to launch via the automation app lookup; Finder successfully opened the app. This was a UI automation lookup issue, not treated as proof that the app worked before the visible window was observed.
- No full hour-long final YouTube video has been produced. Music/visual approval and external-provider prerequisites remain necessary. No production-readiness or notarization claim is made.

## Remaining distribution work

Apple Developer signing/notarization; test external binaries and Unity licensing/rendering on target machines; real configured Herdr end-to-end run; Intel build; user acceptance with actual approved music and visual references. The code deliberately exposes errors rather than substituting mock media.
