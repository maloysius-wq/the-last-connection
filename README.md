# The Last Connection — Prototype 02

> **Windows players:** You do not need Ollama, system Python, Godot, or LocalForge to run the **portable Windows ZIP**. Download the `TheLastConnection-Windows-Portable-NoModel` artifact from [GitHub Actions](https://github.com/maloysius-wq/the-last-connection/actions/workflows/portable_windows.yml), extract the entire folder on D:, and double-click `TheLastConnection.exe`. On first launch, choose the existing GGUF model on D:. **Do not download the Source code ZIP for this installation route.** The AI model itself is not bundled.

An offline-first psychological horror experiment: you watch Eli in a locked maintenance room and guide them using natural language. **The LLM chooses speech and proposes actions; Godot executes and validates physical actions.** The initial playable slice supports typed instructions and the complete first-room escape sequence. Voice is planned for Phase 3, not yet implemented.

## Requirements

- Python 3.10+ (the AI bridge uses Python standard library only).
- Godot 4.3 or newer (Compatibility renderer).
- Ollama and `qwen3:4b-instruct` for actual AI responses. Alternatively, use `--mock` for an intentionally scripted offline demonstration without any LLM.

## Run it

1. Clone `https://github.com/maloysius-wq/the-last-connection` or download its source as ZIP.
2. Open a terminal **in the `the-last-connection` folder** (the folder containing `ai_bridge/`).
3. For real AI, install Ollama and pull the model:

   ```bash
   ollama pull qwen3:4b-instruct
   ```

4. Start the local AI bridge. Keep this terminal open:

   ```bash
   python -m ai_bridge.server
   ```

   If you don't have Ollama yet, run `python -m ai_bridge.server --mock` instead. This mode is scripted; it lets you validate the Godot scene and action wiring without a language model.

5. Open `godot/project.godot` in Godot. Press **F6** to run a selected scene or **F5** to run the project.
6. Type **"Pick up the flashlight"** and click TRANSMIT.
7. Eli should respond, walk across the room, pick up the flashlight, receive the actual outcome, and report back.
8. Ask **"What are you holding?"**. With the real LLM, the next prompt includes the authoritative inventory and recent conversation. In mock mode, the scripted response uses the inventory.

If the bridge is unavailable or Ollama hasn't been started, Godot shows a bridge error instead of silently simulating an LLM response.

## What works in this first slice

- Godot video-feed-like surveillance terminal with a simple generated 3D maintenance room and placeholder Eli.
- Typed natural-language interaction and Ollama structured JSON responses.
- AI requests are constrained to `wait`, `move_to`, `inspect`, `take`, and `use`.
- Visible target whitelist, length guards and a second validation pass in Godot.
- Physical walk-to-object movement and working flashlight inventory interaction.
- The breaker powers the room, an inspectable note reveals a code, the keypad validates four digits, and the door opens after the correct entry.
- Persistent session conversation on disk and saved in-game room state.
- Explicit `--mock` mode for scene verification without a local model.
- Python unit tests for validation, outcomes, and persistence.

## Tests

```bash
python -m unittest discover -s tests -v
# Engine smoke: godot --headless --path godot --import --quit
# Engine smoke: godot --headless --path godot --script res://tests/smoke_test.gd
```

## Run modes and privacy

The bridge listens only on `127.0.0.1:8765`. The Ollama endpoint defaults to `http://127.0.0.1:11434/api/chat`. No cloud service is called by the project code. Ollama must be installed locally; the actual model download requires the internet once.

The local bridge stores conversation history and outcome facts as JSON under `ai_bridge/sessions/`. These files are deliberately gitignored. Save-game progress is stored in Godot's `user://tlc_save.cfg`. This prototype keeps the most recent turns and has not yet implemented long-term summarized memory.

## Configuration

- `TLC_MODEL`: Ollama model tag (default `qwen3:4b-instruct`)
- `TLC_OLLAMA_URL`: local Ollama chat endpoint
- `TLC_SESSION_DIR`: path for persistent conversation JSON files
- `python -m ai_bridge.server --port 8765`: bridge port (Godot currently targets 8765)

## Known limitations

- Voice input/output, lip sync, finished character animations, and advanced atmosphere effects remain later phases.
- Eli uses placeholder geometry, not finished character artwork.
- Local LLM latency depends on CPU/GPU and model selection. No latency benchmarks yet.
- The Python test suite (18 tests) and a real headless Godot 4.5.2 smoke test passed in GitHub Actions on PR #1. The CI test validates gameplay logic but not visual quality, microphone hardware, or actual Ollama model behavior.
- Single active request per terminal; there is no interruption or multistep planner yet.
- Model output validation is deliberately strict; invalid or undiscovered targets are blocked.

## Design contract

1. The game engine is the sole authority on objects, physics, inventory, clues and puzzle success.
2. AI output is an **intent**, never an authoritative action result.
3. The character perceives only the information explicitly included in the world snapshot.
4. An action outcome is returned to the model only after the engine resolves it.
5. Horror story reveals are authored, not left to accidental hallucinations.

See `DEVELOPMENT_HANDOFF.md` for next tasks and acceptance criteria.

## First complete escape path

Tell Eli to take the flashlight, switch on the breaker, inspect the maintenance note, enter its four-digit sequence on the keypad, and open the exit door. Each physical change is checked by Godot; the mock backend deliberately uses simple matching and is not equivalent to real model behavior. CI now runs Python tests and a real headless Godot smoke test on pushes and pull requests.

## Portable Windows edition (D: drive; no Ollama required)

This is a **separate, self-launching Windows ZIP artifact**, not the source ZIP. It includes the exported Godot game, a packaged Python local AI bridge, and a CPU-only llama.cpp server. It intentionally does **not** include GGUF model weights.

1. From GitHub Actions, download a successful **Portable Windows build (no model bundled)** run's artifact **TheLastConnection-Windows-Portable-NoModel**.
2. Extract the **entire** artifact to a writable folder on D:, e.g. `D:\\Games\\TheLastConnection\\`.
3. Double-click `TheLastConnection.exe`. On first run, select your existing **.gguf** model file, which may remain under `D:\\LocalForge\\` (or any location on D:). The launcher saves this path as `config.json`; it does not move or re-download your model.
4. The launcher starts local inference and the game automatically, then stops its model server when the game exits. Saves and AI memories live inside the portable game folder.

See [portable/README.md](portable/README.md). The portable build is CPU-only in this first version, and may be slow on weaker PCs. The AI model must already be a compatible GGUF file. **It is not necessary to run LocalForge, Ollama, or a system Python installation.** Voice remains future work. GitHub Actions packaging cannot validate the private model stored on your PC.
