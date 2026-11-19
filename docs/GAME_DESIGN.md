# THE LAST CONNECTION — Game design v0.1

## Player fantasy

The player is stuck at a surveillance terminal, able to see a live feed of a trapped stranger named Eli, communicate by typing or push-to-talk, and guide Eli through puzzles and an increasingly untrustworthy environment. No direct character controls.

## Genre and tone

Psychological horror with deliberately grounded, slow-burn atmosphere, physically plausible interactions, and authored reveal sequences. Anxiety and ambiguity should emerge from conflicting perceptions and asymmetric information, never from an unbounded language model rewriting the world.

## Interaction principles

1. Player sees the camera feed, hears Eli, and can type or speak. Eli hears the player but cannot see the player's screen.
2. Eli can physically inspect objects, move, collect and use objects, ask questions, and volunteer suggestions.
3. Eli knows only perceived information and memory. The engine always owns authoritative reality.
4. A natural-language instruction becomes at most one validated physical action at first; advanced planning is deferred until interruption and recovery are reliable.
5. Character trust/fear affects dialogue and willingness to take risks, but puzzles must remain solvable without an arbitrary trust threshold.
6. Voice must have a text-only fallback, subtitles, and push-to-talk. Microphone use must be opt-in.

## Prototype 01: Maintenance Chamber

**Scene:** industrial, dark maintenance room with a desk, handheld flashlight, breaker panel, red keypad and heavy locked exit door.

**Interaction milestone:** Player asks Eli to pick up the flashlight; Eli responds, walks to it, takes it, the actual inventory changes, and Eli reports success based on engine feedback. A subsequent question about inventory must elicit an accurate response. If asked to interact with something invisible, Eli asks for clarification.

**Puzzle roadmap:**

- Puzzle A: Find flashlight and restore visibility.
- Puzzle B: Examine breaker panel and enable overhead lights.
- Puzzle C: Find an authored clue and enter a code into keypad.
- End beat: Eli leaves the camera frame; the camera continues filming an apparently empty room.

Only A is implemented fully in v0.1, B partially, and C is not implemented yet.

## Eli character bible

- Observant, capable, slightly sardonic under stress.
- Wary but cooperative at the beginning.
- Remembers contradictions and what the player has already taught.
- Fear can cause hesitation and more clarification questions, never a nonsensical hard lock.
- No unexplained plot knowledge or omniscient camera awareness.

## Technical boundaries

- Godot authoritative state: inventory, room objects, physical interactions, position, puzzle solutions.
- Python bridge: context composition, local Ollama calls, structured output parsing and validation, turn-based memory.
- Interface: `POST /api/decide` and `POST /api/outcome`; local host only.
- Future push-to-talk adapter: capture PCM in Godot; transcribe with whisper.cpp in local bridge; submit transcript through `/api/decide` exactly as typed text.
- Future voice output: synthesize Eli's speech via locally licensed voice engine; subtitle always shown and voice must be skippable.
- No model output is interpreted as a completed physical outcome.

## Risks to test before scaling

- Response latency on low-end CPU machines; benchmark 1.7B and 4B models separately.
- Model schema drift and hallucinated targets.
- Action cancellation/queuing while voice is active.
- Long-term memory summarization vs. authoritative world state.
- TTS and STT licensing for future commercial distribution.
- Local-server launch and error recovery on Windows.
