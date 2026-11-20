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


# A physical-action plan is parsed deterministically from the CURRENT player
# message. The local LLM may phrase Eli's response, but it never grants itself
# actions or decides to keep exploring after an authorized sequence ends.
MAX_PLANNED_ACTIONS = 5

_PLAN_PREFIX = re.compile(
    r"^\s*(?:please\s+|go\s+ahead\s+(?:and\s+)?|"
    r"let(?:'s| us)\s+(?:(?:start|begin)\s+by\s+)?"
    r"(?:having\s+you\s+|(?:get\s+you\s+to\s+))|"
    r"(?:i\s+(?:want|need|would\s+like)\s+you\s+to)\s+|"
    r"(?:can|could|would|will)\s+you\s+|"
    r"(?:start|begin)\s+by\s+)+",
    re.I,
)
_PLAN_VERB = (
    r"(?:pick|grab|take|collect|retrieve|turn|switch|flip|toggle|"
    r"look|scan|survey|inspect|examine|check|read|go|walk|head|"
    r"move|approach|stand|open|unlock|use|enter|type|punch)"
)
# Only joiners introducing a SECOND imperative delimit steps; e.g.
# "a keypad and a breaker" is never split.
_PLAN_JOIN = re.compile(r",\s*(?:and\s+)?(?=" + _PLAN_VERB +
                        r"\b)|\s+and\s+(?=" + _PLAN_VERB + r"\b)", re.I)
_PLAN_IMPERATIVE = re.compile(
    r"^(?:" + _PLAN_VERB + r")\b", re.I)
_PLAN_SURVEY = re.compile(
    r"^(?:look\s+around|look\s+over\s+the\s+room|"
    r"scan\s+(?:the\s+)?room|survey\s+(?:the\s+)?room|"
    r"inspect\s+(?:the\s+)?room|check\s+(?:out\s+)?"
    r"(?:the\s+)?(?:whole\s+)?room)\b", re.I)
_PLAN_FLASHLIGHT_LIGHT = re.compile(
    r"^(?:turn|switch)\s+(on|off)\s+(?:(?:the|that|this|your)\s+)?"
    r"(?:light|flashlight|torch|it)\b|"
    r"^(?:turn|switch)\s+(?:(?:the|that|this|your)\s+)?"
    r"(?:flashlight|torch|light|it)\s+(on|off)\b", re.I)


def _plan_step(text: str, focus: str) -> PlayerIntent:
    text = text.strip().rstrip(" .!?")
    if not text or NEGATED.search(text):
        return PlayerIntent()
    if _PLAN_SURVEY.match(text):
        return PlayerIntent("action", "survey", "room")
    # "The light" can mean several fixtures. Only resolve it to the handheld
    # torch after a prior explicit flashlight reference in this same request
    # or a single unambiguous conversational referent.
    light = _PLAN_FLASHLIGHT_LIGHT.match(text)
    if light:
        mode = (light.group(1) or light.group(2)).lower()
        if re.search(r"\b(?:flashlight|torch)\b", text, re.I) or focus == "flashlight":
            return PlayerIntent("action", "use", "flashlight", mode)
        return PlayerIntent()
    result = _classify_clause(text, focus)
    if result.kind == "action":
        # The user must supply actual digits. Never infer a secret code from
        # world observations or the model's earlier conjectures.
        if result.action == "enter_code" and not re.search(r"\b[0-9]{4}\b", text):
            return PlayerIntent()
        return result
    return PlayerIntent()


def plan_actions(text: str, focus: str = "") -> tuple[PlayerIntent, ...]:
    """Recognize a short ordered sequence of independently authorized acts.

    Pure conversation produces (). No LLM-generated action is accepted.
    A multi-target sentence with no imperative stays conversational; a real
    set of explicit instructions executes in spoken order. Do not silently
    choose just one action from a user's compound instruction.
    """
    if not isinstance(text, str) or not text.strip():
        return ()
    commands: list[PlayerIntent] = []
    current_focus = focus
    for sentence in _COMMAND_SPLIT.split(text.strip()):
        statement = sentence.strip()
        if not statement:
            continue
        # Non-command observations may provide ONE explicit antecedent for
        # "that", but cannot themselves authorize a physical action.
        command = _PLAN_PREFIX.sub("", statement, count=1).strip()
        is_directive = bool(_PLAN_IMPERATIVE.match(command) or _PLAN_SURVEY.match(command))
        if not is_directive:
            mentions = mentioned_targets(statement)
            if len(mentions) == 1:
                current_focus = next(iter(mentions))
            elif len(mentions) > 1:
                current_focus = ""
            continue
        parts = _PLAN_JOIN.split(command)
        for part in parts:
            part = _PLAN_PREFIX.sub("", part.strip(), count=1).strip()
            result = _plan_step(part, current_focus)
            if result.kind != "action":
                # A compound instruction containing an unsupported/ambiguous
                # step must not quietly execute a partial interpretation.
                return ()
            commands.append(result)
            if len(commands) > MAX_PLANNED_ACTIONS:
                return ()
            if result.target != "room":
                current_focus = result.target
    return tuple(commands)
