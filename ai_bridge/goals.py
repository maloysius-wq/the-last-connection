"""Goal-oriented physical plans for Eli's production local model.

The model decides WHAT the operator requested. This module checks whether
those goals are executable in the authoritative world and resolves observed
facts such as a code Eli physically read. No regex phrasebook, quote matching,
independent second model, or model-written movement prerequisites participate
in production action authorization. Godot alone changes room state.
"""
from __future__ import annotations

import re
from typing import Any

MAX_GOALS = 5
PHYSICAL_ACTIONS = frozenset(
    {"move_to", "inspect", "take", "use", "enter_code", "survey", "experiment"}
)
OBJECTS = frozenset({
    "flashlight", "breaker_box", "exit_door", "keypad", "maintenance_note",
    "desk", "wall", "floor", "ceiling", "room",
})
# This is a map of ENGINE CAPABILITIES, not a dictionary of user phrases.
USABLE = frozenset({"flashlight", "breaker_box", "exit_door"})
TAKEABLE = frozenset({"flashlight"})
LIGHT_MODES = frozenset({"", "on", "off"})
# The physical engine only needs an action, target, and sometimes one true
# operation parameter. For these parameterless actions, any model-produced
# argument is descriptive context, NOT a command or a reason to cancel a
# correctly identified goal. Canonicalize it away before queuing to Godot.
# Parameter-bearing capabilities (flashlight mode, keypad digits, experiment
# gesture) keep separate, strict value validation below.
PARAMETERLESS_ACTIONS = frozenset({"move_to", "inspect", "take", "survey"})

GOAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["action", "conversation", "clarify"]},
        "speech": {"type": "string"},
        "emotion": {"type": "string", "enum": ["afraid", "cautious", "curious", "calm"]},
        "goals": {
            "type": "array", "maxItems": MAX_GOALS,
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": sorted(PHYSICAL_ACTIONS)},
                    "target": {"type": "string", "enum": sorted(OBJECTS)},
                    "argument": {"type": "string"},
                },
                "required": ["action", "target", "argument"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["kind", "speech", "emotion", "goals"],
    "additionalProperties": False,
}

GOAL_INSTRUCTIONS = (
    "YOU ARE ELI, initially inside a maintenance chamber. If the engine says "
    "you escaped, you are now beyond the doorway, outside camera view. A remote person "
    "speaks through a speaker, and only YOU can manipulate the room. Your "
    "primary job is to understand the person's ACTUAL current intent. "
    "In one response decide kind=conversation, action, or clarify. "
    "For an action request, output ALL ordered END GOALS the person asked "
    "you to accomplish, not a movement script and not an incomplete prefix. "
    "Each goal has action, target, argument. DO NOT copy quotes or justify "
    "steps using word fragments. NEVER invent a goal that wasn't requested. "
    "ARGUMENT IS AN EXECUTION PARAMETER, not the location or your reasoning. "
    "For take, inspect, move_to and survey set argument='' because the target "
    "already identifies what and where. For flashlight USE the argument is "
    "'on' or 'off'; for keypad entry it is the code or 'known'; for experiment "
    "it describes the physical gesture. "
    "A question about what could happen, a hypothetical, an explanation "
    "request, and a negated or merely observed action are conversation, "
    "NOT permission to act. Polite requests like 'Could you open the door?' "
    "ARE action requests. For each action goal, include the intended physical "
    "end-state even when it would require approaching the object. The GAME "
    "will automatically walk to visible objects and handle prerequisites: "
    "do not output a separate move_to just to reach a thing you will use, "
    "take, inspect, or operate. Explicit requests JUST to go somewhere are "
    "move_to. To pick up the flashlight use take/flashlight; to switch it "
    "on use use/flashlight/argument=on (this also picks it up if needed); "
    "switching it off is use/flashlight/argument=off. Turning room power on "
    "is use/breaker_box/empty argument. Opening or trying a door is "
    "use/exit_door/empty argument whether currently locked or unlocked. "
    "Reading a note is inspect/maintenance_note; looking around is survey/room. "
    "For keypad entry output enter_code/keypad and argument=the four digits "
    "given by the operator, or argument='known' if the operator refers to "
    "a code you physically discovered. If no known code or digits are "
    "available, kind=clarify and ask what code to enter; do not guess. "
    "For unusual physical attempts choose experiment with visible target "
    "and a concise argument describing the attempt. The engine may simulate "
    "it without a puzzle change. Do not turn a request to try knocking into "
    "a request to open a door or solve a puzzle. "
    "If a multi-part request says pick up flashlight, turn it ON, and restore "
    "power, include the ON and POWER goals, not merely walking to the panel. "
    "There may be at most five goals; if genuinely ambiguous ask a specific "
    "question. The prior chat is context ONLY, never permission to run an "
    "unrequested action. Previous successes and room state are facts, not "
    "invitations to skip actions. "
    "Never append a gratuitous action simply because it might be a sensible "
    "next puzzle step, or because you remember using that object earlier. "
    "The operator may ask you to test an operation or see IF a code works; "
    "that does not authorize a subsequent action on the result unless they "
    "also request it. Do not repeat a successful state-setting action just "
    "to reassure yourself. "
    "Speech is your natural in-character response. For an action, express "
    "brief FUTURE-TENSE intent without claiming anything succeeded yet. "
    "Conversation answers directly in your own words, not a puzzle checklist. "
    "Do not ask if objects already shown in your room exist, and do not "
    "invent that a visible target is out of reach. "
    "Never claim the unlocked door is OPEN until you physically exit it."
)


def remove_satisfied_compound_goals(
        goals: tuple[dict[str, str], ...], world: dict[str, Any]
        ) -> tuple[dict[str, str], ...]:
    """Elide redundant SET-STATE operations in compound plans.

    The model can accidentally append a reaffirmation of a previously
    completed task. Because these capabilities are idempotent, a second
    operation contributes no new physical result and can steal the final
    spoken reaction from the actual requested change. This is based only
    on the engine's CURRENT state, never a dictionary of player words.

    Preserve a lone already-satisfied goal so an explicit standalone retry
    still receives Godot's truthful 'already done' observation. If every
    proposed goal is already satisfied, preserve the first one for the same
    reason. This operation does not invent, reorder or activate any goal.
    """
    if len(goals) <= 1:
        return goals
    inventory = world.get("inventory", [])
    held = isinstance(inventory, list) and "flashlight" in inventory
    flash_on = bool(world.get("flashlight_on"))
    power_on = bool(world.get("lights_on"))
    def satisfied(step: dict[str, str]) -> bool:
        action, target, argument = (step["action"], step["target"], step["argument"])
        if action == "take" and target == "flashlight":
            return held
        if action == "use" and target == "flashlight" and argument in ("on", "off"):
            return flash_on == (argument == "on") and held
        if action == "use" and target == "breaker_box":
            return power_on
        return False
    remaining = tuple(goal for goal in goals if not satisfied(goal))
    return remaining if remaining else goals[:1]


class GoalRejected(Exception):
    """Invalid or unavailable physical goals, no partial execution."""


def observed_code(facts: Any) -> str:
    """Bind keypad data to an actual successful close inspection only."""
    if not isinstance(facts, list):
        return ""
    for fact in reversed(facts):
        if (not isinstance(fact, dict) or fact.get("success") is not True or
                fact.get("action") != "inspect" or
                fact.get("target") != "maintenance_note"):
            continue
        description = str(fact.get("description", ""))
        match = re.search(r"\bRESET SEQUENCE\s+([0-9]{4})\b", description, re.I)
        if match:
            return match.group(1)
    return ""


def known_code_context(facts: Any) -> dict[str, Any]:
    code = observed_code(facts)
    return {"confirmed_code": code or None, "source": "inspected_maintenance_note" if code else None}


def _current_user_digits(message: str) -> set[str]:
    # This checks untrusted numeric DATA, not a user-language action phrase.
    return set(re.findall(r"(?<![0-9])[0-9]{4}(?![0-9])", message))


def validate_goals(raw: Any, world: dict[str, Any],
                   player_text: str, facts: Any) -> tuple[dict[str, str], ...]:
    """Check engine capabilities and authoritative data, never wording.

    A missing target or code cancels the whole plan. A model may not
    hallucinate clues or a world transition. The execution engine independently
    rechecks each step immediately before moving/changing state.
    """
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_GOALS:
        raise GoalRejected("No complete actionable goals were provided")
    objects = world.get("objects", {})
    if not isinstance(objects, dict):
        raise GoalRejected("The room state is unavailable")

    typed_codes = _current_user_digits(player_text)
    # When several numeric candidates appear, don't guess which number was
    # affirmed or negated. That is data ambiguity, not a phrase-parsing rule.
    if len(typed_codes) > 1 and any(
            isinstance(g, dict) and g.get("action") in ("enter_code", "use")
            and g.get("target") == "keypad" for g in raw):
        raise GoalRejected("Several four-digit codes were mentioned; specify one")
    code_from_observation = observed_code(facts)
    result: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise GoalRejected("One goal is malformed")
        action = item.get("action")
        target = item.get("target")
        argument = item.get("argument")
        if (not isinstance(action, str) or action not in PHYSICAL_ACTIONS or
                not isinstance(target, str) or target not in OBJECTS or
                not isinstance(argument, str)):
            raise GoalRejected("Goal is not a supported room capability")
        argument = argument.strip()
        if action == "survey":
            if target != "room":
                raise GoalRejected("Survey only applies to the room")
        elif action == "experiment" and target == "room":
            if not 2 <= len(argument) <= 120 or any(c in argument for c in "\r\n\x00"):
                raise GoalRejected("Experiment needs a physical gesture")
        else:
            current_obj = objects.get(target)
            revealed_by_prior = (
                target == "maintenance_note" and
                any(goal["action"] == "use" and
                    goal["target"] == "breaker_box" for goal in result)
            )
            if not (isinstance(current_obj, dict) and
                    current_obj.get("visible") is True) and not revealed_by_prior:
                raise GoalRejected("That object is not visible yet")
            if action == "take" and target not in TAKEABLE:
                raise GoalRejected("This object cannot be carried")
            if action == "experiment":
                if not 2 <= len(argument) <= 120 or any(c in argument for c in "\r\n\x00"):
                    raise GoalRejected("Experiment needs a physical gesture")
            # Convert the model's generic interaction to an actual capability.
            if target == "keypad" and action == "use":
                action = "enter_code"
            if action == "enter_code":
                if target != "keypad":
                    raise GoalRejected("Only the keypad accepts digits")
                if argument.lower() in ("", "known", "discovered", "observed", "that code"):
                    if len(typed_codes) == 1:
                        # A code stated NOW outranks any older observed clue.
                        argument = next(iter(typed_codes))
                    elif len(typed_codes) > 1:
                        raise GoalRejected("Several codes were given; choose one")
                    else:
                        argument = code_from_observation
                if not re.fullmatch(r"[0-9]{4}", argument):
                    raise GoalRejected("Eli needs an actual four-digit code")
                if typed_codes and argument not in typed_codes:
                    raise GoalRejected("Chosen digits contradict the current operator message")
                if not typed_codes and argument != code_from_observation:
                    raise GoalRejected("Those digits were never provided or observed")
            elif action == "use":
                if target not in USABLE:
                    raise GoalRejected("That object has no engine use operation")
                if target == "flashlight":
                    if argument.lower() not in LIGHT_MODES:
                        raise GoalRejected("The flashlight supports on or off")
                    argument = argument.lower()
                elif target == "breaker_box":
                    if argument.lower() not in ("", "on", "up", "flip_up", "activate"):
                        raise GoalRejected("The room breaker can only be switched on")
                    argument = ""
                else:  # exit_door
                    if argument.lower() not in ("", "open", "try_open", "push", "pull"):
                        raise GoalRejected("The door supports an opening attempt")
                    argument = ""
        # An action without an engine parameter has nothing to interpret
        # in the model's descriptive argument. Silently drop that free text
        # instead of making the entire authorized goal sequence disappear.
        if action in PARAMETERLESS_ACTIONS:
            argument = ""
        result.append({"action": action, "target": target, "argument": argument})

    # A model should not generate robotic approach steps before a goal.
    # Collapse only redundant movement to the SAME target, not independent
    # relocations to distinct targets.
    compact: list[dict[str, str]] = []
    for i, goal in enumerate(result):
        next_goal = result[i + 1] if i + 1 < len(result) else None
        if (goal["action"] == "move_to" and next_goal and
                next_goal["target"] == goal["target"] and
                next_goal["action"] in ("take", "use", "inspect", "enter_code", "experiment")):
            continue
        if goal != (compact[-1] if compact else None):
            compact.append(goal)
    if not compact:
        raise GoalRejected("No executable goals remain")
    return tuple(compact)
