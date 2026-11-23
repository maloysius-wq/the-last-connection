# Eli interaction pipeline: next architectural redesign

Status: PROPOSAL ONLY, not implemented. Drafted from the **2026-11-23 real GGUF session ZIP** and the current main source. Preserve the shipped safeguards.

## What is shipped now

- Typed messages and local Whisper.cpp voice transcription both enter the exact same `godot/scripts/main.gd::_submit` path.
- Godot sends current input, session ID and the authoritative world snapshot to `POST /api/decide` on 127.0.0.1.
- `Agent.decide` loads compact session dialogue/facts and uses the local GGUF to emit a structured `kind/speech/emotion/steps` interpretation, or a direct conversational reply for a reflective question.
- `Agent` can request a second local GGUF review for compound, empty or uncertain action plans. `validated_steps` verifies current-turn evidence, target visibility, supported actions and specific arguments; it cannot mutate the world.
- Godot queues up to five approved actions and runs `world.perform_action` sequentially. The engine already **automatically approaches a target** when taking, using, inspecting or entering a code. State changes (breaker, inventory, code, exit) occur only in Godot. The queue stops after a failed operation.
- Each verified result is posted to `/api/outcome` and recorded in the session. Intermediate steps generate no extra spoken response; on the final step, the local GGUF may generate Eli's grounded natural reaction. Piper renders a WAV if speaking is enabled; subtitles persist in all modes.
- The current implementation can make additional GGUF calls for independent review, pre-action dialogue rewriting, clarification rewriting and post-action reaction. They account for some of the delay and amplify inconsistent interpretations.

## Real-session evidence

Uploaded file: `TheLastConnection-eli_1795455569_2827-1795456140.zip`.

12 player inputs resulted in eight completed physical actions across five turns. Seven turns had no executed action; one was the operator venting frustration rather than asking for action. After the keypad accepted 4317, Eli did **not** open the exit and the world still had `escaped=false`.

Specific failures:
- `go over to the pinpad and input that code`: both model passes correctly proposed move + `enter_code 4317`; the validator demanded digits in the *current* input even though Godot had confirmed an inspection of the note reading RESET SEQUENCE 4317.
- `Press it NOW` and `Enter the code into the keypad`: proposals included a stale `GO TO THE KEYPAD` evidence quote from an earlier user turn and/ or a reviewer emitted an unsupported `use keypad`; the whole plan was rejected.
- `Can you open the door now?`: first GGUF emitted an empty action plan and falsely said the already-unlocked door was open; reviewer proposed a valid door use plus an invented keypad operation with 1234. Reconciliation vetoed the door opening even though Godot would have approached it automatically.
- Clarification fallback used further GGUF calls to invent questions about reachability, code confirmation and whether the keypad was in view, although Godot's snapshot made those facts available.

## Shipped immediate fixes

- PR #30: recognize an engine-confirmed code from a successfully inspected note when explicitly referenced by the player; normalize `use keypad` carrying supported four-digit input to `enter_code`, still checked against explicit typed digits or observed note; salvage **one** independently evidence-verified goal from noisy reviewer extras only for a noncompound directive; don't claim an unlocked door is open or demand separate walking permission. Regression tests replay the uploaded model proposals and adversarial counterexamples.
- PR #31: reject explanation-only questions such as `Would you tell me how to open the door?` from being treated as execution instructions, while preserving polite `Can you try opening the door now?` and contextual `Press it NOW`. More tests safeguard the boundary.
- These changes are not proof that the user's local GGUF always generates useful proposals; CI replays captured outputs but does not run their private model or microphone.

## Proposed next system

1. **Extract end goals, not micromovements.** The model proposes structured objectives, for example `open(exit_door)`, `read(maintenance_note)`, `enter_discovered_code(keypad)`, `take(flashlight)`, or `experiment(wall, "knock")`. Explicitly requested standalone movement remains possible. The engine builds required approaches and interaction animations from its own scene graph and state. Do not require the model to generate `move_to` then `use` for a routine operation.
2. **Bind references to authoritative evidence.** Track the most recent inspected clue, object referent, held item, outstanding user goal and last confirmed outcomes as structured, source-tagged state; do not derive action authorization from Eli's generated prose or stale quoted instructions. A short direct follow-up such as `do it` may explicitly resume a still-valid named goal, with clear scope/expiry; it must not authorize an unrelated or denied act.
3. **Separate speech from physical authority.** One compact action-intent interpretation should decide the goals, and engine completion should be the only source of physical results. Eli's natural-language response can be generated from confirmed outcomes, ideally with no mandatory pre-action rewriting. For pure conversation, preserve the richer conversational prompt and avoid extra action review.
4. **Reduce veto-by-second-model.** Review only genuinely multi-goal or unresolved instructions; disagreement is an advisory signal, never a source of invented extra actions. The validator should distinguish invalid individual speculative extras from uncertainty about the entire requested task. For compound instructions, keep all-or-none authorization and sequential stop-on-failure execution.
5. **Visible uncertainty, not invented obstacles.** If a target is hidden, code not observed or a phrase genuinely ambiguous, ask about THAT missing detail. Never claim Eli cannot reach a visible target when Godot can automatically walk there. Preserve experiment attempts and interesting failure outcomes; the engine still decides what physically changes.
6. **Deterministic trace replay and latency diagnostics.** Log the actual current input, inferred goal, reference binding and provenance, validator decision, engine outcomes, and model-call count/duration under each local session ID without saving audio, secrets or model prompts. Add a regression harness that replays entire exported sessions, including known prior clues and user follow-ups. Measure action decision latency on real local GGUF hardware before making performance claims.

## Acceptance scenarios

- After an engine-confirmed close inspection of the maintenance note, `go over to the keypad and input that code` enters the observed 4317 without asking for digits a second time.
- `Press it NOW` after an unambiguous, recent keypad request may use only that verified current goal and code; it never guesses a code from the LLM.
- `try opening the door now` makes Eli physically approach and use the door. Unlocked is NOT the same as open; escape happens only after a successful engine action.
- `Would you tell me how to open the door?`, a hypothetical, negated directive or a user merely mentioning the door remains conversation-only.
- Multi-goal flashlight pickup + ON + survey executes each goal to completion, and stops if a real step fails. The final Eli response matches Godot observations.
- A creative request such as knocking on the wall visibly attempts the experiment; it never invents puzzle progression or items.
- Typed and transcribed voice commands remain identical after transcription; TTS/subtitle/mute/skip behavior and updater remain functional.

## Nonnegotiable safeguards

Do not modify or replace the user's GGUF or copy it onto C:. Keep normal gameplay entirely local. Preserve existing game saves and transcript exports, in-game opt-in GitHub updates, voice, keyboard focus, session diagnostics, world authority, and quote/negation guards until a replacement has equivalent or better tests. No automated scheduled work.
