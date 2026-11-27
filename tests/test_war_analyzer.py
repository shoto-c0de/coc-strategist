#!/usr/bin/env python3
"""Offline tests for war_analyzer.py (SPEC §7)."""

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
import war_analyzer  # noqa: E402


class TestWarAnalyzer(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_war = json.loads((FIXTURES_DIR / "war_inprogress.json").read_text(encoding="utf-8"))

    def test_zero_attack_member_and_mismatch_in_risk_alerts(self) -> None:
        report = war_analyzer.analyze_war(self.raw_war)
        alerts_text = "\n".join(report["riskAlerts"])
        self.assertIn("WardenPrime", alerts_text)
        self.assertIn("#P0C", alerts_text)
        self.assertIn("0 attacks used", alerts_text)
        self.assertIn("TH mismatch", alerts_text)

    def test_target_assignment_avoids_higher_th_when_equal_or_lower_open(self) -> None:
        # #P0P is TH14; open bases include TH16 (#QPP02, #QPP09), TH15 (#QPP0J, #QPP0P), and TH14 (#QPP0R)
        report = war_analyzer.analyze_war(self.raw_war, attacker_tag="#P0P")
        picks = report["targetAssignments"]
        self.assertGreater(len(picks), 0)
        for pick in picks:
            self.assertLessEqual(pick["defenderTh"], 14)

    def test_works_on_compact_war_board_output(self) -> None:
        compact_war = coc_client.normalize_war(self.raw_war)
        report = war_analyzer.analyze_war(compact_war, attacker_tag="P0G")
        md = war_analyzer.render_markdown(report, include_targets=True)
        self.assertIn("WAR STATUS SUMMARY", md)
        self.assertIn("ROSTER READINESS", md)
        self.assertIn("TARGET ASSIGNMENTS", md)
        self.assertIn("RISK ALERTS", md)
        self.assertIn("WardenPrime", md)
        for pick in report["targetAssignments"]:
            self.assertLessEqual(pick["defenderTh"], 15)


if __name__ == "__main__":
    unittest.main()
