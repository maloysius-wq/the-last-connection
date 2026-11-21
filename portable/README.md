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
- **Voice and typing share the same AI/action logic.** Hold **V** (when the text box is empty) or the **HOLD TO TALK** button, speak, and release. The recorded audio is transcribed by bundled local whisper.cpp, then the transcript is sent as a normal message to Eli. The release sends no voice data to the cloud.
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

**Hold V** with an empty input box, or hold the on-screen button. Release after speaking. If the microphone is unavailable, check Windows **Settings > Privacy & security > Microphone**, your input device, and audio input permissions for desktop apps. The **MIC** slider adjusts the silence/noise threshold, not your operating system's device gain.

If recognition is inaccurate, use a quiet microphone and short, clear statements or type normally. Eli's captions always remain visible, even if synthesis fails or is muted. Press **SKIP** to cut off his current voice output without deleting the transcript. **TEXT ONLY** disables both incoming microphone capture and outgoing synthesis.

The microphone's WAV bytes are sent only to the local AI bridge on `127.0.0.1:8765`, and the bridge invokes the packaged local whisper.cpp command-line tool. Recordings and synthesized temporary WAV files are deleted from `temp/` after processing. No online speech APIs are used; the separate **CHECK FOR UPDATES** feature continues to contact GitHub only when explicitly clicked.

Bundled voice engine sources and notices:
- [whisper.cpp v1.8.3](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.8.3) (MIT) and `ggml-tiny.en-q5_1.bin` Whisper transcription model
- [Piper 2023.11.14-2](https://github.com/rhasspy/piper/releases/tag/2023.11.14-2) (MIT)
- [Piper en_US-joe-medium voice v1.0.0](https://huggingface.co/rhasspy/piper-voices/tree/v1.0.0/en/en_US/joe/medium), per-voice dataset card lists CC0. The model card is bundled in the voice directory.
