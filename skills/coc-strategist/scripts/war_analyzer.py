#!/usr/bin/env python3
"""Deterministic war board analyzer for status, readiness, target picks, and risk alerts."""

from __future__ import annotations

import json as _stdlib_json
import re
import sys
from datetime import datetime, timezone
from typing import Any

# Global Rule 1: orjson with stdlib json fallback
try:
    import orjson  # type: ignore
except ImportError:  # pragma: no cover - fallback path
    orjson = None  # type: ignore

# SPEC §7: verbatim help output
HELP_TEXT = """Usage: war_analyzer.py [options]

Reads compact war board JSON from stdin (output of coc_client.py war).

Options:
  --attacker-tag TAG    Your player tag (for personalized target picks)
  --format table|json|markdown
  --help

Output:
  1. WAR STATUS SUMMARY    (stars, remaining attacks, time left)
  2. ROSTER READINESS       (per-TH band: avg hero level, maxed %, mismatch count)
  3. TARGET ASSIGNMENTS     (if --attacker-tag: your top 3 target picks with reasoning)
  4. RISK ALERTS            (missed attacks, low-TH-vs-high-TH mismatches)"""

TAG_REGEX = re.compile(r"^#[0289CGJLPQRUVY]{3,12}$")


def json_loads(raw: str) -> Any:
    if orjson is not None:
        return orjson.loads(raw)
    return _stdlib_json.loads(raw)


def json_dumps(obj: Any, pretty: bool = True) -> str:
    if orjson is not None:
        opts = orjson.OPT_INDENT_2 if pretty else 0
        return orjson.dumps(obj, option=opts).decode("utf-8")
    return _stdlib_json.dumps(obj, indent=2 if pretty else None, ensure_ascii=False)


def normalize_tag(raw_tag: str) -> str:
    tag = raw_tag.strip().upper()
    if not tag.startswith("#"):
        tag = "#" + tag
    if not TAG_REGEX.match(tag):
        raise ValueError(f"Invalid tag format '{raw_tag}'.")
    return tag


def _parse_coc_time(ts: str) -> datetime | None:
    if not ts:
        return None
    for fmt in ("%Y%m%dT%H%M%S.%fZ", "%Y%m%dT%H%M%SZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _format_time_left(end_ts: str, state: str) -> str:
    if state == "warEnded":
        return "0h 0m (war ended)"
    if state == "notInWar":
        return "N/A (not in war)"
    dt = _parse_coc_time(end_ts)
    if dt is None:
        return end_ts or "unknown"
    delta = dt - datetime.now(timezone.utc)
    secs = int(delta.total_seconds())
    if secs <= 0:
        return f"Ended ({end_ts})"
    hours, rem = divmod(secs, 3600)
    mins = rem // 60
    return f"{hours}h {mins}m"


# Accept both compact coc_client.py war JSON and raw /currentwar JSON
def _unify_war_data(raw: dict[str, Any]) -> dict[str, Any]:
    state = raw.get("state", "unknown")
    team_size = int(raw.get("teamSize", 0) or 0)
    attacks_per_member = int(raw.get("attacksPerMember", 2) or 2)
    raw_clan = raw.get("clan") or {}
    raw_opp = raw.get("opponent") or {}

    opp_members: list[dict[str, Any]] = []
    opp_by_tag: dict[str, dict[str, Any]] = {}
    for om in raw_opp.get("members") or []:
        best = om.get("bestOpponentAttack") or {}
        best_stars = om.get("bestStars")
        if best_stars is None:
            best_stars = best.get("stars", 0)
        best_dest = om.get("bestDestruction")
        if best_dest is None:
            best_dest = best.get("destructionPercentage", 0.0)
        entry = {
            "tag": str(om.get("tag", "")),
            "name": str(om.get("name", "")),
            "th": int(om.get("th", om.get("townHallLevel", 0)) or 0),
            "mapPosition": int(om.get("mapPosition", 0) or 0),
            "bestStars": int(best_stars or 0),
            "bestDestruction": float(best_dest or 0.0),
        }
        opp_members.append(entry)
        opp_by_tag[entry["tag"]] = entry
    opp_members.sort(key=lambda x: x["mapPosition"])

    clan_members: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    for cm in raw_clan.get("members") or []:
        cth = int(cm.get("th", cm.get("townHallLevel", 0)) or 0)
        if "attacksUsed" in cm:
            used = int(cm.get("attacksUsed", 0) or 0)
            remaining = int(cm.get("attacksRemaining", max(0, attacks_per_member - used)) or 0)
            stars_earned = int(cm.get("starsEarned", 0) or 0)
            member_mismatches = int(cm.get("mismatchCount", 0) or 0)
        else:
            attacks = cm.get("attacks") or []
            used = len(attacks)
            remaining = max(0, attacks_per_member - used)
            stars_earned = sum(int(a.get("stars", 0) or 0) for a in attacks)
            member_mismatches = 0
            for atk in attacks:
                dtag = atk.get("defenderTag", "")
                defender = opp_by_tag.get(dtag)
                if defender and cth < defender["th"]:
                    member_mismatches += 1
                    mismatches.append({
                        "attackerTag": cm.get("tag", ""),
                        "attackerName": cm.get("name", ""),
                        "attackerTh": cth,
                        "defenderTag": dtag,
                        "defenderName": defender["name"],
                        "defenderTh": defender["th"],
                        "stars": int(atk.get("stars", 0) or 0),
                    })

        hero_avg = cm.get("heroLevelAvg")
        if hero_avg is None and isinstance(cm.get("heroes"), list) and cm["heroes"]:
            hero_vals = [int(h.get("level", h.get("lv", 0)) or 0) for h in cm["heroes"]]
            hero_avg = round(sum(hero_vals) / len(hero_vals), 1)

        hero_max_pct = cm.get("maxedPct")
        if hero_max_pct is None and isinstance(cm.get("heroes"), list) and cm["heroes"]:
            maxed_cnt = sum(
                1 for h in cm["heroes"]
                if int(h.get("level", h.get("lv", 0)) or 0) >= int(h.get("maxLevel", h.get("cap", 1)) or 1)
            )
            hero_max_pct = round(100.0 * maxed_cnt / len(cm["heroes"]), 1)

        clan_members.append({
            "tag": str(cm.get("tag", "")),
            "name": str(cm.get("name", "")),
            "th": cth,
            "mapPosition": int(cm.get("mapPosition", 0) or 0),
            "attacksUsed": used,
            "attacksRemaining": remaining,
            "starsEarned": stars_earned,
            "mismatchCount": member_mismatches,
            "heroLevelAvg": hero_avg,
            "maxedPct": hero_max_pct,
        })
    clan_members.sort(key=lambda x: x["mapPosition"])

    return {
        "state": state,
        "teamSize": team_size or len(clan_members),
        "attacksPerMember": attacks_per_member,
        "endTime": raw.get("endTime", ""),
        "clan": {
            "tag": str(raw_clan.get("tag", "")),
            "name": str(raw_clan.get("name", "Our Clan")),
            "stars": int(raw_clan.get("stars", 0) or 0),
            "destructionPercentage": float(raw_clan.get("destructionPercentage", 0.0) or 0.0),
            "attacks": int(raw_clan.get("attacks", sum(m["attacksUsed"] for m in clan_members)) or 0),
            "members": clan_members,
        },
        "opponent": {
            "tag": str(raw_opp.get("tag", "")),
            "name": str(raw_opp.get("name", "Opponent")),
            "stars": int(raw_opp.get("stars", 0) or 0),
            "destructionPercentage": float(raw_opp.get("destructionPercentage", 0.0) or 0.0),
            "attacks": int(raw_opp.get("attacks", 0) or 0),
            "members": opp_members,
        },
        "recordedMismatches": mismatches,
    }


def analyze_war(raw: dict[str, Any], attacker_tag: str | None = None) -> dict[str, Any]:
    war = _unify_war_data(raw)
    clan = war["clan"]
    opp = war["opponent"]
    team_size = war["teamSize"]
    apm = war["attacksPerMember"]

    total_possible = team_size * apm
    clan_used = sum(m["attacksUsed"] for m in clan["members"])
    clan_remaining = max(0, total_possible - clan_used)
    opp_remaining = max(0, total_possible - opp["attacks"])

    summary = {
        "state": war["state"],
        "teamSize": team_size,
        "clanName": clan["name"],
        "clanStars": clan["stars"],
        "clanDestruction": clan["destructionPercentage"],
        "clanRemainingAttacks": clan_remaining,
        "opponentName": opp["name"],
        "opponentStars": opp["stars"],
        "opponentDestruction": opp["destructionPercentage"],
        "opponentRemainingAttacks": opp_remaining,
        "timeLeft": _format_time_left(war["endTime"], war["state"]),
    }

    # 2. ROSTER READINESS per-TH band
    bands: dict[int, list[dict[str, Any]]] = {}
    for m in clan["members"]:
        bands.setdefault(m["th"], []).append(m)

    readiness: list[dict[str, Any]] = []
    for th in sorted(bands.keys(), reverse=True):
        group = bands[th]
        hero_avgs = [m["heroLevelAvg"] for m in group if m["heroLevelAvg"] is not None]
        max_pcts = [m["maxedPct"] for m in group if m["maxedPct"] is not None]
        # When hero levels are absent from /currentwar, fall back to 3-star hit readiness %
        if not max_pcts:
            total_used = sum(m["attacksUsed"] for m in group)
            total_stars = sum(m["starsEarned"] for m in group)
            hit_pct = round(100.0 * total_stars / (total_used * 3), 1) if total_used else 0.0
            max_pct_val: float | str = hit_pct
        else:
            max_pct_val = round(sum(max_pcts) / len(max_pcts), 1)

        readiness.append({
            "th": th,
            "members": len(group),
            "avgHeroLevel": round(sum(hero_avgs) / len(hero_avgs), 1) if hero_avgs else None,
            "maxedPct": max_pct_val,
            "mismatchCount": sum(m["mismatchCount"] for m in group),
        })

    # 3. TARGET ASSIGNMENTS (when --attacker-tag provided)
    target_assignments: list[dict[str, Any]] = []
    attacker_info: dict[str, Any] | None = None
    if attacker_tag:
        norm_atk = normalize_tag(attacker_tag)
        attacker = next((m for m in clan["members"] if m["tag"].upper() == norm_atk), None)
        if attacker is not None:
            attacker_info = attacker
            atk_th = attacker["th"]
            open_targets = [om for om in opp["members"] if om["bestStars"] < 3]
            pool = open_targets if open_targets else list(opp["members"])

            # SPEC TASK 5 & TASK 11: prefer attacker TH >= defender TH; never pick higher TH if equal/lower open
            eligible = [om for om in pool if atk_th >= om["th"]]
            chosen_pool = eligible if eligible else pool

            def _target_sort_key(om: dict[str, Any]) -> tuple[int, int, int, int]:
                higher_penalty = 1 if om["th"] > atk_th else 0
                th_gap = abs(atk_th - om["th"])
                remaining_stars = max(0, 3 - om["bestStars"])
                return (higher_penalty, th_gap, remaining_stars, om["mapPosition"])

            chosen_pool.sort(key=_target_sort_key)
            for om in chosen_pool[:3]:
                rem_stars = max(0, 3 - om["bestStars"])
                if om["th"] == atk_th:
                    band_note = f"mirror-band TH{om['th']}"
                elif om["th"] < atk_th:
                    band_note = f"TH{atk_th}→TH{om['th']} dip"
                else:
                    band_note = f"reach up vs TH{om['th']} (no equal/lower open)"
                reason = (
                    f"#{om['mapPosition']} {om['name']}: {band_note}, "
                    f"{om['bestStars']}/3★ ({rem_stars} remaining star{'s' if rem_stars != 1 else ''} open)"
                )
                target_assignments.append({
                    "defenderTag": om["tag"],
                    "defenderName": om["name"],
                    "defenderTh": om["th"],
                    "mapPosition": om["mapPosition"],
                    "bestStars": om["bestStars"],
                    "remainingStars": rem_stars,
                    "reasoning": reason,
                })

    # 4. RISK ALERTS
    zero_attack_members = [m for m in clan["members"] if m["attacksUsed"] == 0]
    partial_members = [m for m in clan["members"] if 0 < m["attacksUsed"] < apm]
    mismatch_members = [m for m in clan["members"] if m["mismatchCount"] > 0]

    alerts: list[str] = []
    for m in zero_attack_members:
        alerts.append(
            f"0 attacks used: #{m['mapPosition']} {m['name']} ({m['tag']}, TH{m['th']}) has {m['attacksRemaining']} attacks remaining."
        )
    for m in partial_members:
        alerts.append(
            f"Unused attack: #{m['mapPosition']} {m['name']} ({m['tag']}, TH{m['th']}) has {m['attacksRemaining']} attack remaining."
        )
    for mm in war["recordedMismatches"]:
        alerts.append(
            f"TH mismatch: TH{mm['attackerTh']} {mm['attackerName']} ({mm['attackerTag']}) "
            f"hit TH{mm['defenderTh']} {mm['defenderName']} ({mm['stars']}★)."
        )
    if not war["recordedMismatches"]:
        for m in mismatch_members:
            alerts.append(
                f"TH mismatch: {m['name']} ({m['tag']}, TH{m['th']}) recorded {m['mismatchCount']} upward-TH attack(s)."
            )

    return {
        "warStatusSummary": summary,
        "rosterReadiness": readiness,
        "attacker": attacker_info,
        "targetAssignments": target_assignments,
        "riskAlerts": alerts,
    }


def render_markdown(report: dict[str, Any], include_targets: bool) -> str:
    s = report["warStatusSummary"]
    lines = [
        f"## ⚔️ War Analysis — {s['clanName']} vs {s['opponentName']}",
        "",
        "### 1. WAR STATUS SUMMARY",
        f"- **State:** `{s['state']}` ({s['teamSize']}v{s['teamSize']})",
        f"- **Score:** {s['clanStars']}★ ({s['clanDestruction']:.1f}%) vs {s['opponentStars']}★ ({s['opponentDestruction']:.1f}%)",
        f"- **Remaining Attacks:** {s['clanRemainingAttacks']} (Us) vs {s['opponentRemainingAttacks']} (Opponent)",
        f"- **Time Left:** {s['timeLeft']}",
        "",
        "### 2. ROSTER READINESS",
        "| TH Band | Members | Avg Hero Lv | Maxed / Hit % | Mismatches |",
        "|---------|---------|-------------|---------------|------------|",
    ]
    for row in report["rosterReadiness"]:
        hero_str = f"{row['avgHeroLevel']}" if row["avgHeroLevel"] is not None else "N/A"
        lines.append(
            f"| TH{row['th']} | {row['members']} | {hero_str} | {row['maxedPct']}% | {row['mismatchCount']} |"
        )

    if include_targets:
        lines.extend(["", "### 3. TARGET ASSIGNMENTS"])
        if report["attacker"] is None:
            lines.append("Attacker tag was not found on this war roster.")
        elif not report["targetAssignments"]:
            lines.append("No target candidates available.")
        else:
            atk = report["attacker"]
            lines.append(f"Top picks for **{atk['name']}** (`{atk['tag']}`, TH{atk['th']}):")
            for idx, t in enumerate(report["targetAssignments"], start=1):
                lines.append(f"{idx}. **{t['defenderName']}** (`{t['defenderTag']}`, TH{t['defenderTh']}) — {t['reasoning']}")

    lines.extend(["", "### 4. RISK ALERTS"])
    if not report["riskAlerts"]:
        lines.append("- No missed attacks or upward-TH mismatches detected.")
    else:
        for alert in report["riskAlerts"]:
            lines.append(f"- ⚠️ {alert}")
    return "\n".join(lines)


def render_table(report: dict[str, Any], include_targets: bool) -> str:
    s = report["warStatusSummary"]
    lines = [
        f"WAR ANALYSIS — {s['clanName']} vs {s['opponentName']}",
        "",
        "1. WAR STATUS SUMMARY",
        f"  State    : {s['state']} ({s['teamSize']}v{s['teamSize']})",
        f"  Score    : {s['clanStars']}* ({s['clanDestruction']:.1f}%) vs {s['opponentStars']}* ({s['opponentDestruction']:.1f}%)",
        f"  Remaining: {s['clanRemainingAttacks']} (Us) / {s['opponentRemainingAttacks']} (Opp)",
        f"  Time Left: {s['timeLeft']}",
        "",
        "2. ROSTER READINESS",
        f"  {'TH':<5} {'Count':<6} {'AvgHero':<9} {'Max/Hit%':<10} {'Mismatches'}",
    ]
    for row in report["rosterReadiness"]:
        hero_str = f"{row['avgHeroLevel']}" if row["avgHeroLevel"] is not None else "N/A"
        lines.append(f"  TH{row['th']:<3} {row['members']:<6} {hero_str:<9} {str(row['maxedPct'])+'%':<10} {row['mismatchCount']}")

    if include_targets:
        lines.extend(["", "3. TARGET ASSIGNMENTS"])
        if not report["targetAssignments"]:
            lines.append("  (none)")
        else:
            for idx, t in enumerate(report["targetAssignments"], start=1):
                lines.append(f"  {idx}. {t['reasoning']}")

    lines.extend(["", "4. RISK ALERTS"])
    if not report["riskAlerts"]:
        lines.append("  (none)")
    else:
        for alert in report["riskAlerts"]:
            lines.append(f"  - {alert}")
    return "\n".join(lines)


def _parse_args(argv: list[str]) -> dict[str, Any]:
    attacker_tag: str | None = None
    fmt = "markdown"

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--help", "-h"):
            print(HELP_TEXT)
            sys.exit(0)
        elif arg == "--attacker-tag":
            i += 1
            if i >= len(argv):
                raise ValueError("--attacker-tag requires a value.")
            attacker_tag = argv[i]
        elif arg.startswith("--attacker-tag="):
            attacker_tag = arg.split("=", 1)[1]
        elif arg == "--format":
            i += 1
            if i >= len(argv):
                raise ValueError("--format requires table|json|markdown.")
            fmt = argv[i]
        elif arg.startswith("--format="):
            fmt = arg.split("=", 1)[1]
        else:
            raise ValueError(f"Unknown argument: {arg}")
        i += 1

    if fmt not in ("table", "json", "markdown"):
        raise ValueError(f"Invalid --format '{fmt}'. Choose table|json|markdown.")
    if attacker_tag is not None:
        attacker_tag = normalize_tag(attacker_tag)

    return {"attacker_tag": attacker_tag, "format": fmt}


def main(argv: list[str] | None = None) -> int:
    try:
        opts = _parse_args(sys.argv[1:] if argv is None else argv)
    except ValueError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1

    raw_stdin = sys.stdin.read().strip()
    if not raw_stdin:
        sys.stderr.write("Error: Expected war JSON on stdin.\n")
        return 1

    try:
        data = json_loads(raw_stdin)
    except Exception as exc:
        sys.stderr.write(f"Error: Invalid JSON on stdin: {exc}\n")
        return 1

    report = analyze_war(data, attacker_tag=opts["attacker_tag"])
    include_targets = opts["attacker_tag"] is not None

    if opts["format"] == "json":
        print(json_dumps(report))
    elif opts["format"] == "table":
        print(render_table(report, include_targets))
    else:
        print(render_markdown(report, include_targets))
    return 0


if __name__ == "__main__":
    sys.exit(main())
