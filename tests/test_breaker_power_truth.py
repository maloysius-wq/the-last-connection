"""Regression: the breaker really restores power and Eli tells the truth.

Observed player failure: Eli says he flipped the switch but nothing happened.
Godot owns power state; the speech bridge must not turn an already-powered
breaker or a mere inspection into a fictional unsuccessful restoration.
"""
import unittest
from ai_bridge.agent import Agent


def power_room(on):
    return {
        "room": "maintenance_chamber",
        "actor_at": "breaker_box",
        "inventory": [],
        "lights_on": on,
        "heard_knocks": on,
        "flashlight_on": False,
        "door_unlocked": False,
        "objects": {
            "breaker_box": {"visible": True, "description":
                ("The breaker lever is up. Power is restored and the overhead lights are on."
                 if on else "The breaker box on the wall; its lever is down.")},
            "maintenance_note": {"visible": on, "description":
                "A folded maintenance note on the desk."},
        },
        "last_observation": "",
    }


class TestBreakerPowerTruth(unittest.TestCase):
    def test_first_use_reports_real_restoration_and_knocks(self):
        spoken = Agent._acknowledge(
            "use", "breaker_box", True, power_room(True),
            "Eli flipped the breaker up. Power was restored, overhead lights switched on, "
            "and a folded note appeared on the desk. Three knocks sounded.")
        self.assertIn("lights just came back", spoken.lower())
        self.assertIn("knocks", spoken.lower())

    def test_second_use_does_not_claim_fresh_power_or_retrigger_knocks(self):
        spoken = Agent._acknowledge(
            "use", "breaker_box", True, power_room(True),
            "Eli checked the breaker again. Its lever is already up, "
            "the overhead lights are on, and power was restored earlier.")
        self.assertIn("already on", spoken.lower())
        self.assertNotIn("just came back", spoken.lower())
        self.assertNotIn("knocks", spoken.lower())
        self.assertIn("note", spoken.lower())

    def test_inspection_before_power_never_pretends_eli_operated_switch(self):
        spoken = Agent._acknowledge(
            "inspect", "breaker_box", True, power_room(False),
            "Eli inspected the breaker. Its lever is down.")
        self.assertIn("haven't flipped it yet", spoken.lower())
        self.assertNotIn("lights just came back", spoken.lower())

    def test_inspection_after_power_reads_world_state(self):
        spoken = Agent._acknowledge(
            "inspect", "breaker_box", True, power_room(True),
            "Eli inspected the breaker. Its lever is up.")
        self.assertIn("lights are on", spoken.lower())
        self.assertNotIn("lever's down", spoken.lower())

    def test_report_never_claims_power_restored_if_flag_is_still_off(self):
        spoken = Agent._acknowledge(
            "use", "breaker_box", True, power_room(False),
            "The breaker moved but the lights still don't work.")
        self.assertIn("still out", spoken.lower())
        self.assertNotIn("lights are back", spoken.lower())


if __name__ == "__main__":
    unittest.main()
