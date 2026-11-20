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

## Faster local AI responses (2026-11-19)

The CPU-only portable build now generates **one** LLM response per player instruction rather than generating another response after every physical action. Godot validates the action, reports its observed result immediately, and the bridge saves it as a confirmed memory without a second inference. The next conversation uses that memory. Short in-character acknowledgments after actions are deterministic; the initial dialogue and decisions are still produced by the real local LLM.

Recent dialogue and authoritative observations are compacted before sending them to llama.cpp, including for older saved sessions. The response token budget is reduced from 400 to 192 (with a fallback if a model cannot fit its JSON within the budget). These changes reduce redundant work but cannot guarantee a specific response time on a given CPU.

## Windows GPU acceleration and multi-PC setup

The `TheLastConnection-Windows-GPU-Portable` artifact bundles **Vulkan and CPU llama.cpp builds**. It tries full Vulkan GPU offload, partial offload, then CPU automatically. The selected backend is written to `logs/runtime-status.json`. Vulkan acceleration is supported on many NVIDIA, AMD and Intel GPU drivers; actual improvement depends on hardware and VRAM. On a computer without a compatible GPU it still runs on CPU.

For another computer, extract the complete portable ZIP to a writable folder. Existing GGUF files can be selected without copying to the system drive. When no model exists, the first-run launcher offers a **user-approved one-time** Qwen3-4B-Instruct-2507 Q4_K_M download (~2.5 GB) into the game's `models/` directory. Local inference stays offline afterward. The game itself needs no installed Ollama, LocalForge, Python or Godot. See `portable/README.md` for migration instructions.


## Update from inside the Windows game

Once you install the updater-enabled portable build, click **CHECK FOR UPDATES**
in the surveillance terminal. The game checks the newest public GitHub
Release on demand, shows the update and download size, and asks you to
confirm **Install Update**. The game closes, an independent updater downloads
the official release ZIP, checks its SHA-256 checksum, preserves saves/models/
settings and restarts the updated game.

The first updater-enabled build must be downloaded and extracted manually
once. After that, GitHub Releases are permanent, publicly accessible update
sources. The game does not silently download updates or move GGUF models.
More detail: [portable/README.md](portable/README.md).

## Eli conversation and intent improvements (playtest fix)

Eli remains a local, single-inference-per-player-turn character, with no second model call after an action. His dialogue prompt now prioritizes answering the player's *actual question* and explaining uncertainty naturally rather than always selecting a physical action. A conservative intent guard checks that a proposed movement or interaction matches an unambiguous physical request in the **current** message. Questions, hypothetical discussions, and ambiguous requests cannot accidentally launch actions, even if the LLM proposes one. For direct physical commands, incorrect action/target proposals can be corrected to the requested visible object; Godot still decides whether any action succeeds.

The flashlight interaction now supports `turn on/off` as explicit states. When Eli is asked to switch on a flashlight that is still on the desk, he picks it up as part of that authorized task and then switches it on. Repeat `on` requests do not inadvertently turn it off. In addition, the engine and fast acknowledgments report meaningful prerequisites and failures. Small recent-dialogue context remains compact, but previously saved assistant JSON turns are read back as natural speech. We raised the upper response budget so Qwen has enough room to answer thoughtful questions in one complete structured reply.


## Real location, truthful actions, and natural conversation

The portable game distinguishes **what Eli intends to do** from what Godot
confirms he did. Action instructions use future-tense speech until the world
reports a successful move, pickup, inspection, keypad entry or switch. Eli's
actual current location and the latest confirmed observation are stored in
portable saves and included in model context. Spatial questions such as
"Where are you?" and "What do you see?" read from real room state.

For conversations, local llama.cpp and Ollama now produce **plain natural
dialogue** instead of forcing every answer into an action-shaped JSON envelope.
Physical instructions still use a constrained action proposal validated against
the latest player's request. This change preserves the fast architecture:
**no extra model pass after an action**, and only one model response per
ordinary conversational request. Future work may enrich character reflection
without blocking movement or sacrificing truthful outcomes.
