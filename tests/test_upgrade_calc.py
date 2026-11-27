#!/usr/bin/env python3
"""Offline tests for upgrade_calc.py (SPEC §7 & §9)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "skills" / "coc-strategist" / "scripts"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"

sys.path.insert(0, str(SCRIPTS_DIR))
import coc_client  # noqa: E402
import upgrade_calc  # noqa: E402


class TestUpgradeCalc(unittest.TestCase):
    def setUp(self) -> None:
        raw = json.loads((FIXTURES_DIR / "player_th16.json").read_text(encoding="utf-8"))
        self.norm_player = coc_client.normalize_player(raw)

    def test_top_3_lab_and_builder_picks(self) -> None:
        plan = upgrade_calc.analyze_upgrades(self.norm_player, focus="war", builders=6, lab_available=True)
        self.assertEqual(len(plan["topLabUpgrades"]), 3)
        self.assertEqual(len(plan["topBuilderUpgrades"]), 3)
        self.assertTrue(plan["resourceForecast"]["approximate"])
        md = upgrade_calc.render_markdown(plan)
        self.assertIn("TOP 3 LAB UPGRADES", md)
        self.assertIn("TOP 3 BUILDER UPGRADES", md)
        self.assertIn("RESOURCE FORECAST", md)

    def test_maxed_account_yields_empty_sections_without_crash(self) -> None:
        maxed_raw = {
            "tag": "#CGJ0",
            "name": "MaxPlayer",
            "townHallLevel": 17,
            "heroes": [
                {"name": "Barbarian King", "level": 100, "maxLevel": 100, "village": "home", "equipment": []},
                {"name": "Grand Warden", "level": 75, "maxLevel": 75, "village": "home", "equipment": []},
            ],
            "troops": [
                {"name": "Root Rider", "level": 3, "maxLevel": 3, "village": "home"},
            ],
            "spells": [
                {"name": "Overgrowth Spell", "level": 4, "maxLevel": 4, "village": "home"},
            ],
            "pets": [
                {"name": "Spirit Fox", "level": 10, "maxLevel": 10, "village": "home"},
            ],
        }
        norm_maxed = coc_client.normalize_player(maxed_raw)
        plan = upgrade_calc.analyze_upgrades(norm_maxed)
        self.assertEqual(plan["topLabUpgrades"], [])
        self.assertEqual(plan["topBuilderUpgrades"], [])
        self.assertEqual(plan["resourceForecast"]["darkElixirTotal"], 0)
        self.assertEqual(plan["resourceForecast"]["shinyOre"], 0)
        md = upgrade_calc.render_markdown(plan)
        self.assertIn("All tracked lab troops and spells are maxed", md)

    def test_rushed_base_ranks_highest_deficit_meta_troops_first(self) -> None:
        rushed_compact = {
            "tag": "#RUV2",
            "name": "RushedBase",
            "th": 16,
            "heroes": [
                {"name": "Barbarian King", "lv": 45, "cap": 95, "deficit": 50, "equip": []},
                {"name": "Grand Warden", "lv": 40, "cap": 70, "deficit": 30, "equip": []},
                {"name": "Archer Queen", "lv": 70, "cap": 95, "deficit": 25, "equip": []},
            ],
            "troops": [
                {"name": "Root Rider", "lv": 1, "cap": 3, "deficit": 2},
                {"name": "Electro Titan", "lv": 1, "cap": 3, "deficit": 2},
                {"name": "Goblin", "lv": 6, "cap": 9, "deficit": 3},
                {"name": "Wizard", "lv": 10, "cap": 12, "deficit": 2},
            ],
            "spells": [
                {"name": "Overgrowth Spell", "lv": 1, "cap": 4, "deficit": 3},
                {"name": "Bat Spell", "lv": 4, "cap": 6, "deficit": 2},
            ],
            "pets": [],
        }
        plan = upgrade_calc.analyze_upgrades(rushed_compact, focus="war")
        lab_names = [u["name"] for u in plan["topLabUpgrades"]]
        # Overgrowth Spell (3*3=9), Root Rider (3*2=6), Electro Titan (3*2=6) beat off-meta Goblin (1*3=3)
        self.assertEqual(lab_names[0], "Overgrowth Spell")
        self.assertIn("Root Rider", lab_names)
        self.assertIn("Electro Titan", lab_names)
        self.assertNotIn("Goblin", lab_names)

        builder_names = [u["name"] for u in plan["topBuilderUpgrades"]]
        self.assertEqual(builder_names[0], "Barbarian King")


if __name__ == "__main__":
    unittest.main()
