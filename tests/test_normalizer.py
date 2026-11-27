#!/usr/bin/env python3
"""Offline tests for coc_client.py JSON normalizer (SPEC §6)."""

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


class TestNormalizer(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_bytes = (FIXTURES_DIR / "player_th16.json").read_bytes()
        self.raw_player = json.loads(self.raw_bytes.decode("utf-8"))
        self.norm = coc_client.normalize_player(self.raw_player)

    def test_maxed_items_stripped(self) -> None:
        hero_names = {h["name"] for h in self.norm["heroes"]}
        self.assertNotIn("Grand Warden", hero_names)

        troop_names = {t["name"] for t in self.norm["troops"]}
        self.assertNotIn("Balloon", troop_names)
        self.assertNotIn("Healer", troop_names)
        self.assertNotIn("Valkyrie", troop_names)

        spell_names = {s["name"] for s in self.norm["spells"]}
        self.assertNotIn("Rage Spell", spell_names)

        pet_names = {p["name"] for p in self.norm["pets"]}
        self.assertNotIn("Unicorn", pet_names)
        self.assertNotIn("L.A.S.S.I", pet_names)

    def test_deficits_equal_max_minus_level(self) -> None:
        for category in ("heroes", "troops", "spells", "pets", "heroEquipment"):
            for item in self.norm.get(category, []):
                self.assertIn("deficit", item)
                self.assertEqual(item["deficit"], item["cap"] - item["lv"])
                self.assertGreater(item["deficit"], 0)
                for eq in item.get("equip", []):
                    self.assertIn("deficit", eq)
                    self.assertEqual(eq["deficit"], eq["cap"] - eq["lv"])
                    self.assertGreater(eq["deficit"], 0)

    def test_village_home_dropped_builder_base_kept(self) -> None:
        for t in self.norm["troops"]:
            if t["name"] == "Raged Barbarian":
                self.assertEqual(t.get("village"), "builderBase")
            else:
                self.assertNotIn("village", t)

    def test_sorted_by_deficit_descending(self) -> None:
        for category in ("heroes", "troops", "spells", "pets"):
            deficits = [item["deficit"] for item in self.norm[category]]
            self.assertEqual(deficits, sorted(deficits, reverse=True))

    def test_output_smaller_than_raw_input(self) -> None:
        compact_str = coc_client.json_dumps(self.norm)
        self.assertLess(len(compact_str.encode("utf-8")), len(self.raw_bytes))

    def test_clan_and_war_normalizers(self) -> None:
        raw_clan = json.loads((FIXTURES_DIR / "clan.json").read_text(encoding="utf-8"))
        norm_clan = coc_client.normalize_clan(raw_clan)
        self.assertEqual(norm_clan["thDistribution"], {"17": 1, "16": 2, "15": 1})

        raw_war = json.loads((FIXTURES_DIR / "war_inprogress.json").read_text(encoding="utf-8"))
        norm_war = coc_client.normalize_war(raw_war)
        self.assertEqual(norm_war["clan"]["missedAttacks"], 6)
        self.assertGreaterEqual(norm_war["clan"]["thMismatchCount"], 1)


if __name__ == "__main__":
    unittest.main()
