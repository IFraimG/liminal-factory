# Liminal Factory — implementation and acceptance

## Phase 1 — Foundation
- [x] Tauri 2 + React/TypeScript/Vite/Tailwind shell, navigation and dark UI
- [x] Authenticated loopback Python API, SQLite WAL persistence
- [x] Episode creation, references, settings, per-tool diagnostics
- [x] Actual packaged macOS window opened; PNG imported and draft saved through UI

## Phase 2 — Orchestration
- [x] Persistent asynchronous DAG, bounded concurrency, retry/cancel/approval
- [x] Separate Herdr pane and agent lifecycle, capability/version discovery
- [x] Structured result schemas, unique per-attempt outputs, SHA-256 approvals
- [x] Safe restart reconciliation, process identity tracking, one-backend lock
- [x] Explicit MockHerdrAdapter and contract/integration tests
- [ ] Live Herdr + authorized provider execution (compatible Herdr TUI CLI missing)

## Phase 3 — References
- [x] Strict URL validation, consent-based audio sections, measured technical analysis
- [x] Real image-capable provider contract and typed visual output
- [x] YouTube uploads pagination/cache, metadata generation and SEO validation
- [ ] Real reference download / external AI / YouTube key verification (user configuration required)

## Phase 4 — Production
- [x] Manual Suno prompts/import/playback/approval and invalidation after changes
- [x] File-backed crossfade audio, deterministic evolution, multi-track modes
- [x] Actual 3600-second WAV stress test; sample peak/true peak/duration checks passed
- [x] Procedural Unity C# scene, bounded scene-spec agent, batch preview/loop adapter, visual QA agent
- [x] Actual short H.264/AAC assembly, resolution/FPS/duration and decode checks
- [ ] Unity project/render verification (installed Editor reports no usable licensing entitlement)
- [ ] Full hour-long end-to-end episode with user-approved Suno and Unity outputs

## Phase 5 — Packaging and verification
- [x] First-run welcome, settings, explicit prerequisite diagnostics, Keychain backend
- [x] PyInstaller onedir Python sidecar; starts without system Python
- [x] TypeScript/Vite build, cargo check, release .app build
- [x] Automated backend tests and real media tests
- [x] README, verification report and deliverable archives
- [ ] DMG in this environment (hdiutil: Device not configured; configuration is provided)
- [ ] Apple signing/notarization, Intel/other macOS validation for distribution

## Deliberate MVP limits
Appearance is dark; per-episode output defaults are exposed in New Episode rather than a global defaults editor. Recovery is explicit retry for interrupted work, not partial render continuation. Unity generation uses agent-authored bounded scene parameters and reviewed C# rather than arbitrary AI-generated executable C#. No unauthorized Suno automation or YouTube publishing.
