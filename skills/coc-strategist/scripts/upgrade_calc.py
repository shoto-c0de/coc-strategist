#!/usr/bin/env python3
"""Deterministic upgrade priority calculator for Lab, Builder/Hero/Equipment/Pet queues."""

from __future__ import annotations

import json as _stdlib_json
import sys
from typing import Any

# Global Rule 1: orjson with stdlib json fallback
try:
    import orjson  # type: ignore
except ImportError:  # pragma: no cover - fallback path
    orjson = None  # type: ignore

# SPEC §7: verbatim help output
HELP_TEXT = """Usage: upgrade_calc.py [options]

Reads compact tactical JSON from stdin (output of coc_client.py player).

Options:
  --focus war|cwl|rush-fix|farm   Strategy focus (default: war)
  --builders N                     Available builder count (default: 6)
  --lab-available                  Whether lab is free (default: true)
  --format table|json|markdown     Output format (default: markdown)
  --help                           Show this help

Output: Ranked upgrade plan with 3 sections:
  1. TOP 3 LAB UPGRADES     (troop/spell by war-impact × deficit)
  2. TOP 3 BUILDER UPGRADES (hero/equipment/pet by war-impact × deficit)
  3. RESOURCE FORECAST       (dark elixir, shiny ore, starry ore estimates)"""

# SPEC §9: Static per-TH meta weight table derived from TH9-TH17 war meta
# Core Army / primary meta items = 3.0, support troops/spells/pets = 2.0, everything else = 1.0
TH_META_WEIGHTS: dict[int, dict[str, set[str]]] = {
    17: {
        "core": {
            "Root Rider", "Electro Titan", "Healer",
            "Rage Spell", "Heal Spell", "Freeze Spell", "Overgrowth Spell",
            "Barbarian King", "Archer Queen", "Grand Warden", "Royal Champion",
            "Giant Gauntlet", "Rage Vial", "Giant Arrow", "Healer Puppet",
            "Eternal Tome", "Haste Vial", "Seeking Shield",
            "Spirit Fox", "Phoenix",
        },
        "support": {
            "Wizard", "Baby Dragon", "Balloon", "Valkyrie", "Druid", "Thrower",
            "Super Wall Breaker", "Wall Breaker", "Minion Prince",
            "Electro Boots", "Magic Mirror", "Spiky Ball", "Healing Tome",
            "Poison Spell", "Diggy", "Frosty", "Angry Jelly", "Unicorn",
        },
    },
    16: {
        "core": {
            "Root Rider", "Thrower", "Electro Titan", "Healer",
            "Rage Spell", "Heal Spell", "Freeze Spell", "Overgrowth Spell",
            "Barbarian King", "Archer Queen", "Grand Warden", "Royal Champion",
            "Giant Gauntlet", "Rage Vial", "Giant Arrow", "Healer Puppet",
            "Eternal Tome", "Haste Vial", "Seeking Shield",
            "Spirit Fox", "Phoenix",
        },
        "support": {
            "Wizard", "Baby Dragon", "Balloon", "Valkyrie", "Druid",
            "Super Wall Breaker", "Wall Breaker", "Poison Spell",
            "Electro Boots", "Magic Mirror", "Spiky Ball", "Healing Tome",
            "Diggy", "Frosty", "Unicorn",
        },
    },
    15: {
        "core": {
            "Super Witch", "Witch", "Balloon", "Lava Hound", "Healer",
            "Bat Spell", "Freeze Spell", "Rage Spell", "Clone Spell",
            "Grand Warden", "Archer Queen", "Eternal Tome", "Giant Arrow",
            "Barbarian King", "Royal Champion", "Diggy", "Phoenix",
        },
        "support": {
            "Super Wizard", "Wizard", "Ice Golem", "Headhunter",
            "Invisibility Spell", "Haste Spell", "Poison Spell",
            "Giant Gauntlet", "Rage Vial", "Healer Puppet", "Haste Vial",
            "Frosty", "Unicorn",
        },
    },
    14: {
        "core": {
            "Electro Dragon", "Balloon", "Hog Rider", "Miner", "Healer",
            "Rage Spell", "Freeze Spell", "Lightning Spell",
            "Grand Warden", "Archer Queen", "Eternal Tome", "Unicorn",
        },
        "support": {
            "Baby Dragon", "Wizard", "Heal Spell", "Poison Spell",
            "Barbarian King", "Royal Champion", "Giant Arrow", "Rage Vial",
            "Mighty Yak", "Electro Owl", "L.A.S.S.I",
        },
    },
    13: {
        "core": {
            "Yeti", "Bowler", "Balloon", "Lava Hound", "Healer",
            "Rage Spell", "Heal Spell", "Freeze Spell", "Haste Spell",
            "Archer Queen", "Grand Warden", "Royal Champion", "Barbarian King",
        },
        "support": {
            "Wizard", "Witch", "Super Wall Breaker", "Wall Breaker",
            "Poison Spell", "Minion", "Headhunter",
        },
    },
    12: {
        "core": {
            "Bowler", "Witch", "Electro Dragon", "Balloon",
            "Rage Spell", "Heal Spell", "Freeze Spell", "Bat Spell",
            "Grand Warden", "Archer Queen", "Barbarian King",
        },
        "support": {
            "Golem", "Ice Golem", "Healer", "Clone Spell", "Poison Spell", "Wizard",
        },
    },
    11: {
        "core": {
            "Electro Dragon", "Balloon", "Hog Rider", "Miner",
            "Rage Spell", "Heal Spell", "Freeze Spell",
            "Grand Warden", "Archer Queen", "Barbarian King",
        },
        "support": {
            "Clone Spell", "Poison Spell", "Healer", "Wizard", "Baby Dragon",
        },
    },
    10: {
        "core": {
            "Golem", "Bowler", "Witch", "Lava Hound", "Balloon",
            "Rage Spell", "Heal Spell", "Jump Spell", "Haste Spell",
            "Archer Queen", "Barbarian King",
        },
        "support": {
            "Wizard", "Wall Breaker", "Poison Spell", "Freeze Spell", "Minion",
        },
    },
    9: {
        "core": {
            "Golem", "Hog Rider", "Lava Hound", "Balloon",
            "Heal Spell", "Rage Spell", "Haste Spell", "Poison Spell",
            "Archer Queen", "Barbarian King",
        },
        "support": {
            "Wizard", "Wall Breaker", "Valkyrie", "Minion",
        },
    },
}

FARM_PRIORITY_UNITS: set[str] = {
    "Sneaky Goblin", "Goblin", "Barbarian", "Archer", "Baby Dragon",
    "Miner", "Electro Dragon", "Balloon", "Rage Spell", "Jump Spell", "Haste Spell",
}

WAR_ONLY_UNITS: set[str] = {
    "Overgrowth Spell", "Bat Spell", "Clone Spell", "Hog Rider",
    "Golem", "Lava Hound", "Super Witch", "Poison Spell", "Headhunter",
}

DE_ITEMS: set[str] = {
    "Barbarian King", "Archer Queen", "Royal Champion", "Minion Prince",
    "Minion", "Hog Rider", "Valkyrie", "Golem", "Witch", "Lava Hound",
    "Bowler", "Ice Golem", "Headhunter", "Apprentice Warden", "Druid",
    "Poison Spell", "Earthquake Spell", "Haste Spell", "Skeleton Spell",
    "Bat Spell", "Overgrowth Spell",
    "L.A.S.S.I", "Electro Owl", "Mighty Yak", "Unicorn", "Frosty",
    "Diggy", "Poison Lizard", "Phoenix", "Spirit Fox", "Angry Jelly", "Sneezy",
}

EPIC_EQUIPMENT: set[str] = {
    "Giant Gauntlet", "Frozen Arrow", "Fireball", "Spiky Ball",
    "Rocket Spear", "Magic Mirror", "Electro Boots", "Snake Bracelet",
    "Action Figure",
}


def json_loads(raw: str) -> Any:
    if orjson is not None:
        return orjson.loads(raw)
    return _stdlib_json.loads(raw)


def json_dumps(obj: Any, pretty: bool = True) -> str:
    if orjson is not None:
        opts = orjson.OPT_INDENT_2 if pretty else 0
        return orjson.dumps(obj, option=opts).decode("utf-8")
    return _stdlib_json.dumps(obj, indent=2 if pretty else None, ensure_ascii=False)


def get_meta_weight(th: int, name: str, focus: str) -> float:
    clamped = max(9, min(17, th)) if th else 16
    table = TH_META_WEIGHTS[clamped]
    if name in table["core"]:
        base = 3.0
    elif name in table["support"]:
        base = 2.0
    else:
        base = 1.0

    if focus == "farm":
        if name in FARM_PRIORITY_UNITS:
            return max(base, 2.8)
        if name in WAR_ONLY_UNITS:
            return 0.5
    return base


def compute_score(
    item: dict[str, Any],
    th: int,
    focus: str,
    cwl_within_7d: bool,
    war_always: bool,
) -> tuple[float, float]:
    lv = int(item.get("lv", item.get("level", 0)) or 0)
    cap = int(item.get("cap", item.get("maxLevel", 0)) or 0)
    deficit = int(item.get("deficit", max(0, cap - lv)) or 0)
    name = str(item.get("name", ""))
    upgrading = bool(item.get("upgrading", False))

    meta_w = get_meta_weight(th, name, focus)

    # SPEC §9 formula:
    # priority_score = (meta_weight * deficit) + cwl_urgency_bonus + war_frequency_weight
    cwl_urgency_bonus = 2.0 if ((cwl_within_7d or focus == "cwl") and upgrading) else 0.0
    if focus == "cwl" and not upgrading and meta_w >= 3.0:
        cwl_urgency_bonus = 2.0
    war_frequency_weight = 1.0 if (war_always and meta_w >= 2.0) else 0.0

    if focus == "rush-fix":
        # Invert priority toward lowest-level / highest-deficit items
        ratio_missing = (deficit / cap) if cap > 0 else 1.0
        score = round(deficit * (2.0 + ratio_missing) + (0.25 * meta_w) + cwl_urgency_bonus, 2)
    else:
        score = round((meta_w * deficit) + cwl_urgency_bonus + war_frequency_weight, 2)
    return score, meta_w


def _stars_badge(meta_w: float) -> str:
    if meta_w >= 2.8:
        return "⭐⭐⭐"
    if meta_w >= 1.8:
        return "⭐⭐"
    return "⭐"


def _priority_badge(score: float) -> str:
    if score >= 5.0:
        return "🔴 HIGH"
    if score >= 2.5:
        return "🟡 MED"
    return "🟢 LOW"


def _normalize_entry(item: dict[str, Any], category: str) -> dict[str, Any] | None:
    if item.get("village") == "builderBase":
        return None
    lv = int(item.get("lv", item.get("level", 0)) or 0)
    cap = int(item.get("cap", item.get("maxLevel", 0)) or 0)
    deficit = int(item.get("deficit", max(0, cap - lv)) or 0)
    if cap <= 0 or deficit <= 0:
        return None
    return {
        "name": str(item.get("name", "")),
        "category": category,
        "lv": lv,
        "cap": cap,
        "deficit": deficit,
        "upgrading": bool(item.get("upgrading", False)),
    }


def analyze_upgrades(
    data: dict[str, Any],
    focus: str = "war",
    builders: int = 6,
    lab_available: bool = True,
) -> dict[str, Any]:
    th = int(data.get("th", data.get("townHallLevel", 16)) or 16)
    name = str(data.get("name", "Player"))
    cwl_within_7d = bool(data.get("cwlWithin7Days", False)) or (int(data.get("cwlWithinDays", 999) or 999) <= 7)
    war_always = str(data.get("warFrequency", "")).lower() == "always"

    lab_items: list[dict[str, Any]] = []
    for t in data.get("troops") or []:
        e = _normalize_entry(t, "troop")
        if e:
            lab_items.append(e)
    for s in data.get("spells") or []:
        e = _normalize_entry(s, "spell")
        if e:
            lab_items.append(e)

    builder_items: list[dict[str, Any]] = []
    seen_equip: set[str] = set()
    for h in data.get("heroes") or []:
        e = _normalize_entry(h, "hero")
        if e:
            builder_items.append(e)
        for eq in h.get("equip") or h.get("equipment") or []:
            eq_e = _normalize_entry(eq, "equipment")
            if eq_e and eq_e["name"] not in seen_equip:
                seen_equip.add(eq_e["name"])
                builder_items.append(eq_e)
    for eq in data.get("heroEquipment") or []:
        eq_e = _normalize_entry(eq, "equipment")
        if eq_e and eq_e["name"] not in seen_equip:
            seen_equip.add(eq_e["name"])
            builder_items.append(eq_e)
    for p in data.get("pets") or []:
        p_e = _normalize_entry(p, "pet")
        if p_e:
            builder_items.append(p_e)

    for bucket in (lab_items, builder_items):
        for item in bucket:
            score, meta_w = compute_score(item, th, focus, cwl_within_7d, war_always)
            item["score"] = score
            item["metaWeight"] = meta_w
            item["priority"] = _priority_badge(score)
        bucket.sort(key=lambda x: (-x["score"], -x["deficit"], -x["metaWeight"], x["name"]))

    top_lab = lab_items[:3]
    top_builder = builder_items[:3]

    # SPEC §7: approximate resource forecast derived from deficit counts
    de_hero_pet_k = 0
    de_lab_k = 0
    shiny_ore = 0
    starry_ore = 0
    builder_days = 0

    per_hero_de_k = max(40, min(260, th * 14))
    per_lab_de_k = max(30, min(220, th * 12))

    for item in top_lab:
        if item["name"] in DE_ITEMS:
            de_lab_k += item["deficit"] * per_lab_de_k
    for item in top_builder:
        cat = item["category"]
        if cat == "equipment":
            shiny_ore += item["deficit"] * 300
            if item["name"] in EPIC_EQUIPMENT:
                starry_ore += item["deficit"] * 25
        else:
            if item["name"] in DE_ITEMS:
                de_hero_pet_k += item["deficit"] * per_hero_de_k
            builder_days += item["deficit"] * max(2, min(8, th // 2))

    return {
        "player": {"tag": data.get("tag", ""), "name": name, "th": th},
        "focus": focus,
        "builders": builders,
        "labAvailable": lab_available,
        "topLabUpgrades": top_lab,
        "topBuilderUpgrades": top_builder,
        "resourceForecast": {
            "approximate": True,
            "darkElixirTotal": (de_hero_pet_k + de_lab_k) * 1000,
            "darkElixirHeroesPets": de_hero_pet_k * 1000,
            "darkElixirLab": de_lab_k * 1000,
            "shinyOre": shiny_ore,
            "starryOre": starry_ore,
            "builderDays": builder_days,
        },
    }


def render_markdown(plan: dict[str, Any]) -> str:
    p = plan["player"]
    lines: list[str] = [
        f"## 🏰 Upgrade Report — {p['name']} (TH{p['th']})",
        f"_Focus: `{plan['focus']}` · Builders: {plan['builders']} · Lab free: {str(plan['labAvailable']).lower()}_",
        "",
        "### ⚗️ TOP 3 LAB UPGRADES",
    ]
    if not plan["topLabUpgrades"]:
        lines.append("All tracked lab troops and spells are maxed.")
    else:
        lines.append("| # | Troop/Spell | Current | TH Cap | Deficit | Meta Weight | Score | Priority |")
        lines.append("|---|-------------|---------|--------|---------|-------------|-------|----------|")
        for idx, u in enumerate(plan["topLabUpgrades"], start=1):
            lines.append(
                f"| {idx} | {u['name']} | Lv {u['lv']} | Lv {u['cap']} | {u['deficit']} | "
                f"{_stars_badge(u['metaWeight'])} | {u['score']} | {u['priority']} |"
            )

    lines.extend(["", "### 🔨 TOP 3 BUILDER UPGRADES"])
    if not plan["topBuilderUpgrades"]:
        lines.append("All tracked heroes, equipment, and pets are maxed.")
    else:
        lines.append("| # | Target | Current | Cap | Deficit | Score | Priority |")
        lines.append("|---|--------|---------|-----|---------|-------|----------|")
        for idx, u in enumerate(plan["topBuilderUpgrades"], start=1):
            lines.append(
                f"| {idx} | {u['name']} | Lv {u['lv']} | {u['cap']} | {u['deficit']} | "
                f"{u['score']} | {u['priority']} |"
            )

    rf = plan["resourceForecast"]
    de_total_k = rf["darkElixirTotal"] // 1000
    de_hp_k = rf["darkElixirHeroesPets"] // 1000
    de_lab_k = rf["darkElixirLab"] // 1000
    lines.extend([
        "",
        "### 💎 RESOURCE FORECAST",
        f"- Dark Elixir needed (approximate): ~{de_hp_k}K (Heroes/Pets) + ~{de_lab_k}K (Lab) = **~{de_total_k}K total**",
        f"- Shiny Ore (approximate): ~{rf['shinyOre']:,}",
        f"- Starry Ore (approximate): ~{rf['starryOre']:,}",
        f"- Builder time (approximate): ~{rf['builderDays']} days across {plan['builders']} builders",
    ])
    return "\n".join(lines)


def render_table(plan: dict[str, Any]) -> str:
    p = plan["player"]
    lines = [
        f"UPGRADE REPORT — {p['name']} (TH{p['th']}) [focus={plan['focus']}, builders={plan['builders']}, lab={plan['labAvailable']}]",
        "",
        "1. TOP 3 LAB UPGRADES",
    ]
    if not plan["topLabUpgrades"]:
        lines.append("  (none — all maxed)")
    else:
        lines.append(f"  {'#':<3} {'Name':<20} {'Lv':<6} {'Cap':<6} {'Deficit':<8} {'Score':<7} {'Priority'}")
        for idx, u in enumerate(plan["topLabUpgrades"], start=1):
            lines.append(f"  {idx:<3} {u['name']:<20} {u['lv']:<6} {u['cap']:<6} {u['deficit']:<8} {u['score']:<7} {u['priority']}")

    lines.extend(["", "2. TOP 3 BUILDER UPGRADES"])
    if not plan["topBuilderUpgrades"]:
        lines.append("  (none — all maxed)")
    else:
        lines.append(f"  {'#':<3} {'Name':<20} {'Lv':<6} {'Cap':<6} {'Deficit':<8} {'Score':<7} {'Priority'}")
        for idx, u in enumerate(plan["topBuilderUpgrades"], start=1):
            lines.append(f"  {idx:<3} {u['name']:<20} {u['lv']:<6} {u['cap']:<6} {u['deficit']:<8} {u['score']:<7} {u['priority']}")

    rf = plan["resourceForecast"]
    lines.extend([
        "",
        "3. RESOURCE FORECAST (estimates are approximate)",
        f"  Dark Elixir : ~{rf['darkElixirTotal']:,}",
        f"  Shiny Ore   : ~{rf['shinyOre']:,}",
        f"  Starry Ore  : ~{rf['starryOre']:,}",
        f"  Builder Days: ~{rf['builderDays']} days",
    ])
    return "\n".join(lines)


def _parse_args(argv: list[str]) -> dict[str, Any]:
    focus = "war"
    builders = 6
    lab_available = True
    fmt = "markdown"

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--help", "-h"):
            print(HELP_TEXT)
            sys.exit(0)
        elif arg == "--focus":
            i += 1
            if i >= len(argv):
                raise ValueError("--focus requires a value (war|cwl|rush-fix|farm).")
            focus = argv[i]
        elif arg.startswith("--focus="):
            focus = arg.split("=", 1)[1]
        elif arg == "--builders":
            i += 1
            if i >= len(argv):
                raise ValueError("--builders requires an integer.")
            builders = int(argv[i])
        elif arg.startswith("--builders="):
            builders = int(arg.split("=", 1)[1])
        elif arg == "--lab-available":
            if i + 1 < len(argv) and argv[i + 1].lower() in ("true", "false", "1", "0"):
                i += 1
                lab_available = argv[i].lower() in ("true", "1")
            else:
                lab_available = True
        elif arg.startswith("--lab-available="):
            lab_available = arg.split("=", 1)[1].lower() in ("true", "1")
        elif arg == "--format":
            i += 1
            if i >= len(argv):
                raise ValueError("--format requires a value (table|json|markdown).")
            fmt = argv[i]
        elif arg.startswith("--format="):
            fmt = arg.split("=", 1)[1]
        else:
            raise ValueError(f"Unknown argument: {arg}")
        i += 1

    if focus not in ("war", "cwl", "rush-fix", "farm"):
        raise ValueError(f"Invalid --focus '{focus}'. Choose war|cwl|rush-fix|farm.")
    if fmt not in ("table", "json", "markdown"):
        raise ValueError(f"Invalid --format '{fmt}'. Choose table|json|markdown.")
    if builders < 1:
        raise ValueError("--builders must be >= 1.")

    return {"focus": focus, "builders": builders, "lab_available": lab_available, "format": fmt}


def main(argv: list[str] | None = None) -> int:
    try:
        opts = _parse_args(sys.argv[1:] if argv is None else argv)
    except ValueError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1

    raw_stdin = sys.stdin.read().strip()
    if not raw_stdin:
        sys.stderr.write("Error: Expected compact player JSON on stdin.\n")
        return 1

    try:
        data = json_loads(raw_stdin)
    except Exception as exc:
        sys.stderr.write(f"Error: Invalid JSON on stdin: {exc}\n")
        return 1

    plan = analyze_upgrades(
        data,
        focus=opts["focus"],
        builders=opts["builders"],
        lab_available=opts["lab_available"],
    )

    if opts["format"] == "json":
        print(json_dumps(plan))
    elif opts["format"] == "table":
        print(render_table(plan))
    else:
        print(render_markdown(plan))
    return 0


if __name__ == "__main__":
    sys.exit(main())
