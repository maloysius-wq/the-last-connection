"""Natural emotional agency and persistent relationship state.

Regression scenarios are based on the Nov 23 exported Eli conversation in which
the user repeatedly teased him, denied having a task and refused to describe
the monitor. The model decides meaning and emotional appraisal in ONE pass;
these tests verify that the engine persists and honors those choices, rather
than doing phrase-specific sentiment parsing of the user's words.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_bridge.agent import Agent, EMOTION_SET, SessionStore
from ai_bridge.goals import GOAL_SCHEMA
from test_semantic_planner import world

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"


def appraisal(*, trust=0, stress=0, anger=0, willingness="consider",
              purpose="unchanged", boundary=""):
    return {"trust": trust, "stress": stress, "anger": anger,
            "willingness": willingness, "claimed_purpose": purpose,
            "boundary_update": boundary}


def plan(speech, *, kind="conversation", goals=None, emotion="cautious",
         social=None):
    return {"kind": kind, "goals": goals if goals is not None else [],
            "speech": speech, "emotion": emotion,
            "appraisal": social or appraisal()}


def goal(action, target, argument=""):
    return {"action": action, "target": target, "argument": argument}


class Model:
    def __init__(self, *responses, reaction="I did it. That was frightening."):
        self.responses = list(responses)
        self.reaction = reaction
        self.requests = []
        self.reactions = []

    def plan_goals(self, messages):
        self.requests.append(messages)
        if not self.responses:
            raise AssertionError("Unexpected second GGUF action call")
        return self.responses.pop(0)

    def converse(self, messages):
        self.reactions.append(messages)
        return self.reaction


class EmotionalAgency(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = SessionStore(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def make(self, *responses, reaction="I did it. That was frightening."):
        model = Model(*responses, reaction=reaction)
        return Agent(model, self.store, PERSONA), model

    def test_wakes_recently_without_assuming_a_mission_or_camera(self):
        agent, model = self.make(plan(
            "Who are you? I just woke up here. What the hell is going on?",
            emotion="anxious", social=appraisal(stress=1)))
        decision = agent.decide("first", "Aye whaddup bitch", world())
        self.assertEqual(decision.actions, ())
        self.assertEqual(decision.emotion, "anxious")
        self.assertIn("just woke up", decision.speech)
        system = model.requests[0][0]["content"]
        self.assertIn("woke up", system)
        self.assertIn('"speaker_identity_known":false', system)
        self.assertIn('"speaker_can_see_you":"unknown', system)
        self.assertIn('"claimed_purpose":"unknown"', system)
        self.assertNotIn("frightened and distrustful of the unknown remote voice", system)
        state = self.store.load("first")["relationship"]
        self.assertEqual(state["trust"], -40)
        self.assertEqual(state["stress"], 81)
        self.assertEqual(state["anger"], 24)
        self.assertEqual(state["turns"], 1)

    def test_actual_anger_builds_from_repeated_taunting_without_fake_actions(self):
        model_replies = [
            plan("Don't call me that. I don't know you.", emotion="angry",
                 social=appraisal(trust=-2, stress=1, anger=2)),
            plan("This isn't funny to me.", emotion="frustrated",
                 social=appraisal(trust=-2, stress=1, anger=2)),
            plan("You're really enjoying this, aren't you?", emotion="angry",
                 social=appraisal(trust=-2, stress=1, anger=2)),
            plan("I don't owe you a performance.", emotion="angry",
                 social=appraisal(trust=-2, anger=2)),
        ]
        agent, model = self.make(*model_replies)
        for words in ("Aye whaddup bitch", "Nothing dickhead",
                      "Wow, you mad bro?", "I want you to get angry and talk back to me"):
            answer = agent.decide("taunted", words, world())
            self.assertEqual(answer.actions, ())
            self.assertIn(answer.emotion, ("angry", "frustrated"))
        r = self.store.load("taunted")["relationship"]
        self.assertEqual(r["turns"], 4)
        self.assertEqual(r["trust"], -80)
        self.assertEqual(r["anger"], 96)
        self.assertEqual(r["stress"], 95)
        self.assertEqual(len(model.requests), 4)
        self.assertIn("deeply angry", model.requests[-1][0]["content"] if False
                      else agent._relationship_stance(r))

    def test_speaker_only_wants_conversation_and_boundary_is_remembered(self):
        agent, model = self.make(
            plan("We can just talk. I'm not about to hand you a checklist.",
                 social=appraisal(purpose="just_talking", trust=1)),
            plan("Fine. I won't ask about the monitor again.",
                 social=appraisal(trust=-1, anger=1,
                                  boundary="Refuses to describe the monitor")),
            plan("No, I understand. No tasks. We can talk or not.",
                 social=appraisal(boundary="Does not want to give room instructions")),
            plan("You sound like you enjoy getting under my skin.",
                 emotion="frustrated", social=appraisal(anger=1)),
        )
        for text in (
            "I'm just talking to you man, just trying to have a conversation.",
            "I will never tell you what I see on this monitor.",
            "I don't want you to do anything in the room.",
            "Well wouldn't you like to know",
        ):
            agent.decide("chat_only", text, world())
        r = self.store.load("chat_only")["relationship"]
        self.assertEqual(r["claimed_purpose"], "just_talking")
        self.assertEqual(len(r["boundaries"]), 2)
        self.assertIn("Refuses to describe the monitor", r["boundaries"])
        latest_system = model.requests[-1][0]["content"]
        self.assertIn('"claimed_purpose":"just_talking"', latest_system)
        self.assertIn("Does not want to give room instructions", latest_system)
        self.assertEqual(len(model.requests), 4)

    def test_late_chat_retains_boundaries_when_early_history_truncated(self):
        responses = [
            plan("I'm listening.", social=appraisal(
                purpose="just_talking", boundary="Do not ask about the monitor")),
        ] + [plan("All right. Keep talking.") for _ in range(14)]
        agent, model = self.make(*responses)
        agent.decide("long", "I will never tell you what I see on the monitor.", world())
        for i in range(14):
            agent.decide("long", f"Let's keep talking about something else {i}.", world())
        state = self.store.load("long")
        self.assertEqual(state["relationship"]["turns"], 15)
        self.assertIn("Do not ask about the monitor", model.requests[-1][0]["content"])
        self.assertIn('"claimed_purpose":"just_talking"', model.requests[-1][0]["content"])

    def test_trust_recovers_gradually_not_on_one_polite_turn(self):
        agent, model = self.make(
            plan("That's cruel.", social=appraisal(trust=-2, anger=2)),
            plan("I hear you.", social=appraisal(trust=2, stress=-1, anger=-1)),
            plan("I appreciate you staying.", social=appraisal(trust=2, stress=-1, anger=-1)),
        )
        agent.decide("repair", "You're trapped and it's hilarious.", world())
        hurt = self.store.load("repair")["relationship"]["trust"]
        agent.decide("repair", "I shouldn't have said that. I'm sorry.", world())
        after_apology = self.store.load("repair")["relationship"]["trust"]
        agent.decide("repair", "I meant it. I'll respect your boundaries.", world())
        more = self.store.load("repair")["relationship"]["trust"]
        self.assertEqual((hurt, after_apology, more), (-50, -40, -30))
        self.assertLess(more, 0)

    def test_low_trust_can_refuse_without_starting_an_action(self):
        step = goal("use", "breaker_box")
        agent, model = self.make(plan(
            "Who are you to order me around? I'm not touching that yet.",
            kind="action", goals=[step], emotion="suspicious",
            social=appraisal(willingness="decline", trust=-1, anger=1)))
        response = agent.decide("refusal", "Flip that breaker right now.", world())
        self.assertEqual(response.actions, ())
        self.assertEqual(response.action, "wait")
        self.assertIn("not touching", response.speech)
        self.assertEqual(response.status, "")
        self.assertEqual(len(model.requests), 1)

    def test_low_trust_can_consider_without_falsely_promising_action(self):
        agent, _ = self.make(plan(
            "Maybe, but I need to understand why you want that.",
            kind="action", goals=[goal("inspect", "exit_door")],
            social=appraisal(willingness="consider", stress=1)))
        decision = agent.decide("hesitate", "Check the door for me.", world())
        self.assertFalse(decision.actions)
        self.assertIn("why", decision.speech)

    def test_low_trust_can_choose_obvious_self_protection_without_forced_wait(self):
        agent, _ = self.make(plan(
            "Fine, I'll get some light. I need to see where I am.",
            kind="action", goals=[goal("use", "flashlight", "on")],
            emotion="afraid", social=appraisal(
                willingness="accept", stress=-1)))
        decision = agent.decide("survival", "Turn that flashlight on.", world())
        self.assertEqual(decision.actions, (goal("use", "flashlight", "on"),))
        self.assertEqual(self.store.load("survival")["relationship"]["trust"], -40)

    def test_environment_changes_stress_but_do_not_magically_grant_friendship(self):
        agent, model = self.make(plan(
            "I'll try that.", kind="action", goals=[goal("use", "breaker_box")],
            social=appraisal(willingness="accept")))
        room = world()
        agent.decide("power", "Try restoring the lights.", room)
        after = dict(room)
        after.update({"lights_on": True, "heard_knocks": True})
        agent.outcome("power", "use", "breaker_box", True,
                      "Eli restored the power. Three knocks sounded behind the door.",
                      after)
        r = self.store.load("power")["relationship"]
        self.assertEqual(r["trust"], -40)
        self.assertEqual(r["stress"], 79)  # power -8, knocks +13
        self.assertEqual(len(model.reactions), 1)
        diag = self.store.trace_path("power").read_text(encoding="utf-8")
        self.assertIn("verified_environmental_effect", diag)

    def test_no_fake_knocks_before_engine_hears_them(self):
        agent, _ = self.make()
        room = world()
        speech = agent._ground_dialogue(
            "I just heard a knock behind the door. I don't like this.",
            room, {"history": [], "facts": []}, "What's happening?",
            allow_fallback=False)
        self.assertNotIn("heard a knock", speech)
        self.assertIn("I don't like this.", speech)

    def test_schema_remains_one_pass_and_supports_new_emotions(self):
        self.assertIn("appraisal", GOAL_SCHEMA["required"])
        spec = GOAL_SCHEMA["properties"]["appraisal"]
        self.assertEqual(spec["properties"]["willingness"]["enum"],
                         ["accept", "consider", "decline"])
        self.assertIn("angry", EMOTION_SET)
        self.assertIn("anxious", EMOTION_SET)
        self.assertIn("overwhelmed", EMOTION_SET)

    def test_old_saved_sessions_upgrade_without_resetting_their_history(self):
        self.store.save("old", {"history": [
            {"role": "user", "content": "You seem frightened."}],
            "facts": [{"action": "inspect", "target": "desk",
                       "success": True, "description": "Eli looked at the desk."}]})
        agent, model = self.make(plan("I am frightened, yes."))
        response = agent.decide("old", "Are you okay?", world())
        self.assertIn("frightened", response.speech)
        self.assertEqual(self.store.load("old")["relationship"]["turns"], 1)
        self.assertIn("You seem frightened", model.requests[0][1]["content"])


if __name__ == "__main__":
    unittest.main()
