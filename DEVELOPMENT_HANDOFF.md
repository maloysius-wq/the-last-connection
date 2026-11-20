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

## Grounded action/real location and plain-language dialogue release verified (Nov 19, 2026)

- User observed Eli falsely claiming actions, mentioning keypad while at breaker, and saying he moved when he did not. User asked about restoring slow second reasoning pass; decided **not** to restore it because an LLM cannot verify action execution, and the second blocking call harmed responsiveness.
- PR #8 merged as `b3fd74b5d99ec13da69657b7c2a46fbbc35cfafe`. GitHub Actions main run `44676806715` fully passed, including Windows package and permanent release publishing; Python suite **84/84 passed** and Godot engine smoke passed.
- Latest release: `portable-b3fd74b5d99ec13da69657b7c2a46fbbc35cfafe`, publicly accessible from `https://github.com/maloysius-wq/the-last-connection/releases/latest`. Permanent ZIP + SHA256SUMS, user can click in-game Check for Updates (if installed updater-enabled build).
- Main-run Actions artifact `14602293859` independently downloaded/inspected: 1,097 members, ZIP CRC clean, launcher, exported Godot game, updater, CPU and Vulkan local llama.cpp runtimes, exact release tag in build-info.json, no GGUF weights. Release asset (~125 MB ZIP) published by CI. Windows user-side in-place updating still needs playtest.
- Engine tracks true `actor_at` position and `last_observation`; verifies moves by position; persisted across save/restore including legacy positions. Natural movement requests parse better. Structured physical action proposals are followed by deterministic future-tense intention, then only verified Godot outcomes can be acknowledged (zero post-action LLM inference).
- Real Ollama and llama.cpp backends now use **plain prose generation for conversation** (no forced JSON response schema), with grounded location and last observation supplied. Spatial questions use deterministic world answer. Unverified recent physical claims are grounded against actual confirmed observations; ordinary autobiographical memories are not suppressed. Other/mock backends retain structured fallback.
- Tests also verify HTTP payloads for both plain language model backends; real local GGUF dialogue and rendered movement require user testing. If still shallow, next assess the selected GGUF model's capabilities and GPU/model fit, rather than bringing back a wasteful post-action pass.

## 2026-11-20 fresh-session physical perspective fix (user screenshot)

- User shared screenshot of a new first-contact session: Eli responded to a remote operator who had just arrived in a control room as though the **operator** owned the flashlight on Eli's desk and could pick it up, and said the exit was *still* locked despite no previous attempt. This was not evidence that saved session state actually leaked: the small model used misleading role/temporal language because the user turn mixed physical room JSON into the USER prompt, and the persona did not explicitly fix who could touch room props.
- PR #9 merged to main as `a4fd81534a90438fbfb497a942ccd42febe6604e`. Conversation now sends the **player's literal speech as USER text**; authoritative Eli room information, actor ownership, remote speaker topology, first-contact/confirmed-action counts and prior-door-attempt state go into SYSTEM context in one concatenated message, preserving the llama.cpp chat-template requirement. The player remains remote and can only communicate, never grab the in-room flashlight or operate the keypad.
- The persona reinforces Eli's perspective and says that the operator's precise location is unknown until they tell him. No invented earlier interactions or claims about how long the door has been shut.
- Added limited no-second-inference wording corrections for screenshot-specific role slips (`you've got a flashlight on the desk; can you grab/pick it up?` → object on Eli's desk and an Eli-facing question), and `still locked` only prior to a *confirmed* door attempt. Correction is scoped to the visible flashlight/physical world and aims not to rewrite normal personal memories. Fixed sentence-boundary grammar.
- 6 additional screenshot-based Python regressions: separate system/user content, remote object ownership, first-contact state and session isolation, confirmed later door attempt, exact quoted reply, and ordinary childhood dialogue. Adjusted existing location-context test. Current Python suite **90/90 passed**; Godot headless tests passed.
- Main GitHub Actions release run `44756632816` succeeded. Latest permanent Release `portable-a4fd81534a90438fbfb497a942ccd42febe6604e` includes `TheLastConnection-Windows-Portable.zip` and `SHA256SUMS.txt`; main Actions artifact id `14639460972`. Downloaded artifact `TheLastConnection-Fresh-Session-Fix-Windows.zip` inspected independently: 1,097 entries, ZIP CRC clean, game+launcher+updater, CPU/Vulkan runners, expected build-info tag; no GGUF model weights.
- Next: user tests in-app update, starts fresh session, repeats control-room arrival story, verifies Eli refers to flashlight as *his room's object* and asks whether **he** should pick it up, and does not assert previous attempts. A real local Qwen3 4B generative playtest is needed; prompt/test guarantees do not establish perfect natural roleplay.


## 2026-11-20: keypad movement and persistent chat focus

- User screenshot shows Eli stationary beside desk after player said: **"Okay great. Go over to the pin pad and take a look at the red glowing screen."** The model replied in fluent prose that it was walking but the game showed Ready and no movement.
- Root cause confirmed in `ai_bridge/intent.py`: target aliases accepted `keypad` but not `pin pad`; the verb matcher interpreted "take a look" as physical `take`, and "Have a look" was rejected as a question due to `QUESTION_PREFIX`. With unrecognized intent, agent called `converse` and never emitted a physical action, despite its text falsely claiming movement.
- Added aliases for PIN pad and its red indicator, explicit inspection phrases, `take(?! ... look)` exclusion, and guarded `Have a look` imperative. Combined "go ... and take a look" becomes one authorized `inspect keypad` action. Godot already physically moves to an inspected object before emitting its observed description. Code-entry on pin pad is recognized. Conversation mode now blocks the specific unverified "I'm already on my way" claim when no action is executed.
- UI: keep LineEdit editable while model is processing; send button remains disabled until idle, and Enter when busy does not drop the draft. Deferred `grab_focus` following send, completion, reset, update dialog dismissal and OS window focus; on `focus_exited` the terminal retakes keyboard focus except when a modal dialog is open. Camera/log click no longer strands typing.
- New Python screenshot regression tests plus Godot headless smoke checking actual keypad movement/inspection, chat focus after transmit/idle, and ability to draft while inference runs. The Godot smoke disconnects normal AI bridge callbacks to prevent localhost HTTP errors in test-only room simulations.
- Require GitHub CI Python, Godot, and Windows packaging green before merge. User can then update via in-game Check for Updates; test with their local GGUF and actual mouse/keyboard interaction.

## 2026-11-20 pin-pad movement and chat focus release verified

- Screenshot player request: `Okay great. Go over to the pin pad and take a look at the red glowing screen.` Eli said `I'm already on my way to the keypad` but never moved and the terminal showed Ready. Root cause in `ai_bridge/intent.py`: `pin pad` missing target alias; `take a look` was not reliably parsed as inspection, leading to conversational `wait` with false motion narration.
- PR #10 merged as `cc674c44455bf6da68da79c664494752760d38f2`. Added pinpad aliases, red glowing screen/indicator descriptions, look-at phrases, code entry on pin pad, and prevented `take a look` from being treated as a physical `take`. `Have a look` now bypasses the overbroad question-prefix guard. Combined `go to pin pad and take a look at red glowing screen` grounds to `inspect keypad`, which Godot automatically physically walks to and observes, one action.
- Conversational path now corrects false *in-progress* movement claims when no action was issued instead of asserting character movement without engine verification.
- Godot chat input remains editable while Eli thinks, retains draft, and deferred-focus-restores after clicking Transmit, response completion, new session, update modal dismissal, focus changes and window reactivation. Modal update dialog retains focus until closed. Submit remains blocked while a request or physical action is outstanding.
- PR and main tests: **99 Python tests passed**, real Godot headless smoke passed with **no engine errors**, including keypad inspection from across the room, chat focus restoration and typing during pending HTTP request. Windows packaging CI passed.
- Latest permanent GitHub Release `portable-cc674c44455bf6da68da79c664494752760d38f2` created by main run `44760190821`, with published `TheLastConnection-Windows-Portable.zip` and `SHA256SUMS.txt`.
- Independently downloaded main-run Actions artifact `14641335934` to `TheLastConnection-Keypad-Focus-Fix-Windows.zip`: 1,097 entries, no CRC errors, confirmed launcher, Godot game, updater, CPU and Vulkan local runners, exact release-tag metadata, no GGUF weights.
- Player may install with in-game **CHECK FOR UPDATES** or download from `https://github.com/maloysius-wq/the-last-connection/releases/latest`. No model replacement needed. Actual Windows UI and chosen local GGUF playtest still required to validate real-world focus persistence and interaction timing.


## 2026-11-20: screenshot failure when flashlight referenced as "that"

- User screenshot: Eli says flashlight is on desk and asks if remote player sees it. User replies "I'm able to see it. Please pick that up and turn it on." Eli responds at length saying he grabs flashlight and presses switch, but webcam shows him standing at breaker and terminal shows Ready with no OBSERVATION. No Godot action happened.
- Root cause: action classifier permits demonstratives only when `state.focus` was set; reference tracking focused on player text and confirmed outcomes, **not on an unambiguous physical object Eli mentioned in his most recent conversational reply**. The user's follow-up has no explicit "flashlight", so defaulted to free-chat LLM mode; the free-chat guard missed "I'll grab" and "I pressed" false physical claims.
- Added `mentioned_targets` in intent and `state.referent` in Agent: one unique visible prop named in Eli's latest reply becomes the referent for follow-up "it/that". Several visible props or no clear object produce no referent; never guess. Confirmed actions retain referent; older stored `focus` used only for backward compatibility when no explicit referent field exists.
- Added post-generation natural-dialogue guard for first-person claimed/unexecuted physical actions. A false "I'll grab/pressed it" is replaced by confirmed in-room state, not recorded as a success or executed without explicit player authorization. Ground action claims to the correct prop, and preserve autobiography about objects outside this room.
- Exact two-turn screenshot regression test on mock LLM (conversation mention → indirect user imperative → structured `use flashlight on`), no-second-inference outcome test, ambiguous references, no referent cases, false action narration, and personal-story protection.
- Godot smoke checks actor physically moves **from breaker to flashlight desk** and has inventory + flashlight_on true before saying pickup succeeded.
- Preserve one LLM request per player command and zero post-action requests; actual on-device user playtest needed to verify local GGUF conversation and camera.


## 2026-11-20: Check for Updates button appears inert

- User pressed **CHECK FOR UPDATES** in the self-updating Windows version and saw no visible response; asked whether the latest GitHub build was missing. Verified public `releases/latest` already returned stable `portable-50b93c80e4ea672a350bb4c7afa537994d0f2bf9` with both `TheLastConnection-Windows-Portable.zip` (~125 MB) and `SHA256SUMS.txt`; missing publication was not the issue.
- Investigated `godot/scripts/main.gd`. Earlier always-active chat fix connected `input.focus_exited` to a deferred `grab_focus` regardless of why focus was lost. This could interrupt a button click during mouse-down/mouse-up. Removed the global focus-exited recapture and instead assigned `Control.FOCUS_NONE` to Transmit, Check for Updates, and New Session buttons; clicks work without taking keyboard focus away from chat. Deferred refocus after sending, completion, modal dismissal and window reactivation remains.
- Update click now immediately sets button text to `CHECKING GITHUB...`, changes status to `Checking GitHub releases...`, and writes a SYSTEM log entry. Successful no-update checks and failed HTTP requests show durable visible status, not silent resets; dialog confirmation unchanged.
- Expanded headless Godot smoke to verify signal wiring, button focus modes, removal of intrusive blur callback, immediate status/log text, and reset after canceling a pending update check. Existing separate bridge and update-service HTTP tests still cover requests and explicit confirmation.
- Validate Python + Godot engine + Windows packaging CI before publishing; user should see immediate CHECKING GITHUB on click. If not, they may be running an older executable. Actual graphical Windows click test is still required.

## 2026-11-20 root-cause audit: multi-object context vs physical command

- User screenshots before and after latest update: Eli claimed to hold and turn on an untouched desk flashlight with no actual movement or OBSERVATION. Later message describes a flashlight, keypad, door, and breaker, then clearly commands flashlight pickup and activation.
- Confirmed source root cause: intent.py scans target names across the *entire* player message; any more than one target makes classify() return conversation. This routed a clear flashlight instruction to free-text model output, no Godot action. Existing single-object unit tests missed the complete utterance.
- Second failure: conversational action-claim guard missed forms such as curly apostrophes in 'I've got' / 'I'll turn', present-progressive 'I'm right there picking up', and 'light's on now'. Free conversation could present invented actions as actual.
- Fix: clause-by-clause command parsing to separate room-description context from one authorized physical instruction; per-clause negation and question filtering. Multi-target commands remain ambiguous. Expanded conversational physical-claim filter; no LLM narration is authoritative about physical acts.
- Regression tests use full user screenshots. Real Godot engine smoke now simulates decision HTTP completion and checks command dispatch through the game UI, actor travel, inventory pickup, switched-on light, and real outcome, in addition to previous direct world action tests.
- Maintain one model call per conversational player turn and zero post-action generation. Test actual local GGUF visually after release; CI cannot verify live model semantics.

## 2026-11-20 verified release for full-message action parsing

- PR #13 merged into main as 5bb03c9dd5fb8befd21cd19d1401778707790960. The production Python and Godot checks passed; 121 Python tests passed, including both complete playtest screenshot regressions and the new main.gd decision-to-world smoke. Windows production build run 44775176277 completed successfully.
- Public GitHub Release portable-5bb03c9dd5fb8befd21cd19d1401778707790960 published with TheLastConnection-Windows-Portable.zip (~125 MB) and SHA256SUMS.txt. Latest link: https://github.com/maloysius-wq/the-last-connection/releases/latest.
- Downloaded and independently inspected corresponding main-run Actions artifact 14649856318 (TheLastConnection-Verified-Actions-Fix-Windows.zip): 1,097 archive entries, no CRC failures, game executable, launcher, updater and correct build-info exact commit/tag, no GGUF model weights.
- User can use in-game CHECK FOR UPDATES after previous click-fix build; if still unresponsive, manually extract official release while preserving config.json, user_data, models, logs. Real on-device GGUF/Windows validation still needed, and rules-based hallucination detection cannot guarantee perfect truthfulness for all novel phrasings. Preserve authoritative action/observation mechanism.


## 2026-11-20 conversation-quality and desk collision pass

- New user screenshot confirms the flashlight command finally physically moves Eli, picks up prop and illuminates room. Remaining playtest issues: (1) first-contact "Hi Eli, I'm Max... help you escape" is answered "I haven't touched anything new. What would you like me to do?"; (2) world OBSERVATION followed by near-identical Eli "I picked it up and switched it on"; (3) "Okay, what do you see in the room?" returns "I'm standing right by the flashlight. The flashlight is in Eli's inventory. It is on", failing to survey the environment and leaking technical third-person engine description; (4) Eli appears embedded in table.
- Root cause (1): Agent._ground_dialogue replaced ENTIRE generated answer when ANY action-related clause triggered its safety filter. This erased greetings and produced canned administrative language. Replace with sentence-level removal of only unverified physical claims and a contextual first-contact fallback when needed. Preserve ordinary safe replies and true observations without a second LLM pass. Distinguish autobiography and real room-actions.
- Root cause (2): Godot Main displays verified OBSERVATION, then Agent._acknowledge duplicates same text. Keep evidence log but use a short character reaction "There we go. I can actually see a little better now." for first pickup+on.
- Root cause (3): _spatial_question matched broad "what do you see" and returned only _describe_location, including raw per-object descriptions. Separate broad room overview from precise position questions. New _describe_room composes first-person natural summary of visible props, lighting, and Eli's held light, no "Eli's inventory" or hidden clue text. _describe_location translates actor_at to desk/keypad/breaker and reports correct nearby truth.
- Root cause (4): world.object_positions flashlight (-1.7, -1.4) / note (-1.3,-1.4) overlap desk footprint z=-1.85..-0.95. Move interaction points to camera-side z=-0.40, route via aisle when coming from back-wall objects; relocate legacy saves with actors inside table on restore.
- Added screenshot-specific Python suite and Godot smoke assertions for desk clearance, safe movement, legacy saves and existing complete physical action flow. Update old tests expecting repetitive speech.
- Keep engine authoritative, natural character prose, zero second-inference post-action call and full CI validation.

## 2026-11-20 verified release: natural conversation and desk position

- PR #14 merged to main as `084ea611f83815739f548f950979d3f7310f065f`; CI main validation and Windows package passed. Python suite **133/133 passed**, including new screenshot natural-dialogue regressions, with real headless Godot gameplay, desk access, legacy save and physically routed action smoke passing.
- Main Windows release job `44782202845` succeeded and published permanent GitHub Release `portable-084ea611f83815739f548f950979d3f7310f065f` containing `TheLastConnection-Windows-Portable.zip` and `SHA256SUMS.txt`.
- Downloaded and inspected Actions artifact `14652613305` as `TheLastConnection-Natural-Dialogue-Desk-Fix-Windows.zip`: 1,097 ZIP entries, CRC check clean, build-info tag and commit exactly match released version; launcher, game and updater executables present, no bundled GGUF weights.
- Remaining user-side verification: use **CHECK FOR UPDATES**, repeat first greeting and room question after flashlight pickup, confirm Eli does not say technical inventory descriptions or a canned no-action disclaimer, and inspect the desk standing location visually on Windows. CI does not prove local GGUF naturalness.
