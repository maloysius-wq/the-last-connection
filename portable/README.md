# The Last Connection | Portable Windows build

**This is the game build intended for D: (not the GitHub source ZIP).**

The package includes the Godot game executable, a packaged local Python AI bridge,
and both Vulkan GPU-accelerated and CPU-fallback llama.cpp servers. It **does not bundle an AI model**. On first launch you can reuse an existing GGUF,\nor explicitly download Qwen3 4B Q4_K_M (~2.5 GB) into the game's own models folder.\nNothing is downloaded without your approval. There is no Ollama, LocalForge or system-wide
Python/Godot installation required to play this Windows build.

## Install / play

1. Download the **TheLastConnection-Windows-GPU-Portable** artifact from a successful
   GitHub Actions portable Windows workflow, then extract the **whole folder** somewhere
   writable on D:, e.g. `D:\Games\TheLastConnection\`.
2. Double-click `TheLastConnection.exe`.
3. On first launch, if exactly one `.gguf` is present under `D:\LocalForge` or beside
   the game in `models\`, the launcher uses it automatically. Otherwise, a native file
   selection window asks you to choose **the existing GGUF file**. The selected path
   is saved in `config.json` next to the launcher, not on C:.
4. The launcher starts llama.cpp on `127.0.0.1:8877`, then the game AI bridge on
   `127.0.0.1:8765`, then the game itself. Both servers stop when you close the game.

Sample optional `config.json` in the game folder:

```json
{
  "model_path": "D:\\LocalForge\\models\\qwen3-4b-instruct.gguf"
}
```

The real file path can be elsewhere on D:. Models in **GGUF format** are supported;
if the LocalForge model consists of `.safetensors` or Ollama `blobs`, it cannot be
loaded directly by this particular runner without a compatible GGUF version.
A compatible GGUF model should use a supported chat template. The model is not
copied, deleted or moved automatically.

## Disk usage and behavior

- Game, model runner, Python bridge, logs and game saves: D:.
- Game saves: `user_data/tlc_save.cfg` (alongside the portable game exe).
- Eli session memory: `user_data/sessions/`.
- Model server logs: `logs/llama-server.log`.
- Portable temp directory: `temp/`.
- The operating system and drivers can still create some small temporary/cache files
  in user profile folders on C:. We avoid **large AI model duplication** on C:.
- This build attempts **Vulkan GPU inference** first (NVIDIA/AMD/Intel with working Vulkan drivers), then partial GPU offload, and falls back to CPU automatically. Set `\"acceleration\": \"cpu\"` in `config.json` to force CPU mode.\n- After launching, inspect `logs/runtime-status.json` for `gpu_active` and `acceleration`. GPU support and performance depend on driver, VRAM, and model.
- **Voice and typing share the same AI/action logic.** Hold **Alt+V** while the text box is focused, **V** after clicking outside the text editor, or the **HOLD TO TALK** button, speak, and release. The recorded audio is transcribed by bundled local whisper.cpp, then the transcript is sent as a normal message to Eli. The release sends no voice data to the cloud.
- Eli's dialogue and verified action reactions are spoken using bundled Piper, while the full text continues to appear in the terminal. **MUTE**, **TEXT ONLY**, the **SKIP** button, and **MIC/VOICE** sliders are available below TRANSMIT.
- Voice input is push-to-talk, never always-listening. Recognition requires an enabled Windows microphone device and Windows microphone permission. Keep your audio driver input enabled. Each recording is capped at 15 seconds; the temporary WAV is deleted after processing.
- The Windows package includes the offline whisper.cpp runtime, a small English speech-recognition model, Piper, and the en_US-joe-medium voice model (pinned historical version for the packaged Piper executable). The first launch needs no additional speech-model download. If a voice asset or microphone is unavailable, typed conversation and subtitles still work.
- Voice preferences are saved with your normal portable save in `user_data/`, and remain intact after the in-game updater runs. All speech inference uses local CPU tools and may be slower on older PCs; speech synthesizes after the full Eli response is displayed.

**Note:** GitHub Actions validates packaging and the mock gameplay path, but cannot
run your specific private model file. Real-model latency/compatibility needs a local
playtest after download.


## Installing on a different Windows PC

Download the GitHub Actions ZIP, unpack it to a writable folder on that PC (for example, `D:\Games\TheLastConnection` or `C:\Games\TheLastConnection`), and double-click `TheLastConnection.exe`. The game includes the engine, local bridge, and CPU/Vulkan runners, so **you do not need Python, Godot, LocalForge, Ollama, or a Vulkan SDK**. A compatible graphics driver is needed for Vulkan GPU acceleration.

If that computer has no GGUF model, the game explicitly asks whether it should download a reviewed Qwen3 4B Q4_K_M model to the game's `models/` directory. It remains offline after setup. The file comes from the independent quantization repository `bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF` on Hugging Face; original Qwen weights are Apache-2.0 licensed. If you prefer not to download, transfer your existing `.gguf` file onto that PC and select it instead.

For migrating existing progress, copy `user_data/`. The `config.json` file may reference a model path that does not exist on the new machine; the launcher now lets you select/download a replacement. Never copy one computer's `config.json` blindly without checking the model path.


## Updating from inside the game

After installing this updater-enabled Windows version once, click
**CHECK FOR UPDATES** inside the surveillance terminal. The game checks
GitHub's latest published portable release only when you click. It displays
the release size and asks permission to install. Choosing Install ends the
game session, downloads the official ZIP and SHA-256 checksum, verifies its
contents, and relaunches the updated game automatically.

Updates require Internet only for the check and explicitly approved download.
AI conversations and model inference remain local and do not use the network.
No GitHub account is needed.

The updater preserves config.json (GPU and model settings), user_data/
(Eli's memories and saves), models/ (GGUF files), and logs/. It moves
model files in-place rather than copying or redownloading them. A separate
Windows updater executable sits briefly beside the installation directory
because Windows won't permit replacing a running program. An update failure
should leave or restore the old installation.

**Initial setup:** You must download the first version with an updater
once from GitHub Releases or an Actions build. Later releases can be
installed through the game. GitHub Actions artifacts eventually expire;
the new release-download channel is permanent.

## Voice troubleshooting and privacy

**Hold Alt+V** from the focused text editor, **V** outside it, or hold the on-screen button. Release after speaking. If the microphone is unavailable, check Windows **Settings > Privacy & security > Microphone**, your input device, and audio input permissions for desktop apps. The **MIC** slider adjusts the silence/noise threshold, not your operating system's device gain.

If recognition is inaccurate, use a quiet microphone and short, clear statements or type normally. Eli's captions always remain visible, even if synthesis fails or is muted. Press **SKIP** to cut off his current voice output without deleting the transcript. **TEXT ONLY** disables both incoming microphone capture and outgoing synthesis.

The microphone's WAV bytes are sent only to the local AI bridge on `127.0.0.1:8765`, and the bridge invokes the packaged local whisper.cpp command-line tool. Recordings and synthesized temporary WAV files are deleted from `temp/` after processing. No online speech APIs are used; the separate **CHECK FOR UPDATES** feature continues to contact GitHub only when explicitly clicked.

Bundled voice engine sources and notices:
- [whisper.cpp v1.8.3](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.8.3) (MIT) and `ggml-tiny.en-q5_1.bin` Whisper transcription model
- [Piper 2023.11.14-2](https://github.com/rhasspy/piper/releases/tag/2023.11.14-2) (MIT)
- [Piper en_US-joe-medium voice v1.0.0](https://huggingface.co/rhasspy/piper-voices/tree/v1.0.0/en/en_US/joe/medium), per-voice dataset card lists CC0. The model card is bundled in the voice directory.

## Export the current conversation and diagnostic logs

When Eli misunderstands something, press **EXPORT CONVERSATION + LOGS ZIP** in the surveillance terminal. The game saves a timestamped `.zip` in `user_data/exports/` next to the game and opens that folder in Windows Explorer. Attach the ZIP to the ChatGPT conversation to inspect the incident.

Each archive contains:
- `conversation.txt`: the full text currently visible in the terminal (including player, Eli, and authoritative OBSERVATION/SYSTEM lines)
- `diagnostics.jsonl`: player input, one structured goal proposal and inference latency, verified engine goals, any capability/data issue, and real Godot outcomes (older exported sessions may contain the retired two-pass review events)
- `conversation_state.json` and `current_room.json`: conversation state plus the exact room flags/items when exported
- `export_manifest.json` and `README.txt`: session identifier and how to interpret the export

The ZIP is **created locally only after clicking the button**, is never automatically uploaded, and excludes the GGUF file, other saved conversations, microphone recordings, passwords and API credentials. Its contents can include everything you typed and Eli said, so review the ZIP before sharing it.

The game also appends displayed conversation lines (YOU, ELI, OBSERVATION and SYSTEM) to `user_data/<session_id>.transcript.txt` as they happen. When reopening the game, it restores that session's visible conversation without replaying Eli's voice or duplicating saved lines. **NEW SESSION / RESET ROOM** starts a separate transcript, leaving the previous session's text file available for investigation. Like save files, these private local transcripts are retained by the in-game updater; you can remove old transcript files manually after you no longer need them. This update cannot reconstruct dialogue that disappeared during restarts **before** transcript persistence was installed. Neither the text files nor the diagnostics are sent to any external service.

## How Eli handles instructions

The production AI now interprets each player utterance as either conversation or **up to five physical end goals in order**, using a **single inference on your existing local GGUF**. There is no second AI opinion, no regex phrasebook deciding what you meant, and no requirement for the model to copy fragments of your sentence as action permission. Godot itself checks whether the room supports each goal, automatically walks Eli to an interactable object, performs the interaction, and records the true result. For example, asking him to open the door should not require a separate walk-to-door command. The action queue stops after an actual failed step. Eli can still attempt unusual physical experiments without hallucinating a new puzzle effect.

If the model supplies a goal the physical engine cannot safely perform, you see a specific **SYSTEM: Goal not executed** message, rather than a fabricated explanation from Eli. Codes are accepted only if you state the four digits or Eli has read them through a confirmed close-up note inspection. The game never treats model-spoken clues as verified observations.

## Experimental actions

Eli can attempt unusual things such as knocking on the door, tapping a flashlight against the desk, dancing, or testing a wall. The small local GGUF interprets the physical intention and sends a freeform `experiment` to Godot, which actually moves/gestures and reports the attempt. An experiment by itself does not magically unlock doors, make new items or change breaker/puzzle state. Existing real puzzle actions like flipping the breaker, picking up the flashlight and entering a code still follow authoritative engine rules. A hypothetical suggestion or a question never authorizes a physical attempt.

## Optional Chatterbox Nano voice (experimental)

Close the game and double-click `SETUP_CHATTERBOX_NANO.cmd` in the portable folder.
Accept the one-time download only if you have several GB free on the game drive
(recommend at least 8 GB for the model, Python, CPU Torch, and temporary/cache files).
The script downloads pinned official Chatterbox source (MIT), the Nano model
(MIT), pinned Perth source and a checksum-verified uv bootstrap; it installs a
game-local Python 3.11 environment without requiring a global Python or Git
installation. The model files required by the official loader total about 2 GB,
not including dependencies. Setup performs a real local WAV smoke test and
only then creates the ready marker. Restart the game to use Nano. An initial
synthetic built-in voice is used; if desired put a clean, authorized reference
recording longer than five seconds at `models/chatterbox-nano/eli-reference.wav`
before starting the game. Only use recordings you have permission to clone.
No cloud inference or speech upload, and no download during ordinary gameplay.
Nano stays loaded in one separate CPU worker and uses the current dialogue
emotion to choose supported style tags (not guaranteed acting intensity).
If missing or if synthesis fails, Piper remains available; subtitles and
microphone are unchanged. To disable, close the game and rename
`models/chatterbox-nano/ready.json`. The updater preserves models/ including
the optional runtime; if moving to a different drive or machine, rerun setup
if its environment no longer works. Listen to sample.wav after setup.
Official model: https://huggingface.co/ResembleAI/chatterbox-nano
Official code: https://github.com/resemble-ai/chatterbox

### Voice Studio and low-latency buffering
Open VOICE STUDIO in the game to select the built-in Nano voice, Joe (an
on-demand local synthetic reference from the bundled CC0 Piper model), or
import your own authorized WAV references (5–30 seconds). References are copied
to models/chatterbox-nano/voices and persist through updates. Preview measures
request-to-playable-WAV latency for a fixed line without changing Eli's
conversation. Select 0 threads for automatic, or compare thread counts on your
hardware. Select Piper for speed. Low-latency mode sends a short opening
segment and prefetches one WAV during playback; toggle off for longer segments
and continuity. This is sentence buffering, not true model-token streaming.
The worker logs model load, inference time, audio duration and CPU threads to
logs/nano-voice.log. Game logs contain time to playable audio. Nano's first
custom reference can take longer; conditionals are cached in memory.

### Native Chatterbox Nano Q8 (experimental, CPU)
Close the game and run `SETUP_NATIVE_NANO.cmd` from its portable folder.
The optional download is about 653 MB: pinned audio.cpp v0.9.4-jv.7 Windows
CPU portable runtime and MIT Nano Q8 GGUF conversion. Both downloads are
SHA256-checked. Setup starts the actual local C++ server and generates two
samples before writing the activation marker; no cloud speech inference.
Restart and open VOICE STUDIO, select Native Nano Q8, and compare previews
with the original Nano. Existing Joe/custom reference profiles work with
the native engine. The server loads once and remains resident until the
game closes, engine switches, or CPU thread count changes. The first preview
can include startup; compare subsequent previews. The UI identifies which
engine actually generated audio (including fallback). CPU speed and clone
quality depend on hardware; native is experimental, not guaranteed faster.
If native fails, official Nano and then Piper remain available. Models and
reference files stay in models/ and survive in-game updates.
Sources: https://github.com/delebash/audio.cpp and
https://huggingface.co/delebash/chatterbox-nano-GGUF .
