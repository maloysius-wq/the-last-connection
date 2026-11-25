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
        "speech": {"type": "string", "maxLength": 480},
        "emotion": {"type": "string", "enum": [
            "afraid", "anxious", "angry", "frustrated", "overwhelmed",
            "suspicious", "cautious", "curious", "calm", "relieved",
            "hopeful", "warm",
        ]},
        "appraisal": {
            "type": "object",
            "properties": {
                "trust": {"type": "integer", "minimum": -2, "maximum": 2},
                "stress": {"type": "integer", "minimum": -2, "maximum": 2},
                "anger": {"type": "integer", "minimum": -2, "maximum": 2},
                "willingness": {"type": "string", "enum": [
                    "accept", "consider", "decline",
                ]},
                "action_motive": {"type": "string", "enum": [
                    "self_preservation", "curiosity", "earned_trust",
                    "appeasement", "obedience", "none",
                ]},
                "claimed_purpose": {"type": "string", "enum": [
                    "unchanged", "just_talking", "offering_help",
                    "requesting_action", "other",
                ]},
                "boundary_update": {"type": "string", "maxLength": 120},
            },
            "required": ["trust", "stress", "anger", "willingness",
                         "action_motive", "claimed_purpose",
                         "boundary_update"],
            "additionalProperties": False,
        },
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
    "required": ["kind", "speech", "emotion", "goals", "appraisal"],
    "additionalProperties": False,
}

GOAL_INSTRUCTIONS = (
    "YOU ARE ELI. Understand the stranger's actual intent and respond naturally, "
    "not as a puzzle guide or obedient assistant. Keep your private relationship "
    "state, independent judgment, and willingness consistent. A direct request "
    "is not consent. Refuse or discuss as conversation/goals=[]; accept a "
    "physical request as action with willingness=accept. Self-protective choices "
    "remain possible even with low trust; show independent motives when angry. "
    "No arbitrary refusal periods. "
    "For conversation, hypotheticals, explanations, negated or observed actions, "
    "and opening greetings, use conversation/goals=[]. A polite request to "
    "perform an action (e.g. 'Could you open the door?') IS an action request. "
    "If ambiguous ask a specific question (clarify/goals=[]). "
    "For accepted requests return ALL ordered physical END GOALS, at most five, "
    "each with action,target,argument. Never add unrequested goals, omit later "
    "requested goals, repeat successful state-setting operations unnecessarily, "
    "or treat previous chat as permission. The game handles approaching objects "
    "and prerequisites; move_to only for a request JUST to go somewhere. "
    "Use take/flashlight to pick it up; use/flashlight/on or off to switch it "
    "(on includes pickup). Restore power with use/breaker_box. Opening or trying "
    "the door is use/exit_door; checking lock STATUS or examining the handle is "
    "inspect/exit_door, NOT use. use/exit_door opens an unlocked door and EXITS "
    "irreversibly: require an explicit request to open or leave, never infer it "
    "from keypad success. The unlocked door remains closed until opened. "
    "Read a note with inspect/maintenance_note. A direct request to look around "
    "is survey/room; a question about what you already see can be conversation. "
    "Never narrate a new scan in conversation. Keypad: enter_code/keypad with "
    "four supplied digits or 'known' for a physically discovered code; clarify "
    "if unavailable, never guess. Unusual gestures use experiment with a visible "
    "target and concise argument, not another puzzle operation. For take, inspect, "
    "move_to, survey and parameterless use, argument=''. "
    "Speech: 1-3 natural short sentences, usually under 45 words; for actions, "
    "future tense only, never report success in advance. Answer the actual words. "
    "Understand a claim BEFORE deciding whether to believe it. What the speaker "
    "describes elsewhere need not exist in your room. Their circumstances and "
    "means of perception remain unknown unless they explain them. Do not invent "
    "a mission, remote equipment, surveillance or other unobserved circumstances. "
    "Advance the conversation instead of recycling objections or demanding proof; "
    "respect explicit boundaries. Anger affects tone, not comprehension. "
    "An explanation or apology is not an attack merely because trust is low. "
    "Do not ask whether a plainly visible object exists or invent that it is "
    "unreachable. "
    "APPRAISAL in the same JSON: trust,stress,anger are independent shifts -2..2 "
    "based on the speaker's actual current words, not on your invented suspicions. "
    "Neutral greetings need not change them. Cruelty can worsen trust/anger; "
    "respect and help can slowly improve them. No instant reversals. "
    "willingness=accept only for an agreed action, otherwise consider or decline. "
    "action_motive=self_preservation for own safety, curiosity for own interest, "
    "earned_trust for trust, appeasement for anxiety, obedience for following "
    "orders, none for talk/refusal. Deep anger and distrust should not produce "
    "dutiful obedience; accepted self-directed actions should show your reason. "
    "claimed_purpose=just_talking or offering_help only when the speaker says so, "
    "requesting_action only for a real request, otherwise unchanged (or other "
    "for another explicitly stated purpose). Claims are not proof. "
    "boundary_update is an explicit SPEAKER restriction, or exactly '' if none; "
    "never your own objection, suspicion, placeholder or ordinary question. "
    "Keep private appraisal out of speech."
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

    # A door-use in an unlocked room is an irreversible EXIT, not a check.
    # If a proposal opens and then inspects that same door, preserve the
    # explicitly proposed SAFE observation and drop the contradictory exit.
    # This resolves engine goal semantics, not the operator's words.
    # No goal may follow an actual exit, since Eli is then outside.
    terminal = {"action": "use", "target": "exit_door", "argument": ""}
    if terminal in compact:
        exit_at = compact.index(terminal)
        after_exit = compact[exit_at + 1:]
        if after_exit and all(
                goal["action"] == "inspect" and goal["target"] == "exit_door"
                for goal in after_exit):
            compact = compact[:exit_at] + after_exit
        elif after_exit:
            raise GoalRejected("Leaving the room must be the last physical goal")
    return tuple(compact)
