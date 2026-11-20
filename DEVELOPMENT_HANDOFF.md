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
