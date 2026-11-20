"""Conservative, ordered plans for explicit multi-step player instructions.

These steps come from the player's CURRENT words, not model-proposed tools.
Godot remains responsible for visibility, reachability, and success at each step.
"""
from __future__ import annotations

import re
from .intent import PlayerIntent, _classify_clause

# Split ONLY where a new command begins. Never treat a list of objects joined
# with "and" as permission to act on each one.
_COMMAND_START = (
    r"(?:please\s+)?(?:go|walk|head|move|approach|step|stand|"
    r"pick|grab|take|collect|retrieve|turn|switch|flip|toggle|"
    r"activate|use|open|unlock|read|look|have\s+a\s+look|"
    r"inspect|check|examine|search|study|enter|type|punch|"
    r"input|submit|can\s+you|could\s+you|would\s+you|will\s+you)\b"
)
_SPLIT = re.compile(
    r"(?<=[.!?])\s+|[;\n]+|"
    r",\s*(?=" + _COMMAND_START + r")|"
    r"\b(?:and\s+then|then|after\s+that|next)\s*[,:]?\s*|"
    r"\band\s+(?=" + _COMMAND_START + r")",
    re.I,
)
_EXPLICIT_START = re.compile(r"^\s*" + _COMMAND_START, re.I)
_DIGITS = re.compile(r"\b([0-9]{4})\b")
MAX_ACTIONS = 6


def _simplify(steps: list[PlayerIntent]) -> list[PlayerIntent]:
    """Avoid redundant walking or pickup when a subsequent act already does it."""
    simplified: list[PlayerIntent] = []
    for step in steps:
        if simplified:
            prev = simplified[-1]
            if prev.target == step.target:
                if prev.action == "move_to" and step.action in (
                        "inspect", "take", "use", "enter_code"):
                    simplified.pop()  # Godot approaches before these actions.
                elif (prev.action == "take" and step.action == "use"
                      and step.target == "flashlight" and step.light_mode == "on"):
                    simplified.pop()  # Godot's flashlight ON includes pickup.
                elif (prev.action == step.action and
                      prev.light_mode == step.light_mode and
                      prev.argument == step.argument):
                    continue
        simplified.append(step)
    return simplified


def parse_sequence(text: str, focus: str = "") -> list[PlayerIntent] | None:
    """Return ordered safe steps, [] for an unsafe sequence, None if not a sequence.

    The operator must issue at least two distinct physical directives. Context,
    negated clauses and ordinary conversation never authorize an action. A
    malformed step in a recognized sequence fails closed rather than executing
    only some of the instructions.
    """
    if not isinstance(text, str):
        return None
    parts = [part.strip() for part in _SPLIT.split(text.strip()) if part.strip()]
    if len(parts) < 2:
        return None
    parsed: list[PlayerIntent] = []
    current_focus = focus
    invalid = False
    directive_count = 0
    for part in parts:
        step = _classify_clause(part, current_focus)
        explicit = bool(_EXPLICIT_START.match(part))
        if step.kind == "action":
            directive_count += 1
            if step.action == "enter_code":
                code = _DIGITS.search(part)
                if not code:
                    invalid = True
                else:
                    step = PlayerIntent(step.kind, step.action, step.target,
                                        step.light_mode, code.group(1))
            parsed.append(step)
            current_focus = step.target
        elif explicit:
            directive_count += 1
            # "Don't touch the door" is an instruction not to act, not a
            # malformed positive command. A question is not permission.
            if not re.search(r"\b(?:don't|dont|do\s+not|never|stop)\b", part, re.I):
                invalid = True
    if directive_count < 2:
        return None
    if invalid or not parsed or len(parsed) > MAX_ACTIONS:
        return []
    return _simplify(parsed)
