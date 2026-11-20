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

def classify(text: str, focus: str = "") -> PlayerIntent:
    lower = text.strip().lower()
    if not lower or NEGATED.search(lower):
        return PlayerIntent()
    # Describing an idea or past event is not a command to physically act.
    if re.match(r"^(?:i (?:think|thought|wonder|was|remember|saw)|maybe|perhaps|imagine|"
                r"suppose|if\b|you (?:said|were|already)|it (?:looks|seems)|"
                r"would it|should we)\b", lower):
        return PlayerIntent()

    # Questions about what/why/how and requests for verbal explanations never
    # authorize motion just because they mention an object or a verb.
    if QUESTION_PREFIX.search(lower) and not re.match(
            r"^have\s+(?:a\s+)?(?:closer\s+)?look\b", lower):
        return PlayerIntent()

    matches = sorted((m.start(), target)
                     for target, pattern in TARGETS
                     if (m := re.search(pattern, lower)))
    mentioned = [target for _, target in matches]
    if not mentioned and focus and PRONOUN.search(lower):
        mentioned = [focus]

    verb = next((name for name, pattern in VERBS if re.search(pattern, lower)), "")
    if not verb or not mentioned:
        return PlayerIntent()

    # "Can you look at the note?" is a polite action request, but
    # "Can you see the note?" is an information question.
    if lower.endswith("?") and not POLITE_REQUEST.search(lower):
        # Imperatives such as "Please read the note?" remain actionable.
        if not lower.startswith(("please ", "go ", "read ", "inspect ", "take ", "grab ", "pick ", "turn ", "switch ", "open ", "check ", "walk ", "head ", "move ", "stand ")):
            return PlayerIntent()

    # A request covering multiple named objects should be understood by the
    # LLM before action, rather than allowing an unrelated arbitrary target.
    if len(mentioned) > 1:
        return PlayerIntent()

    target = mentioned[0]
    # A "use flashlight" includes grabbing it from the desk if necessary.
    # Likewise "pick up the flashlight and turn it on" is one desired operation.
    light_mode = ""
    if target == "flashlight":
        if re.search(r"\b(?:turn|switch)\b.{0,35}\boff\b|\boff\b.{0,15}\b(?:flashlight|torch)\b", lower):
            light_mode = "off"
        elif re.search(r"\b(?:turn|switch)\b.{0,35}\bon\b|\bon\b.{0,15}\b(?:flashlight|torch)\b", lower):
            light_mode = "on"
        if light_mode:
            verb = "use"
    if target == "keypad" and verb == "enter_code":
        return PlayerIntent("action", verb, target)
    if verb == "enter_code" and target != "keypad":
        return PlayerIntent()
    # "switch on power" is an act, not a request to walk to the panel.
    return PlayerIntent("action", verb, target, light_mode)
