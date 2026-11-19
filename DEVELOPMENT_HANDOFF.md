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

## Portable D: drive distribution (2026-11-19)

User clarified that their existing AI model is on D:\\LocalForge, C: is almost full, and they want the game completely standalone with no dependency on LocalForge or Ollama. Implemented a separate portable Windows build track:

- `portable/launcher.py`: packaged single-click startup, auto-detection or one-time chooser for an existing GGUF file, startup/shutdown of its own llama.cpp server and Python bridge, dedicated D:-resident sessions/logs/temp.
- `ai_bridge/agent.py`: local llama.cpp OpenAI-compatible JSON-schema backend, still validated by game authority.
- `godot/scripts/main.gd`: exported build writes save files beside the game rather than `%APPDATA%` on C:.
- `godot/export_presets.cfg`, `.github/workflows/portable_windows.yml`: Windows Godot export + PyInstaller onedir + upstream CPU llama server + downloadable GitHub Actions artifact, no model bundled.
- `tests/test_portable.py`: in-place model selection and llama.cpp schema regression tests. Local suite 25/25 passing.

Next: verify Windows GitHub Actions packaging actually succeeds, inspect the artifact layout, then test with a real existing Qwen3 GGUF on Windows. If original model isn't GGUF, it cannot be reused directly by this particular runner; do not silently download weights or fill C:. Voice remains a separate upcoming feature. Never claim runtime verification with the user's private model based on CI only.
