# The Last Connection | Portable Windows build

**This is the game build intended for D: (not the GitHub source ZIP).**

The package includes the Godot game executable, a packaged local Python AI bridge,
and a CPU-only llama.cpp server. It **does not bundle an AI model**, avoiding any
second 2.5+ GB download or copy. There is no Ollama, LocalForge or system-wide
Python/Godot installation required to play this Windows build.

## Install / play

1. Download the **TheLastConnection-Windows-Portable-NoModel** artifact from a successful
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
- This initial portable runner uses **CPU inference** and may be slow on older machines.
- The current game uses **typed** dialogue. Voice will be added later.

**Note:** GitHub Actions validates packaging and the mock gameplay path, but cannot
run your specific private model file. Real-model latency/compatibility needs a local
playtest after download.
