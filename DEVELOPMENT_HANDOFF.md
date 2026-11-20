# DEVELOPMENT HANDOFF — The Last Connection

Updated: 2026-11-19

## Product

First-person psychological horror surveillance game. Player guides Eli, a trapped AI-controlled person, through a dark escape room. User approved both typed and spoken interaction; voice is a required product feature, but it is intentionally not implemented in the initial AI/action vertical slice.

## Current status

- Prototype Python bridge, local session memory and strict structured-action contract implemented.
- Explicit Ollama model `qwen3:4b-instruct` and explicit `--mock` mode.
- Basic Godot 4 surveillance view, room geometry, clickable terminal input, Eli placeholder, action tween, flashlight pickup, breaker interaction and persistent room state created.
- Python unit and HTTP integration tests pass: 18/18 (2026-11-19).
- **Godot runtime smoke-tested by GitHub Actions using Godot 4.5.2:** full first-room escape, wrong/correct keypad inputs, reset, and restore all passed. Headless checks do not validate on-screen visual quality or real microphone/voice hardware.
- User created public GitHub repository `maloysius-wq/the-last-connection` on 2026-11-19. Prototype 01 source was committed to `main` at `9f3c9bc214c51bfd31896f9a98404d6ef0a94c3a`; the GitHub repository is now the source of truth.
- Fixed the initial Godot session ID formatting bug: integer Unix timestamp now conforms to the bridge session ID regex; legacy saved decimal timestamps are replaced on load.

## Immediate priority

1. **Next feature: Phase 3 voice communications.** Build opt-in push-to-talk input and a local speech-to-text adapter (whisper.cpp), then route transcripts to the same `/api/decide` handler as typing. Keep a keyboard-only fallback.
2. Add local TTS playback for Eli with subtitles and a mute/skip setting; inspect redistributable model and voice licensing before bundling binaries.
3. Evaluate actual `qwen3:4b-instruct` with Ollama for first-room puzzle completion, vague instructions, and response latency; CI currently uses deterministic mock mode, not a real LLM.
4. Improve 3D art, atmosphere, character animations, and visual QA on a desktop machine. Headless CI cannot establish visual fidelity.
5. Add tests for the voice adapter and failure states; keep GitHub Actions Python+Godot checks green.

## Safeguards

- Game engine owns world and can reject every AI-suggested action.
- Action schema: `speech`, `action`, `target`, `emotion`, `argument` (strict four-digit input only for `enter_code`).
- No cloud inference fallback. Mock backend must be labeled as scripted.
- No automatic periodic tasks or scheduled verification. Development proceeds only in direct requests.
- No background completion promises.

## Test command

`python -m unittest discover -s tests -v`

## Project ownership / repo plan

Primary repo: `maloysius-wq/the-last-connection` (public; created by user). Use this repo as source of truth for all subsequent development.

## 2026-11-19 continuation

- GitHub Actions workflow added to main (`.github/workflows/ci.yml`): Python unit/HTTP and Godot 4.5.2 headless import/runtime smoke checks.
- Phase 2 first-room escape implemented: breaker reveals clue, inspect note reveals keypad digits, validated `enter_code` action, exit unlock/escape, save/reset.
- LLM JSON contract now includes optional semantic `argument` (four digits only for keypad), never free-form direct Godot commands.
- Mock mode supports deterministic first-room walkthrough.
- PR #1 merged into `main` as `c7509caf4be4cbe4d131d8f784045ca865aa7311`. GitHub Actions PR run `44617750509` was green in **both** jobs: 18 Python tests and the full headless Godot escape smoke test. Next: actual local Ollama evaluation, push-to-talk transcription, TTS, and visual validation.

## 2026-11-19 portable Windows work

- User requires a completely autonomous game executable on D: without reliance on LocalForge or Ollama, and with no duplicate AI-model download on C:.
- Added a packaged Windows launcher using a bundled CPU-only llama.cpp server. It loads an existing user-selected GGUF file by absolute path, displays startup progress, starts an embedded local Python AI bridge, launches the exported Godot game, and cleans up the server on exit.
- Portable save location is beside the exported game, plus AI memory and logs under the game folder on D:; avoid claiming that Windows never uses C: for incidental caches.
- Added portable Windows GitHub Actions packaging workflow; it distributes the llama.cpp CPU runtime but no model weights, adds upstream MIT license notices, and uploads a downloadable artifact.
- Python unit tests expanded to 25 (including model selection and llama.cpp JSON transport); local test suite passes. **Windows packaging and model runtime compatibility must be validated by GitHub Actions and a real user GGUF playtest before claiming either as verified.**
- Next: inspect portable workflow, address any packaging errors, and obtain working Windows artifact. Continue voice phase only after user confirms the executable and model work.

## Portable Windows verification (GitHub Actions)

- PR #3 merged on 2026-11-19 as `bb0e55ea5b568bcc8cf10a43d2cad3c6477c9470`.
- Windows Actions run `44623335908` **passed** all packaging checks, including 25 Python tests, PyInstaller launcher build, Godot import and Windows export, verified llama.cpp CPU binaries, and artifact upload. Artifact: `TheLastConnection-Windows-Portable-NoModel` (~38 MB compressed) from that run.
- Linux-based Prototype validation CI also passed on the portable branch.
- GitHub Actions is configured to produce a new portable build when relevant source changes are pushed to `main` (plus manual `workflow_dispatch`).
- The actual user-owned `D:\\LocalForge\\...gguf` model was **not available on GitHub runners** and must still be tested on Windows. CI does not establish natural-language model behavior, model compatibility, or UI/audio fidelity.
- **Next priority**: user tests standalone Windows download on D:, selects existing GGUF, and verifies Eli responds; fix any discovered runtime compatibility issues. Voice remains the next major feature after this validation.

## FINAL portable ZIP integrity check (2026-11-19)

- Corrected the Windows CI export: Godot is a GUI-subsystem executable on Windows, so invoke via `Start-Process -Wait -PassThru` and check nonzero exit codes; calling `godot ...` directly returned before the game export finished. The earlier PR #3 archive was missing `TheLastConnectionGame.exe` and must not be used.
- Current passing GitHub Actions run: https://github.com/maloysius-wq/the-last-connection/actions/runs/44624634567 (main branch). Artifact ID `14578706692`, `TheLastConnection-Windows-Portable-NoModel`, ZIP size `72,843,783` bytes.
- Downloaded artifact and inspected ZIP independently: no corrupt entries; `TheLastConnection.exe` (2,128,824 bytes), `TheLastConnectionGame.exe` (96,364,280 bytes), `runtime/llama/llama-server.exe`, necessary model-runner DLLs, `_internal/data/characters/eli.json`, and README are all present. All three executables have valid `MZ` headers. No `.gguf` weights are bundled.
- Python test suite: 25 passing on Windows. Godot Linux headless gameplay smoke tests still passing.
- User must test with actual GGUF file from D:; model compatibility and real-world latency not verified by hosted workflow.
- Prioritize user playtest feedback / portable startup issues. Do not claim voice is done.

## 2026-11-19 latency/interaction optimization

- User confirmed the portable build launches and model works with their local GGUF, but found a long pause before actions and another after them.
- Root cause: every action outcome was sent through a second full llama.cpp inference; conversation history also repeatedly stored and resent whole world snapshots. This grew the prompt on CPU with each interaction.
- Updated `Agent.outcome` to immediately persist authoritative action facts and return a safe, deterministic in-character acknowledgment; no additional LLM call. The next `/api/decide` includes confirmed facts.
- Constrain conversation context to recent turns and six confirmed events, compress legacy save snapshots, filter invisible objects, and reduce llama.cpp generated token cap from 400 to 192.
- Added tests that count backend calls, validate outcome memory, protect hidden facts and legacy sessions, and enforce bounded prompt size. Test using GitHub Actions on both Python/Godot and portable Windows workflows before merging.
- Existing GGUF stays in its D: location; update does not move/copy weights. Real latency on user's machine should be observed after they download the refreshed build.

## Latency optimization shipped (2026-11-19, user playtest follow-up)

- PR #4 merged into `main` as `4dcc47d6b40d3c4878d2c704083c4df4b3998f47`.
- GitHub Actions PR run `44658602430`: Python and Godot headless tests both passed.
- Portable Windows PR build run `44658602351` passed; artifact ID `14594821021` named `TheLastConnection-Windows-Portable-NoModel`.
- Downloaded and checked actual ZIP (`72,846,429` bytes): 1,042 files, no ZIP corruption; includes `TheLastConnection.exe`, `TheLastConnectionGame.exe`, and `runtime/llama/llama-server.exe`; includes no GGUF weights.
- Response path now makes **one LLM request per player input** and **zero LLM requests to acknowledge action outcomes**. Acknowledgments are deterministic phrases based on authoritative Godot results. Confirmed facts persist and enter the next prompt.
- Shortened model output cap to 192 and bounded prompt history; old histories compact on next turn. CI has 30 Python tests (25 previously + five new latency regression tests).
- Next step: user tests D-drive portable game, observes initial thinking latency versus the now-fast post-action acknowledgment; do not promise instant first response on CPU. Potential subsequent optimization: optional GPU backend, runtime response timing instrumentation, model/quantization benchmarking.
- Preserve `config.json`, `user_data/`, and user's external D-drive GGUF file on upgrades. Never duplicate model weights to C:.

## GPU acceleration and transfer to another Windows PC (2026-11-19)

- User playtested updated portable build: second model stall removed; initial CPU model response still too slow. Requested GPU acceleration and a distributable package for other PCs.
- Added pinned Vulkan llama.cpp Windows runtime alongside CPU runtime. Launcher auto tries full GPU offload (99 layers), partial (16), then CPU fallback. User may force CPU via `config.json`. Backend status is written under `logs/runtime-status.json`.
- Added first-run GGUF setup: use existing model when available, recover stale configured model path after transferring folder, or obtain explicit consent to download Qwen3-4B-Instruct-2507 Q4_K_M (~2.5GB) into `models/` beside game. Downloads use resumable `.part` and never write GGUF weights to C: unless that is the user's selected game drive.
- Cross-platform unit tests cover GPU fallback and model setup. GitHub Actions builds both CPU and Vulkan runtimes. Keep model self-contained/local-only after optional one-time download; no cloud inference.
- Next validation: check successful GitHub Windows artifact, inspect file tree, verify real model speed and active Vulkan offload using the user's computer. GitHub hosted runners do not test real GPU inference.

## GPU portable build VERIFIED & merged (2026-11-19)

- PR #5 merged to main: `94a8b85e2b95d4286df3bf6ae94399c09e26f2d1`.
- Passing GitHub Actions PR workflow: `44663330813`, artifact ID `14597450024`, name `TheLastConnection-Windows-GPU-Portable` (~112.7 MB ZIP); Python + Godot workflows also passed for the branch. GPU inference with a real NVIDIA/AMD/Intel card was NOT measured on hosted runners.
- Retrieved ZIP and inspected: 1,095 files, zero corruption, `TheLastConnection.exe`, `TheLastConnectionGame.exe`, `runtime/llama/cpu/llama-server.exe`, `runtime/llama/vulkan/llama-server.exe`, `runtime/llama/vulkan/ggml-vulkan.dll` and dependencies, no bundled GGUF.
- GitHub Actions originally failed an overstrict runtime exe size check: upstream llama-server.exe is a small (~9.7kB) DLL-linked Windows PE, validated with `MZ` header rather than a 1MB minimum. The corrected workflow is green.
- Installer/runner first launch supports existing GGUF path or explicit single-file download (~2.5GB) into game/models. The user's existing D-drive model remains untouched. When transferring to a new PC, copy ZIP and optionally bring your .gguf into models for fully offline setup.
- Launcher records selected backend in logs/runtime-status.json. Note: backend selection is not proof of actual GPU-layer offload; inspect logs/llama-server.log for layer offload count during local playtests.
- Future priority: user checks initial response time, mode, Vulkan GPU logs, compatibility and memory footprint, then continue voice input/output. Test on real hardware is required before promises about speed.


## In-game GitHub release updater (2026-11-19)

- User requested a Check for Updates button within the portable Windows game.
- Added explicit opt-in check via the localhost bridge and Godot confirmation
  UI. No periodic checks, background polling or silent installations.
- Added GitHub Release publishing in Windows CI on main-branch pushes:
  a permanently downloadable ZIP, SHA256SUMS.txt, and exact build-info.json
  version tag tied to the full source commit SHA. PR builds remain artifacts.
- Godot confirms an install request, saves progress and exits. The launcher
  stops its AI/bridge subprocesses and starts a self-contained updater from
  a sibling location. Updater waits for the parent process to exit, retrieves
  official release assets, validates checksum and ZIP file names/binaries,
  swaps the install directory and restores user_data/models/config/logs.
- Old install is restored on failure during file swap; no GGUF copy to C:.
  The updater restarts the portable launcher after install.
- First updater-enabled build requires one manual download. Future builds
  use the in-game update channel; no GitHub login required for public releases.
- Add regression tests for release metadata, checksum mismatch, traversal,
  state preservation, no silent installs, HTTP confirmation.
- Validate actual Windows packaging, Godot UI smoke, and published release
  asset before calling it ready. Normal gameplay remains offline.

## In-game updater: merged, CI passed and public release published (2026-11-19)

- PR #6 merged into main at `85e59c4e3478a74b5f4a04d6a26e257467af301e`.
- GitHub Actions main release run `44668071377` completed successfully, including the separate updater executable launch smoke test, Godot Windows export, model-runner binaries, artifact upload and `gh release create`.
- Public GitHub Release tag `portable-85e59c4e3478a74b5f4a04d6a26e257467af301e` is latest, with permanent assets `TheLastConnection-Windows-Portable.zip` (~125 MB) and `SHA256SUMS.txt`.
- Independently downloaded main-run Actions artifact `14598152992`, verified ZIP CRC (none corrupt), inspected 1,097 entries: `TheLastConnection.exe`, `TheLastConnectionGame.exe`, `TheLastConnectionUpdater.exe`, build-info.json with exact release tag, both CPU/Vulkan llama-server binaries. No GGUF weights bundled. Note: this verifies the same build's Actions artifact, not the separately generated Release ZIP bytes.
- Python tests and headless Godot smoke passed on PR and main. Actual interactive Windows in-place self-update (network download, Windows file replacement and restart) still needs end-user playtest.
- For user: One manual download/extraction from GitHub Releases is necessary to get the updater-enabled build. Thereafter click CHECK FOR UPDATES inside game. Preserve config.json, user_data/, models/, logs/ on first manual upgrade; code handles later updates.
- In-game update checks/installations require Internet *only when user clicks*; gameplay and LLM remain local. No schedule/background checks.

## Playtest: conversation fidelity and wrong-action regression (2026-11-19)

- User confirmed big inference-speed improvement, but Eli sometimes acted on unrelated objects, moved to inspect instead of obeying the request, failed to answer questions, and reported generic flashlight failures when it was still on the desk.
- Root causes: original persona encouraged `one action per decision`, model proposals were validated only against visibility (not player intent), assistant JSON/action envelopes crowded context, 192 generated-token ceiling could truncate useful conversational JSON, and `use flashlight` assumed prior pickup and toggled blindly.
- Added intent grounding in `ai_bridge/intent.py`: conversational/question turns are action-free; direct clear physical requests permit only the requested action and object, optionally pronoun-referenced to current conversational focus. Agent corrects a mis-targeted physical proposal to the user's explicit requested action when grounded in visible world state. World remains authoritative.
- Updated persona to answer questions naturally and suggest ideas in words without unauthorized movement. Prior conversational assistant JSON records are compacted into just their spoken text. Increased response token ceiling to 320, still ONE LLM call per player utterance and ZERO on outcome.
- Godot flashlight use can pick up from desk and switch on as one explicitly requested action; explicit on/off is idempotent, and status/acknowledgments explain prerequisites. Updated Godot smoke and Python behavior tests for real user reports.
- Future direction: optional fast structured tool decoder or behavior evaluators with real GGUF, but don't trade away natural conversation or the no-second-inference performance fix. Request actual user feedback before further changes.

## Eli behavior regression fix released (2026-11-19)

- Real user playtest: Eli sometimes took off-target actions, inspected/moved when asked different things, failed to answer questions, and repeatedly could not turn on an uncollected flashlight. The previous no-second-LLM-call speed gain was highly successful and must be preserved.
- PR #7 merged into main at `c26f5964d429fb8acb3de152e990680d9a184f3a`. GitHub PR Python tests (69 total) and headless Godot gameplay tests passed; Windows portable packaging passed.
- First permanent updater-ready GitHub Release with fixes: `portable-c26f5964d429fb8acb3de152e990680d9a184f3a`. Main Windows release job `44673704732` passed (published ZIP + SHA256SUMS). Main Actions artifact `14601590310` verified independently: 1,097 ZIP entries, no corruption, launcher/game/updater executables, CPU/Vulkan runners, correct build-info version, no GGUF weights.
- New `ai_bridge/intent.py` conservatively distinguishes questions/speculation from explicit physical requests, restricts attempted actions to user-requested visible targets, and supports flashlight on/off and pronoun focus. Preserves roleplay conversation via natural-speech history, richer Eli persona, and generated token ceiling 320 vs 192.
- Godot `use flashlight` now performs pick-up-then-switch-on when needed; on/off directives are idempotent. Confirmed outcomes are described truthfully with helpful prerequisites, without a second LLM call.
- Do not claim real Qwen GGUF conversation quality is completely verified by mocked tests. Ask user to playtest direct questions, unrelated actions, flashlight, and latency; tune based on the actual behavior. In-app updater button should find new published release.


## Location-grounded dialogue and action verification pass (November 19, 2026)

- User playtest: Eli says physical actions happened when they did not, describes keypad while at breaker, sometimes reports movement without actually moving; conversation still shallow. Asked if reintroducing expensive post-action reasoning would help.
- **Decision:** Do not restore blocking second model generation. It cannot prove movement and would undo a major responsiveness improvement.
- Godot now tracks and saves `actor_at` and the last completed `last_observation` from real physical outcomes. Move actions report success only when actor reaches target, and already-arrived movement is reported accurately.
- Expand direct movement intent phrasings (including walk over to/stand by). Physical pre-action narration comes from a deterministic, **future-tense** plan tied to the authorized requested object; the model can no longer announce arbitrary completed actions before Godot verification.
- Local llama.cpp/Ollama backends now use a separate *natural plain-text* conversation request for questions instead of the forced JSON action schema. Dialogue prompt includes actual location, confirmed observations, and visible world details. Replies remain a single model generation; outcomes remain zero generations.
- Location questions are answered directly from verified Godot location, with no model call. Unsupported recent room-action claims in conversational text are corrected against confirmed observations, while autobiographical stories are left alone.
- Regression tests cover action narration, real movement and save/restore, geographic context, false event claims, and natural conversation; Python, headless Godot and portable Windows CI required before shipping.
- User should test via in-app updater after release; actual GGUF naturalness and camera visual movement still need on-device feedback.
