"""Validate model-interpreted physical instructions without a phrase-by-phrase parser.

The GGUF interprets conversational language, but the engine alone owns state.
Each proposed act needs a verbatim span from this *current* player turn. This
validator is a security boundary, not an intent classifier: it checks evidence,
ordering, allowed targets/arguments and ambiguity, not exact command phrases.
"""
from __future__ import annotations

import re
from typing import Any

from .intent import mentioned_targets

MAX_STEPS = 5
ACTIONS = frozenset(("move_to", "inspect", "take", "use", "enter_code", "survey"))
TARGETS = frozenset(("flashlight", "breaker_box", "keypad",
                     "exit_door", "maintenance_note"))
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
# Colloquial suggestions can be real directives; these are exceptions to the
# generic question/negation safeguard, not a command-phrase dictionary.
SUGGESTION_REQUEST = re.compile(
    r"^\s*(?:why\s+don't\s+you|how\s+about(?!\s+if\b))\b", re.I)

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
    "to do NOW. Translate natural phrasing, indirect but clear requests and "
    "references to known objects into ordered steps, at most five. Use only "
    "action verbs move_to,inspect,take,use,enter_code,survey. Use only targets "
    "flashlight,breaker_box,keypad,exit_door,maintenance_note,room; room only "
    "for survey. 'Tell me what you see' after a survey is its spoken result, "
    "not a separate physical step. Do not invent prerequisites as separate "
    "steps: the engine handles necessary approach and flashlight pickup. "
    "For EVERY proposed physical step set evidence to the exact, shortest "
    "CONTIGUOUS quotation from the CURRENT user message authorizing that "
    "particular act (verbatim words, in original order). Never quote previous "
    "turns or world descriptions as evidence. Use one different evidence span "
    "per step. An ambiguous reference, mixed-up targets, missing code, or "
    "uncertain instruction requires kind=clarify, steps=[] and a natural "
    "question. A clearly requested action uses kind=action. For flashlight "
    "use argument=on/off when specified, else empty. Enter_code needs the "
    "user's explicitly stated four digits; no guessed codes. Other arguments "
    "are empty. Do not append helpful extra actions. Never report physical "
    "success in speech before the engine confirms it. Keep speech short, "
    "frightened, believable and conversational, not a verbose monologue."
)


class PlanRejected(Exception):
    """A proposed physical plan could not be verified; execute NOTHING."""


def _find_span(message: str, evidence: str, cursor: int) -> tuple[int, int]:
    if not isinstance(evidence, str) or not 3 <= len(evidence) <= 180:
        raise PlanRejected("Missing a short exact quotation for an action")
    start = message.casefold().find(evidence.casefold(), cursor)
    if start < 0:
        raise PlanRejected("Model action is not quoted from this player turn")
    return start, start + len(evidence)


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
    return bool(NEGATION.search(local))


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
        cursor = end  # No reused, overlapping or out-of-order evidence.
        if _non_command_context(message, start, quote):
            raise PlanRejected("A hypothetical or negated request cannot authorize action")
        if action == "survey":
            if target != "room" or argument:
                raise PlanRejected("Survey is only valid for the visible room")
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
            elif argument:
                raise PlanRejected("Unrequested action argument")
            names = mentioned_targets(quote)
            if names and (len(names) != 1 or target not in names):
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
                    raise PlanRejected("Unresolved pronoun")
            previous_target = target
        result.append({"action": action, "target": target, "argument": argument})
    return tuple(result)
