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
- Application was closed cleanly through its Quit shortcut, relaunched, and the Episodes screen visibly restored `Local validation draft` with Pending status and the connected backend. The application is left open.
- Real FFmpeg tests exercised all three audio modes with exact short durations, crossfades and peak verification, plus 1080p H.264/AAC assembly and sampled decoding.
- A separate **real 3600.0-second stereo WAV** stress test completed using synthetic tones (test input only): -18.01 LUFS, -14.18 dBTP, sample peak 0.1953421831, no clipping. Final WAV was removed after verification to avoid retaining a gigabyte of test audio. Its processing JSON is included with the deliverables.

Automated tests cover URL/domain rejection, model validation, hashtag format, path traversal/symlink escape, task claims and parallelism, retries/cancellation/approval gates, approval and dependency tampering, restart handling without trusting PIDs, Herdr pane-before-agent contract, idle without artifact rejection, yt-dlp channel tabs/deduplication/cache using controlled subprocess output, process timeouts/identity, API auth/persistence, actual image/audio import, media byte ranges and locked approved music.

## Environment blockers / unverified integrations

- Installed `Herdr.app` does not supply the required TUI CLI on PATH. Existing `~/.local/bin/herdr-core` reports `hc 0.1.18` and rejects `agent` and `status`; it is not silently substituted for the documented Herdr TUI. Real agent execution remains unverified. The adapter fails clearly and links installation instructions.
- Codex executable exists; provider login/model image capabilities have not been exercised. Gemini is absent from PATH. No user credentials were read or generated.
- YouTube Data API is no longer required. A live yt-dlp channel extraction retrieved 322 titles without an API key; details appear in the keyless update below. Full reference audio was not downloaded by this channel check.
- Unity 6000.6.5f1 is installed. A real batch project creation attempt produced licensing errors: no entitlement groups/free entitlements; `com.unity.editor.headless` not found. It reached the configured timeout. C# compilation and image rendering are therefore **not verified**. Unity logs are not included because they contain machine/license identifiers; error handling includes the local log for the user.
- `npm run tauri build` generated `.app` but the DMG stage failed with `hdiutil: create failed - Device not configured`. App-only build subsequently passed. DMG configuration remains available for a normal macOS environment.
- GUI initially failed to launch via the automation app lookup; Finder successfully opened the app. This was a UI automation lookup issue, not treated as proof that the app worked before the visible window was observed.
- No full hour-long final YouTube video has been produced. Music/visual approval and external-provider prerequisites remain necessary. No production-readiness or notarization claim is made.

## Remaining distribution work

Apple Developer signing/notarization; test external binaries and Unity licensing/rendering on target machines; real configured Herdr end-to-end run; Intel build; user acceptance with actual approved music and visual references. The code deliberately exposes errors rather than substituting mock media.


## Antigravity Client-only update

- Added an existing-session adapter for the installed Herdr Core `hc 0.1.18`, using its actual `schema`, `ls/get/send/read/interrupt` API. Codex/TUI remains a separate adapter.
- Added an external launcher implemented as an independent PyInstaller sidecar entry point. A real Client CLI button invocation created the original `agy` as Herdr terminal `t2` through stdin JSON-RPC `terminal.run`; the production orchestrator never calls this launch path.
- The user explicitly allowed changing the normal Client CLI Custom Executable Path. That one field was changed through the Client's own Settings UI and verified after reopening Settings. No Client application file was edited or updated; all four bundle file hashes are compared to the baseline.
- The new CLI initially reported `blocked`/`permission`. The user handled its permission prompt themselves, after which Herdr reported `idle`. No dialog was auto-approved.
- In the actual packaged Liminal Factory GUI the Client-only provider was saved, terminal `t2` was selected, its Client origin confirmed, and **Ready / Connected to t2** was visibly observed. The app is left connected. No AI task or model prompt was submitted during setup.
- Client origin is user-confirmed. Process identity, idle state and local proxy availability are checked automatically; a replacement process requires reconfirmation. One pane serializes AI tasks, and cancellation/restart never closes or relaunches the user's CLI.
- The complete suite has **48 passing tests**: 13 session-gate tests and 11 launcher/RPC/environment/quoting tests were added to the original 24. Test credentials are synthetic. No credential-bearing environment values are printed or written by the launcher.
- TypeScript/Vite build, packaged sidecar launcher entry point, read-only real HC RPC hello/schema checks, and release `.app` build passed.
- Production reference-analysis tasks and the full video pipeline remain unverified; the later synthetic vision check is recorded below. Model labels in the Client UI are not assumed to be CLI identifiers; choose the desired model in the existing CLI.

## Load failed diagnosis and Chrome cookies

- Reproduced the user's rejected Start Production request: settings had `vision_enabled=false`, and all episode tasks were Pending with no started workflow/download.
- Demonstrated the transport defect before the fix: a normal health response had `Access-Control-Allow-Origin: tauri://localhost`, but the ValueError rejection response had HTTP 400 with no CORS header. WebKit therefore hid its body as a fetch `Load failed` error.
- Moved CORS around the complete ASGI app, including auth/validation and server-error responses; added readable JSON error handling, persistent `Start blocked` episode logs, and explicit frontend network errors without automatic POST retry. The image-capability requirement remains enforced.
- Added explicit Chrome cookie/profile settings and `--cookies-from-browser chrome[:PROFILE]` with consent validation before browser/tool access. No cookie jar export or cookie values are added to arguments, logs or repository files. Cookie/header and signed-URL redaction is tested for downloader logs/errors.
- Real yt-dlp metadata-only check of the user's consented video completed with exit code 0 using `--cookies-from-browser chrome`; its expected YouTube ID was returned, with no stderr error. Cookie values were not printed or exported. This did not download the full reference audio.
- The full automated suite now has **60 passing tests**, including CORS for validation/auth/unhandled errors, persisted preflight errors, rejected cookie option/path injection, consent ordering, explicit yt-dlp flags, and output redaction. Frontend compilation passed.
- In the rebuilt native app, Chrome cookies were enabled and saved through Settings. The existing Client pane was reconnected; repeating Start on the same episode visibly displayed the image-capability explanation instead of `Load failed`. The `Start blocked` log was confirmed in the real SQLite database. The vision assertion was deliberately left false, and production/model tasks were not started.

## Image-capability configuration resolved

- Sent one actual capability-check task through the existing Client-launched Herdr pane. It used a synthetic PNG only, not the user's reference images. The CLI identified itself as Gemini 4 Argon (Medium), viewed the PNG with `read_file`, and saved a JSON result.
- Independently viewed the same PNG and confirmed that the six-character code and left/right shapes matched the CLI result exactly. The image-capability requirement is therefore satisfied for this current model/CLI.
- The test exposed a short `blocked` permission phase that the adapter treated as an immediate failure even though the CLI subsequently completed. The adapter now waits for the user/provider to resolve blocked state without approving dialogs; the task completes only after the expected JSON and completed turn.
- Herdr Core 0.1.18 retains `done` after a turn and rejects `--if idle` in that state. Completed-state readiness is now accepted; normal Core send retains its blocked-dialog rejection. Actual empty-input checks confirmed the mismatch and supported default-send behavior without submitting another model task.
- In the rebuilt `.app`, enabled and saved `vision_enabled=true`, left Chrome cookies enabled, and reconnected the same Client pane to visible Ready. Read-only SQLite inspection confirmed both saved booleans. Production was not started during this settings fix.
- **62 tests pass**, including waiting through a permission pause with no injected approval and accepting the next task from a completed CLI state. Release `.app` build passed.

## YouTube without an API key

- Removed the global YouTube key preflight and replaced Data API calls with yt-dlp public channel extraction. Audio extraction remains an independent DAG branch.
- The channel root is extracted with flat playlist metadata and automatic continuation pagination, including public videos/shorts/streams returned by yt-dlp. IDs are deduplicated across tabs, original title text is retained, and a source-specific TTL cache prevents reuse of old API results. Failed or malformed extraction is not cached.
- Channel extraction shares the existing, user-authorized Chrome profile setting. Subprocess stdout JSON is separated from stderr diagnostics so redaction never corrupts titles; errors and diagnostic logs are redacted.
- Real metadata-only verification on `https://www.youtube.com/@midwichmusic`: **322 titles**, **20.7 seconds**, Chrome cookies enabled, **no API key**. No audio or model generation was initiated in this check. See `outputs/youtube-channel-verification.json`.
- **69 tests pass**, including no-key production preflight, nested channel tabs/cache expiry, malformed output rejection, URL validation before browser access, and separate JSON/diagnostic handling. Frontend compilation and release app build passed.

## Chrome profile selection corrected

- `--cookies-from-browser` was already present in the failed audio download. Chrome has multiple profiles; yt-dlp's default cookie database selection does not reliably select Chrome's active profile.
- Blank profile now resolves Chrome's own `profile.last_used` and validates the folder. If unavailable or invalid, extraction requests explicit configuration instead of silently selecting another session. An explicit profile remains authoritative.
- Set the local app to the verified `Profile 9` through Settings. User cookie values were not printed, exported or committed.
- Metadata extraction for the failing video `ulyhIyFXCyQ` succeeded with `chrome:Profile 9`. Then the actual audio pipeline downloaded a five-second excerpt (73,124-byte MP3) and produced FFprobe/RMS/FFT analysis. No API key was used. This confirms media download, not only listing metadata.
- **73 automated tests pass**, including automatic active-profile selection, missing/malformed profile state, explicit override and no cookie export. Release app build passed.

- After installing the rebuilt app, retried the actual episode audio task with the saved Chrome profile. The native UI confirmed **Audio Reference → Completed** after 109 seconds; `reference.mp3` (2,709,620 bytes) and `audio_analysis.json` passed artifact validation. Music Brief started next. The temporarily cancelled visual waiting task was restored to Waiting for Client. Previous error entries remain historical logs.

## Automatic Client launcher reconnection

- Repeated timeouts occurred because the active CLI was replaced (`t5` → `t7`) while binding grants were memory-only. A live CLI alone did not establish a new application binding.
- A single idle/done terminal created by the existing external Client launcher is now discovered and connected automatically. Checks include launcher labels and launch ID, original argv, live foreground executable, matching terminal/foreground PID, expected project directory and Client proxy. Reconnection always creates a fresh nonce; saved PIDs never authorize process control.
- Unmarked terminals, multiple marked launches, shells, different directories and blocked/busy terminals are not auto-selected. Manual selection is retained. Explicit Disconnect suppresses discovery until Prepare or manual Connect is requested.
- A real read-only discovery with a new adapter instance found `t7` and returned Ready with `connection_origin=client-launcher`, without sending a prompt or launching a process.
- **82 tests pass**, covering restart discovery, ambiguity, unproven/busy sessions, explicit disconnect, replacement identity and existing serialization/cancellation safeguards. Frontend build passes.
- Rebuilt and reopened the native app while the existing `t7` CLI remained running. Settings changed from Checking to **Ready / Connected to t7** without pane selection, an origin checkbox or Connect click. Retried Visual Reference: the UI showed **Running · agy · t7** and the live CLI reported working. Music Brief was also retried and queued behind the same session lock. Release app build passed.

## Suno prepare-only workflow

- Added Music studio's optional Prepare form in Chrome action. It packages one validated agent prompt, episode title, target account email, instrumental intent and prepare-only mode. It does not approve music, generate songs or download audio. MP3/WAV import remains available and is still required for final audio production.
- Added a local Manifest V3 extension restricted to `https://suno.com/*`. It verifies the visible Account Email row, then fills title/Styles in Advanced/Custom mode with empty Lyrics. It refuses mismatched accounts, existing different drafts, nonempty lyrics, ambiguous/unsupported fields and expired preparation links. No backend bearer token, cookies, download permission or internal Suno API is involved.
- Real browser check via computer use: verified the intended account email in Suno Settings, then manually filled Styles and Song Title in the current v6 Advanced form from the episode's completed music brief. Lyrics stayed empty; Create was not clicked, no generation or download occurred. This verifies the real UI and account; it is **not** a live installation test of the extension.
- **89 Python tests and 7 browser DOM tests pass**. Browser tests verify field mutations without click/submit, preserving conflicting drafts, account mismatch, malformed/expired requests and restricted manifest permissions. Frontend compilation passed.
- Extension installation in the user's Chrome requires the user's explicit permission. Until installed and tested, its live-page compatibility remains unverified. The current production app was left running while the updated native bundle was built separately to avoid interrupting active episode tasks.

## Mandatory Suno More Options

- New music-agent output now requires structured `suno_options` with explicit creative recommendations and rationale. Legacy briefs can still be read, but cannot prepare Suno without these options. Music studio shows the values/rationale and offers Ask agent for More Options to revise an old brief; prompt edits preserve the options.
- Browser handoff v2 requires excluded styles, Weirdness, Style Influence, Variety, duration, Max Mode, Personalize Off and no vocal gender for instrumental. The extension opens More Options and reads back every value before declaring Prepared. It handles custom role-button accordion headers, hidden native slider duplicates and Suno HXC selected/unselected pill variants.
- With the user's explicit permission, installed Liminal Suno Prep 0.2.0 in the active Chrome profile. Live verification checked the actual Suno email and completed a full preparation with a visible Prepared banner. Independently observed Weirdness **25%**, Style Influence **85%**, Variety **Off**, Duration **180s**, Exclude styles populated, title/styles filled, empty Lyrics, Max Mode and Personalize Off. Create was not clicked; no generation, publication or media download occurred.
- The live test options were derived by this assistant from the existing completed ambient brief, in an isolated verification copy; they were not claimed as numeric settings already present in the old Gemini output. Future app generations require the provider to return these values and rationale. The original brief remains available for review/enrichment through the app.
- **96 Python tests and 13 browser DOM tests pass**. Tests cover missing/invalid mandatory options, retaining options during handoff, hidden duplicate controls, collapsed role-button panels, HXC selection states and independent read-back rejection after mutation. Frontend and release `.app` builds passed.

- Updated the installed native app at its original launcher-compatible path and reopened it after confirming there were no active production tasks. Existing episodes and the legacy music brief were retained. The GUI showed Ask agent for More Options and disabled Prepare form in Chrome for that legacy brief, confirming mandatory-option enforcement. No CLI permission dialog was approved automatically.
