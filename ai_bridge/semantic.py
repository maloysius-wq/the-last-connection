"""Validate model-interpreted physical instructions without a phrase-by-phrase parser.

The GGUF interprets conversational language, but the engine alone owns state.
Each proposed act needs a verbatim span from this *current* player turn. This
validator is a security boundary, not an intent classifier: it checks evidence,
ordering, allowed targets/arguments and ambiguity, not exact command phrases.
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any

from .intent import mentioned_targets

MAX_STEPS = 5
ACTIONS = frozenset(("move_to", "inspect", "take", "use", "enter_code", "survey", "experiment"))
TARGETS = frozenset(("flashlight", "breaker_box", "keypad",
                     "exit_door", "maintenance_note", "desk", "wall", "floor", "ceiling"))
USABLE = frozenset(("flashlight", "breaker_box", "exit_door"))
# These are sentence-level safety checks for non-commands, NOT a dictionary of
# how to express physical instructions.
HYPOTHETICAL = re.compile(
    r"^\s*(?:what\s+if|if\b|suppose\b|imagine\b|i\s+(?:wonder|was\s+"
    r"thinking|think\s+about)|do\s+you\s+think|would\s+it|could\s+it|"
    r"should\s+(?:we|i)|why\b|how\b|what\b|when\b|where\b|who\b)",
    re.I)
NEGATION = re.compile(r"\b(?:do\s+not|don't|dont|never|not\s+to|"
                      r"shouldn't|should\s+not|stop\s+(?:touching|using|"
                      r"opening|pressing|turning|picking|grabbing|trying))\b", re.I)
PRONOUN = re.compile(r"\b(?:it|that|this|one|there|them)\b", re.I)
# Seeing or describing a prop never itself authorizes touching it.
OBSERVATION_PREFIX = re.compile(
    r"^\s*(?:i\s+(?:can\s+)?see|i\s+(?:am|'m)\s+looking\s+at|"
    r"there\s+(?:is|are|'s|'re)|you\s+(?:can\s+)?see)\b", re.I)
# Colloquial suggestions can be real directives; these are exceptions to the
# generic question/negation safeguard, not a command-phrase dictionary.
SUGGESTION_REQUEST = re.compile(
    r"^\s*(?:why\s+don't\s+you|how\s+about(?!\s+if\b))\b", re.I)

# These are speech-act / complexity HINTS, never a phrase-based permission
# system. The existing model still proposes all actions and the evidence/world
# validator still approves every proposed act. This prevents a second small-
# model review from vetoing a simple, fully grounded one-step request.
DIRECT_COMMAND = re.compile(
    r"^\s*(?:eli[,]?\s+)?(?:(?:please|just)\s+)?(?:go|walk|head|move|come|"
    r"pick|grab|take|bring|fetch|switch|turn|toggle|flip|"
    r"look|check|examine|inspect|read|survey|open|unlock|"
    r"enter|type|punch|try|use|activate|stop\s+by)\b", re.I)
ACTION_CHAIN = re.compile(r"\b(?:and|then|next|after\s+that|followed\s+by)\b", re.I)
REFLECTIVE_QUESTION = re.compile(
    r"^\s*(?:why(?!\s+don['’]?t\s+you\b)|"
    r"what|which|who|where|when|"
    r"how(?!\s+about\b)|"
    r"do\s+you\s+(?:think|remember|know|see|notice|hear)|"
    r"can\s+you\s+(?:see|hear|tell)|"
    r"does\s+it|is\s+it|is\s+there|are\s+there|"
    r"are\s+you|were\s+you|"
    r"would\s+it|should\s+(?:we|i)|what\s+if)\b", re.I)


def is_reflective_question(message: str) -> bool:
    """Grounded conversation takes priority for unambiguously *asking* Eli.

    Only the final independent sentence is considered. "Why did you resist?"
    is conversation; "Why did you resist? Turn it on!" remains an action turn.
    This is a speech-act boundary, not a list of commands Eli can understand.
    """
    if not isinstance(message, str) or not message.strip().endswith("?"):
        return False
    clauses = [re.sub(r"^\s*eli[,]?\s+", "", part.strip(), flags=re.I)
               for part in re.split(r"[.!?]+", message) if part.strip()]
    if not clauses or not REFLECTIVE_QUESTION.match(clauses[-1]):
        return False
    # A question appended AFTER a concrete instruction does not erase that
    # instruction. Let the semantic planner handle mixed instruction+question
    # turns while retaining the strict per-action authorization checks.
    return not any(DIRECT_COMMAND.match(clause) for clause in clauses[:-1])


def contains_explicit_action_request(message: str) -> bool:
    """Whether to TRY a second semantic inference on a misclassified turn.

    This does not authorize any physical action. Each reviewed operation still
    needs independent evidence and validation before reaching Godot.
    """
    if not isinstance(message, str):
        return False
    clauses = [part.strip() for part in re.split(r"[.!?;]+", message)
               if part.strip()]
    # For creative requests with no named prop, only invite a second MODEL
    # interpretation. This gate is never itself permission to act.
    invitations = ("please try ", "try to ", "do a ", "go ahead and ",
                   "let's try ", "could you try ")
    return any((bool(mentioned_targets(part)) and DIRECT_COMMAND.match(part))
               or part.lower().startswith(invitations) for part in clauses)


def needs_action_review(message: str, steps: Any) -> bool:
    """Audit potentially compound commands, not obvious one-step directives.

    A single clear action already has strict permission and world validation.
    Sending that action back to the same small GGUF for another opinion made
    'turn it on' fail despite Eli physically holding the only flashlight.
    Multi-step requests still get the extra coverage review.
    """
    if not isinstance(steps, list) or len(steps) != 1:
        return True
    if ACTION_CHAIN.search(message):
        return True
    clauses = [part.strip() for part in re.split(r"[.!?;]+", message)
               if part.strip()]
    return sum(bool(DIRECT_COMMAND.match(part)) for part in clauses) > 1


# Limit output structure, not Eli's in-character phrasing.
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["conversation", "action", "clarify"]},
        "speech": {"type": "string"},
        "emotion": {"type": "string", "enum": ["afraid", "cautious", "curious", "calm"]},
        "steps": {
            "type": "array", "maxItems": MAX_STEPS,
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": sorted(ACTIONS)},
                    "target": {"type": "string"},
                    "argument": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["action", "target", "argument", "evidence"],
                "additionalProperties": False,
            }
        }
    },
    "required": ["kind", "speech", "emotion", "steps"],
    "additionalProperties": False,
}

INSTRUCTIONS = (
    "\nSEMANTIC ACTION INTERPRETATION: Return ONE JSON object with "
    "kind=conversation,action,or clarify; speech (Eli's natural live reply); "
    "emotion; and steps (an array). This structured envelope is not spoken. "
    "Conversation and hypothetical questions have steps=[]; reply thoughtfully "
    "as Eli. Even a discussion of actions does not authorize doing them. "
    "Only execute physical tasks the remote operator actually instructs you "
    "to do NOW. Read the ENTIRE operator turn before generating any actions. "
    "Never stop after identifying the first valid instruction: include EVERY "
    "explicitly requested step and intended end-state. For example, picking "
    "up a flashlight AND turning it on must finish with flashlight ON, not "
    "merely held. A bare take action cannot satisfy a switch-ON request. "
    "Translate natural phrasing, indirect but clear requests and "
    "references to known objects into ordered steps, at most five. Use only "
    "action verbs move_to,inspect,take,use,enter_code,survey,experiment. Use only targets "
    "flashlight,breaker_box,keypad,exit_door,maintenance_note,desk,wall,floor,ceiling,room; room only "
    "for survey or an in-place experiment. Experiment is for novel "
    "physical attempts like knocking, dancing, shouting, shaking, pushing, "
    "or investigating unusual details. Its argument describes the attempt "
    "in Eli's natural words (120 characters maximum). The engine may "
    "simulate it without changing puzzle state. Do not substitute "
    "experiment for a normal physical task that the engine already supports. "
    "'Tell me what you see' after a survey is its spoken result, "
    "not a separate physical step. Do not invent prerequisites as separate "
    "steps: the engine handles necessary approach and flashlight pickup. "
    "For EVERY proposed physical step set evidence to the exact, shortest "
    "CONTIGUOUS quotation from the CURRENT user message authorizing that "
    "particular act (verbatim words, in original order). Never quote previous "
    "turns or world descriptions as evidence. Use one different evidence span "
    "per step. Quote just the action words, not the entire multi-step "
    "sentence; for example, 'grab that flashlight, turn it on, and look "
    "around' uses evidence 'grab that flashlight', 'turn it on', and "
    "'look around'. If asked to report what you see after looking around, "
    "one room survey already includes the report. "
    "An ambiguous reference, mixed-up targets, missing code, or "
    "uncertain instruction requires kind=clarify, steps=[] and a natural "
    "question. A clearly requested action uses kind=action. For flashlight "
    "use argument=on/off when specified, else empty. Enter_code needs the "
    "user's explicitly stated four digits; no guessed codes. For breaker_box "
    "and exit_door use, argument is empty. Experiment argument is the short "
    "physical attempt. Other arguments "
    "are empty. Do not append helpful extra actions. Never report physical "
    "success in speech before the engine confirms it. Keep speech short, "
    "frightened, believable and conversational, not a verbose monologue."
)


# A SECOND, narrowly scoped model pass is used only for physical requests.
# This is an independent coverage audit, not permission to perform actions.
# The same tiny local GGUF is reused, and the reviewer receives only a short
# world summary plus the original request and draft plan.
REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["action", "clarify"]},
        "steps": SCHEMA["properties"]["steps"],
        "reason": {"type": "string"},
    },
    "required": ["kind", "steps", "reason"],
    "additionalProperties": False,
}

REVIEW_INSTRUCTIONS = (
    "ACTION COMPLETENESS AUDITOR. You are checking the actions another model "
    "extracted from a single player's request. You DO NOT control the world. "
    "Re-read ALL of the current operator message independently, beginning to end. "
    "Ignore the draft until you've identified the entire set of explicitly "
    "requested physical operations, their order and intended result. "
    "The draft can be missing steps or may be entirely wrong. "
    "Do not rubber-stamp a plan just because its first step is correct. "
    "Critical example: 'let's start with picking up the flashlight on the "
    "table there, and turning it on' requires BOTH taking the flashlight and "
    "switching it ON. A draft containing only take/flashlight is INCOMPLETE. "
    "The same principle applies to all objects and phrasings. "
    "You may use one use/flashlight/on action when it performs both operations "
    "because the engine automatically picks up a flashlight before switching "
    "it on, but a bare take/flashlight is NOT enough. "
    "Surveying the room and telling the player what is seen is survey/room; "
    "the report comes from the confirmed post-survey state, not an invented "
    "extra physical step. Never add prerequisites that the engine already "
    "handles, unless the operator explicitly requested them separately. "
    "Every distinct user-requested physical outcome must be covered. "
    "Return kind=action with the COMPLETE, ORDERED list of 1-5 requested "
    "steps. Each step includes action, target, argument and a separate "
    "evidence quote taken EXACTLY AND CONTIGUOUSLY from this current user "
    "message, in sequence. Quote the smallest distinct action fragments, "
    "not the whole player sentence for every step. An instruction like "
    "'grab that flashlight, turn it on and look around' has evidence "
    "'grab that flashlight', 'turn it on', 'look around'. "
    "Only actions: move_to, inspect, take, use, enter_code, survey, experiment. "
    "Valid targets: flashlight, breaker_box, keypad, exit_door, "
    "maintenance_note, desk, wall, floor, ceiling, room (survey or "
    "in-place experiment only). For experiments use a short natural "
    "argument of the attempted behavior; never claim puzzle progress. "
    "Flashlight switch ON requires argument=on; switch OFF uses argument=off. "
    "For breaker use, report an empty argument (it restores power); "
    "for opening the door use an empty argument; do not encode switch "
    "directions or operation labels in argument. "
    "Other action arguments empty, except freeform experiments and keypad's "
    "four digits given "
    "explicitly in the user message. Do not infer a code. "
    "Do not treat a question about an imagined action, a negated instruction, "
    "or mere mention of an object as permission to touch it. "
    "If the user was only discussing possibilities, or action targets are "
    "ambiguous, or the proposed step count is too large, return kind=clarify "
    "with steps=[] and a brief reason. The output is JSON only."
)


def review_messages(message: str, draft: Any, world: dict[str, Any],
                    referent: str = "") -> list[dict[str, str]]:
    """Minimal local-GGUF review context, with no saved prompt or hidden clue."""
    objects = world.get("objects", {})
    visible = [name for name, obj in objects.items()
               if isinstance(obj, dict) and obj.get("visible") is True]
    request = {
        "current_player_message": message,
        "draft_steps_not_yet_executed": draft if isinstance(draft, list) else [],
        "visible_targets": visible,
        "held_objects": world.get("inventory", []),
        "last_unambiguous_object": referent,
        "flashlight_on": bool(world.get("flashlight_on")),
    }
    return [
        {"role": "system", "content": REVIEW_INSTRUCTIONS},
        {"role": "user", "content": json.dumps(
            request, ensure_ascii=False, separators=(",", ":"))},
    ]


class PlanRejected(Exception):
    """A proposed physical plan could not be verified; execute NOTHING."""


def _find_span(message: str, evidence: str, cursor: int) -> tuple[int, int]:
    """Find exact quoted player words, allowing whitespace or broad quotes.

    The GGUF sometimes quotes an entire joined instruction for its first
    step, then cites a later phrase inside that quote. Require distinct,
    ascending *starts*, rather than non-overlapping spans. A second action
    cannot reuse the same quote/start to gain additional permission.
    """
    if not isinstance(evidence, str) or not 3 <= len(evidence) <= 180:
        raise PlanRejected("Missing a short exact quotation for an action")
    quote = evidence.strip()
    start = message.casefold().find(quote.casefold(), cursor)
    end = start + len(quote)
    if start < 0:
        # Preserve the actual quoted WORDS but tolerate different formatting
        # of whitespace and harmless surrounding quotation marks.
        quote = quote.strip(' "“”‘’')
        pattern = r"\s+".join(re.escape(part) for part in quote.split())
        found = re.search(pattern, message[cursor:], re.I) if pattern else None
        if found:
            start, end = cursor + found.start(), cursor + found.end()
    if start < 0:
        # A small GGUF sometimes inserts a connective while quoting a
        # *real* instruction ("flip the lever up" versus the player's
        # "flip the lever so it's up"). Recover only an anchored, same-order
        # phrase from THIS utterance. Unlike a general intent parser, this
        # never invents evidence, changes targets, or guesses a keypad code.
        tokens = list(re.finditer(r"[a-z0-9]+(?:['’][a-z0-9]+)?",
                                  message[cursor:], re.I))
        quoted = [m.group().casefold() for m in re.finditer(
            r"[a-z0-9]+(?:['’][a-z0-9]+)?", quote, re.I)]
        best: tuple[float, int, int] | None = None
        if len(quoted) >= 3 and len(tokens) <= 300:
            contrary = ({"on", "off"}, {"up", "down"},
                        {"open", "close", "closed"}, {"lock", "unlock"})
            for i, token in enumerate(tokens):
                if token.group().casefold() != quoted[0]:
                    continue
                for size in range(len(quoted), min(len(quoted) + 4,
                                                   len(tokens) - i) + 1):
                    window = tokens[i:i + size]
                    original = [m.group().casefold() for m in window]
                    if original[-1] != quoted[-1]:
                        continue
                    if any(bool(set(original) & choices) and
                           bool(set(quoted) & choices) and
                           set(original) & choices != set(quoted) & choices
                           for choices in contrary):
                        continue
                    first = cursor + window[0].start()
                    last = cursor + window[-1].end()
                    if re.search(r"[.!?;\n]", message[first:last]):
                        continue
                    score = SequenceMatcher(None, quoted, original).ratio()
                    if score >= 0.76 and (best is None or score > best[0]):
                        best = (score, first, last)
        if best:
            _, start, end = best
    if start < 0:
        raise PlanRejected("Model action is not quoted from this player turn")
    return start, end


def _non_command_context(message: str, start: int, evidence: str) -> bool:
    # Consider the surrounding independent sentence, not the previous user
    # turn or an unrelated earlier instruction.
    boundary = max(message.rfind(x, 0, start) for x in ".!?;\n")
    preceding = message[boundary + 1:start]
    context = preceding + evidence
    suggested_directive = bool(SUGGESTION_REQUEST.search(context))
    if HYPOTHETICAL.search(context) and not suggested_directive:
        return True
    # A negated imperative cannot be converted into a positive engine action.
    # Stop at a comma: "don't touch the door, grab the light" has a separate
    # positive command; neither one authorizes acting on the *door*.
    local = preceding.rsplit(",", 1)[-1] + evidence
    if suggested_directive:
        # "Why don't you try..." is a positive request, not a prohibition.
        local = SUGGESTION_REQUEST.sub("", local, count=1)
    return bool(NEGATION.search(local) or OBSERVATION_PREFIX.search(local))


def validated_steps(raw: Any, message: str, world: dict[str, Any],
                    referent: str = "") -> tuple[dict[str, str], ...]:
    """Return whole authorized plan or raise PlanRejected. Never partial-plan."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_STEPS:
        raise PlanRejected("Invalid number of action steps")
    objects = world.get("objects", {})
    cursor = 0
    previous_target = ""
    result: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise PlanRejected("Malformed action step")
        action, target, argument, quote = (item.get(k) for k in
                                           ("action", "target", "argument", "evidence"))
        if (not isinstance(action, str) or action not in ACTIONS or
                not isinstance(target, str) or not isinstance(argument, str)):
            raise PlanRejected("Unknown action, object, or argument")
        start, end = _find_span(message, quote, cursor)
        cursor = start + 1  # distinct ordered starts; nested broad quotes okay.
        # Check the actual quoted span, not the model's paraphrase: it may
        # have skipped an inserted "don't", "not", or other safety word.
        evidence_here = message[start:end]
        if _non_command_context(message, start, evidence_here):
            raise PlanRejected("A hypothetical or negated request cannot authorize action")
        # Inspecting the whole room is the engine's survey operation.
        # This is an action synonym, not another player-phrase dictionary.
        if action == "inspect" and target == "room":
            action = "survey"
        if action == "survey":
            if target != "room" or argument:
                raise PlanRejected("Survey is only valid for the visible room")
        elif action == "experiment" and target == "room":
            if not 2 <= len(argument.strip()) <= 120 or re.search(r"[\r\n\x00-\x1f]", argument):
                raise PlanRejected("Invalid creative action")
        else:
            if target not in TARGETS:
                raise PlanRejected("Unknown physical target")
            visible = (isinstance(objects.get(target), dict) and
                       objects[target].get("visible") is True)
            revealed_later = (target == "maintenance_note" and
                              any(step["action"] == "use" and
                                  step["target"] == "breaker_box" for step in result))
            if not visible and not revealed_later:
                raise PlanRejected("The target is not visible or obtainable yet")
            if action == "take" and target != "flashlight":
                raise PlanRejected("Object cannot be carried")
            if action == "experiment" and (
                    not 2 <= len(argument.strip()) <= 120 or
                    re.search(r"[\r\n\x00-\x1f]", argument)):
                raise PlanRejected("Invalid creative action")
            if action == "use" and target not in USABLE:
                raise PlanRejected("Object cannot be activated")
            if action == "enter_code":
                if target != "keypad" or not re.fullmatch(r"[0-9]{4}", argument):
                    raise PlanRejected("Keypad needs four specific digits")
                if argument not in message or argument not in quote:
                    raise PlanRejected("Code was not explicitly provided by the player")
            elif action == "use" and target == "flashlight":
                if argument not in ("", "on", "off"):
                    raise PlanRejected("Invalid flashlight mode")
                # Explicit ON/OFF is idempotent. Never let a small model omit
                # that field and accidentally toggle an already-on light off.
                requested_modes = {mode.lower() for mode in
                                   re.findall(r"\b(?:on|off)\b", quote, re.I)}
                if len(requested_modes) > 1:
                    raise PlanRejected("Ambiguous flashlight state")
                if argument and argument not in requested_modes:
                    raise PlanRejected("Flashlight state contradicts the player")
                if not argument and requested_modes:
                    argument = next(iter(requested_modes))
                if not requested_modes and argument:
                    raise PlanRejected("Flashlight state was not requested")
                if re.fullmatch(r"(?:turn|switch)\s+(?:on|off)\s+(?:the\s+)?light", quote, re.I):
                    if previous_target != "flashlight" and referent != "flashlight":
                        raise PlanRejected("Ambiguous room light versus handheld flashlight")
            elif action == "use" and target == "breaker_box":
                # Godot's breaker USE operation has no parameters; it raises
                # the lever and restores power. A model may still express
                # the requested direction as "on", "up" or "flip_up".
                # Normalize those representations, not the player's intent.
                if argument not in ("", "on", "up", "flip_up",
                                    "turn_on", "switch_on", "activate"):
                    raise PlanRejected("Unsupported breaker mode")
                if re.search(r"\b(?:off|down|deactivate)\b", evidence_here, re.I):
                    raise PlanRejected("Cannot treat breaker OFF as power ON")
                argument = ""
            elif action == "use" and target == "exit_door":
                # Opening a locked door can be attempted, but only the engine
                # can decide whether it actually opens.
                if argument not in ("", "open", "try_open", "pull", "push"):
                    raise PlanRejected("Unsupported door operation")
                argument = ""
            elif argument and action != "experiment":
                raise PlanRejected("Unrequested action argument")
            names = mentioned_targets(quote)
            if action != "experiment" and names and (len(names) != 1 or target not in names):
                raise PlanRejected("Action target contradicts the quoted player request")
            if not names and PRONOUN.search(quote):
                # Pronoun must refer to a single object, not whichever target
                # the LLM happens to choose. New physical steps take priority
                # over older conversational focus.
                recent = mentioned_targets(message[:start])
                if previous_target:
                    if target != previous_target:
                        raise PlanRejected("Pronoun does not match earlier queued target")
                elif len(recent) == 1:
                    if target not in recent:
                        raise PlanRejected("Pronoun differs from current-turn referent")
                elif recent:
                    raise PlanRejected("Ambiguous pronoun")
                elif target != referent:
                    # A held object is a stronger physical referent than a
                    # stale conversational focus. "You're already holding it.
                    # Turn it on!" must not fail because Eli omitted the word
                    # flashlight. Do not guess when zero/multiple items are held.
                    inventory = world.get("inventory", [])
                    held = [name for name in inventory
                            if isinstance(name, str) and name in TARGETS] if isinstance(inventory, list) else []
                    holding_context = bool(re.search(
                        r"\b(?:holding|held|in\s+your\s+hand|you(?:'re|\s+are)\s+carrying)\b",
                        message[:start], re.I))
                    explicit_mode = action == "use" and target == "flashlight" and argument in ("on", "off")
                    if not (len(held) == 1 and held[0] == target and
                            (holding_context or (not referent and explicit_mode))):
                        raise PlanRejected("Unresolved pronoun")
            previous_target = target
        # The report of what Eli sees comes from one successful survey.
        # Model-generated duplicate surveys should not make him survey twice.
        if not (action == "survey" and result and
                result[-1]["action"] == "survey" and result[-1]["target"] == "room"):
            result.append({"action": action, "target": target, "argument": argument})
    return tuple(result)
