# DEVELOPMENT HANDOFF — The Last Connection

Updated: 2026-11-19

## Product

First-person psychological horror surveillance game. Player guides Eli, a trapped AI-controlled person, through a dark escape room. User approved both typed and spoken interaction; voice is a required product feature, but it is intentionally not implemented in the initial AI/action vertical slice.

## Current status

- Prototype Python bridge, local session memory and strict structured-action contract implemented.
- Explicit Ollama model `qwen3:4b-instruct` and explicit `--mock` mode.
- Basic Godot 4 surveillance view, room geometry, clickable terminal input, Eli placeholder, action tween, flashlight pickup, breaker interaction and persistent room state created.
- Python unit and HTTP integration tests pass: 13/13 (2026-11-19).
- **Not runtime-verified in Godot** because Godot executable is unavailable in this environment. Treat initial Godot import and interaction smoke test as the highest-priority blocker.
- User created public GitHub repository `maloysius-wq/the-last-connection` on 2026-11-19. Prototype 01 source was committed to `main` at `9f3c9bc214c51bfd31896f9a98404d6ef0a94c3a`; the GitHub repository is now the source of truth.
- Fixed the initial Godot session ID formatting bug: integer Unix timestamp now conforms to the bridge session ID regex; legacy saved decimal timestamps are replaced on load.

## Immediate priority

1. Import `godot/project.godot` into Godot 4.3+ and fix any GDScript/scene errors.
2. Start bridge with `python -m ai_bridge.server --mock`, press F5, send 'Pick up the flashlight'. Verify Eli actually moves, the flashlight disappears, inventory changes and an action outcome returns.
3. Run same interaction with Ollama `qwen3:4b-instruct`, including follow-up 'What are you holding?'. Record response time and any output errors.
4. Verify the HTTP integration suite against actual running bridge requests; scripted test coverage currently passes.
5. Begin Phase 2 puzzle interactions, including breaker, keypad, clues and locked exit door.
6. Phase 3: typed + push-to-talk voice via local speech recognition, text-to-speech, subtitles and accessibility fallback.

## Safeguards

- Game engine owns world and can reject every AI-suggested action.
- Action schema: `speech`, `action`, `target`, `emotion`.
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
- Next: inspect GitHub Actions results and fix Godot parsing/runtime issues; perform actual local Ollama behavior tests, then begin voice capture/transcription.
