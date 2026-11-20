"""Conservative, deterministic action permission derived from the latest player turn.

The LLM writes natural dialogue and proposes actions, but a proposal is not
permission. Every physical act must be traceable to the player's current
request, not older messages or incidental object descriptions.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

TARGETS = (
    ("flashlight", r"\b(?:flashlight|flash light|torch|handheld light)\b"),
    ("breaker_box", r"\b(?:breaker(?: box)?|fuse box|electrical panel|power panel|power switch|main power|room lights?|ceiling lights?|overhead lights?)\b"),
    ("maintenance_note", r"\b(?:maintenance note|note|paper|memo|letter|written clue)\b"),
    ("keypad", r"\b(?:key\s*pad|pin\s*pad|pin[- ]?code\s*pad|number\s*pad|code\s*panel|"
               r"combination\s*lock|red\s+(?:(?:glowing|lit)\s+)?(?:screen|indicator|light)|"
               r"glowing\s+red\s+(?:screen|indicator|light))\b"),
    ("exit_door", r"\b(?:exit door|door|exit|doorway)\b"),
)
# Longer, multiword phrases first so "pick up" is correctly recognized.
VERBS = (
    ("enter_code", r"\b(?:enter|type|punch in|key in|input|submit)\b.{0,45}\b(?:code|digits?|numbers?|key\s*pad|pin\s*pad)\b|\b(?:code|digits?)\b.{0,20}\b(?:enter|type|try)\b"),
    ("take", r"\b(?:pick up|pickup|grab|take(?!\s+(?:a\s+)?(?:closer\s+)?look)|collect|retrieve|pick|fetch)\b"),
    ("use", r"\b(?:turn|switch|flip|toggle|activate|use|open|unlock|power up|switch on|switch off)\b"),
    ("inspect", r"\b(?:take\s+(?:a\s+)?(?:closer\s+)?look(?:\s+at)?|"
               r"have\s+a\s+look(?:\s+at)?|look\s+at|examine|inspect|read|"
               r"check(?:\s+out)?|study|search|investigate)\b"),
    ("move_to", r"\b(?:go(?:\s+over)?\s+to|walk(?:\s+over)?\s+to|head(?:\s+over)?\s+to|move(?:\s+over)?\s+to|move\s+toward(?:s)?|walk\s+toward(?:s)?|approach|step\s+over\s+to|stand\s+(?:by|near|in front of|beside|at)|come\s+(?:over\s+)?to)\b"),
)
QUESTION_PREFIX = re.compile(
    r"^\s*(?:what|why|how|where|when|who|which|whose|is|are|was|were|do|does|did|have|has|"
    r"tell me|describe|explain|i wonder|i'm wondering|i am wondering|what if|would it|should we)\b", re.I
)
POLITE_REQUEST = re.compile(r"^\s*(?:can|could|would|will)\s+you\b", re.I)
NEGATED = re.compile(r"\b(?:don't|dont|do not|never|stop|shouldn't|should not|not to)\b", re.I)
PRONOUN = re.compile(r"\b(?:it|that|this|there)\b", re.I)


@dataclass(frozen=True)
class PlayerIntent:
    kind: str = "conversation"
    action: str = ""
    target: str = ""
    light_mode: str = ""
    # Exposed to the model only as high-level guidance, not an execution permit.
    @property
    def prompt_hint(self) -> dict[str, str]:
        result = {"kind": self.kind}
        if self.kind == "action":
            result.update({"suggested_action": self.action, "target": self.target})
            if self.light_mode:
                result["light_mode"] = self.light_mode
        return result



def mentioned_targets(text: str) -> set[str]:
    """Find explicit visible-object references in a human or Eli utterance.

    Pronouns are intentionally NOT resolved here. A subsequent pronoun may
    refer to the latest unambiguous object Eli named, but never a guessed prop.
    """
    return {target for target, pattern in TARGETS if re.search(pattern, text, re.I)}

def _classify_clause(text: str, focus: str = "") -> PlayerIntent:
    """Classify one conversational clause, never a whole mixed-context paragraph."""
    lower = text.strip().lower()
    if not lower or NEGATED.search(lower):
        return PlayerIntent()
    if re.match(r"^(?:i (?:think|thought|wonder|was|remember|saw|see|saw|noticed)|"
                r"maybe|perhaps|imagine|suppose|if\b|you (?:said|were|already)|"
                r"it (?:looks|seems)|would it|should we)\b", lower):
        return PlayerIntent()

    # A question about an action is not an instruction to perform that action.
    if QUESTION_PREFIX.search(lower) and not re.match(
            r"^have\s+(?:a\s+)?(?:closer\s+)?look\b", lower):
        return PlayerIntent()

    matches = sorted((m.start(), target) for target, pattern in TARGETS
                     if (m := re.search(pattern, lower)))
    mentioned = [target for _, target in matches]
    if not mentioned and focus and PRONOUN.search(lower):
        mentioned = [focus]
    verb = next((name for name, pattern in VERBS if re.search(pattern, lower)), "")
    if not verb or not mentioned or len(mentioned) != 1:
        return PlayerIntent()

    if lower.endswith("?") and not POLITE_REQUEST.search(lower):
        if not lower.startswith(("please ", "go ", "read ", "inspect ", "take ",
                                 "grab ", "pick ", "turn ", "switch ", "open ",
                                 "check ", "walk ", "head ", "move ", "stand ",
                                 "have a look", "have a closer look")):
            return PlayerIntent()

    target = mentioned[0]
    light_mode = ""
    if target == "flashlight":
        if re.search(r"\b(?:turn|switch)\b.{0,45}\boff\b|"
                     r"\boff\b.{0,15}\b(?:flashlight|torch)\b", lower):
            light_mode = "off"
        elif re.search(r"\b(?:turn|switch)\b.{0,45}\bon\b|"
                       r"\bon\b.{0,15}\b(?:flashlight|torch)\b", lower):
            light_mode = "on"
        if light_mode:
            verb = "use"
    if verb == "enter_code" and target != "keypad":
        return PlayerIntent()
    return PlayerIntent("action", verb, target, light_mode)


# Context often includes an inventory description before an actual instruction.
# Example: "I see a keypad, door, and breaker. Go ahead and pick up the
# flashlight and turn it on." Only the LAST sentence grants permission.
# A comma separating a polite new instruction is another useful boundary.
_COMMAND_SPLIT = re.compile(
    r"(?<=[.!?])\s+|[;\n]+|,\s*(?=(?:please\b|go ahead\b|"
    r"(?:can|could|would|will)\s+you\b|(?:i want|i need)\s+you\s+to\b))",
    re.I,
)


def classify(text: str, focus: str = "") -> PlayerIntent:
    """Return only a clear, currently authorized action.

    Object references from *other* sentences must never make a later clear
    instruction ambiguous. Conversely, two different physical targets in the
    actual instructions aren't silently collapsed to a single action.
    """
    if not isinstance(text, str):
        return PlayerIntent()
    requests: list[PlayerIntent] = []
    current_focus = focus
    for segment in _COMMAND_SPLIT.split(text.strip()):
        intent = _classify_clause(segment, current_focus)
        if intent.kind == "action":
            requests.append(intent)
            current_focus = intent.target
    if not requests:
        return PlayerIntent()
    if len({item.target for item in requests}) != 1:
        return PlayerIntent()
    # Consecutive commands on the SAME prop can be combined when a later use
    # has an explicit desired state (e.g. "Pick up flashlight. Turn it on.").
    if len(requests) > 1:
        if requests[-1].target == "flashlight" and requests[-1].light_mode:
            return requests[-1]
        if all(item.action == requests[0].action for item in requests):
            return requests[-1]
        return PlayerIntent()
    return requests[0]
