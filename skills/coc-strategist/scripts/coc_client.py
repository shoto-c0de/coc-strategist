#!/usr/bin/env python3
"""Self-contained Clash of Clans API client, TTL cache, and tactical JSON normalizer."""

from __future__ import annotations

import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# SPEC §2 & Global Rule 1: optional dependencies with stdlib fallbacks
try:
    import httpx  # type: ignore
except ImportError:  # pragma: no cover - fallback path
    httpx = None  # type: ignore

try:
    import orjson  # type: ignore
except ImportError:  # pragma: no cover - fallback path
    orjson = None  # type: ignore

import json as _stdlib_json

# SPEC §7: verbatim help output
HELP_TEXT = """Usage: coc_client.py <command> [options]

Commands:
  player <tag>          Fetch & normalize player profile
  battlelog <tag>       Fetch recent battle log
  clan <tag>            Fetch & normalize clan summary
  members <tag>         Fetch clan member roster
  war <clan_tag>        Fetch current war board
  cwl <clan_tag>        Fetch CWL league group

Options:
  --raw                 Output raw API JSON (skip normalizer)
  --token TOKEN         Override COC_API_TOKEN env var
  --base-url URL        Override COC_API_BASE_URL env var
  --cache-ttl SEC       Override default TTL (default: per-endpoint)
  --help                Show this help

Exit Codes:
  0   Success
  1   Invalid tag format
  2   Network / timeout error
  3   403 — IP mismatch (prints detected IP)
  4   404 — Tag not found
  5   429 — Rate limited (retries exhausted)
  10  Private war log (fallback data printed to stdout)"""

DEFAULT_BASE_URL = "https://api.clashofclans.com/v1"

# SPEC §4 & §11: valid Clash of Clans tag pattern
TAG_REGEX = re.compile(r"^#[0289CGJLPQRUVY]{3,12}$")
IPV4_REGEX = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")

# SPEC §4: per-endpoint TTL cache durations in seconds
ENDPOINT_TTLS: dict[str, int] = {
    "player": 300,
    "battlelog": 120,
    "clan": 300,
    "members": 300,
    "warlog": 600,
    "war": 120,
    "cwl": 300,
    "cwl_war": 120,
}

# SPEC §4: subcommand -> official API path template
ENDPOINT_PATHS: dict[str, str] = {
    "player": "/players/{tag}",
    "battlelog": "/players/{tag}/battlelog",
    "clan": "/clans/{tag}",
    "members": "/clans/{tag}/members",
    "warlog": "/clans/{tag}/warlog",
    "war": "/clans/{tag}/currentwar",
    "cwl": "/clans/{tag}/currentwar/leaguegroup",
}

KNOWN_PETS: set[str] = {
    "L.A.S.S.I",
    "Electro Owl",
    "Mighty Yak",
    "Unicorn",
    "Frosty",
    "Diggy",
    "Poison Lizard",
    "Phoenix",
    "Spirit Fox",
    "Angry Jelly",
    "Sneezy",
}

# SPEC §9: condensed meta-relevance weights (1.0-3.0) for tie-break sorting
_META_CORE_BY_TH: dict[int, set[str]] = {
    17: {
        "Root Rider", "Electro Titan", "Healer", "Rage Spell", "Heal Spell",
        "Freeze Spell", "Overgrowth Spell", "Barbarian King", "Archer Queen",
        "Grand Warden", "Royal Champion", "Giant Gauntlet", "Rage Vial",
        "Giant Arrow", "Healer Puppet", "Eternal Tome", "Haste Vial",
        "Seeking Shield", "Spirit Fox", "Phoenix",
    },
    16: {
        "Root Rider", "Thrower", "Electro Titan", "Healer", "Rage Spell",
        "Heal Spell", "Freeze Spell", "Overgrowth Spell", "Barbarian King",
        "Archer Queen", "Grand Warden", "Royal Champion", "Giant Gauntlet",
        "Rage Vial", "Giant Arrow", "Healer Puppet", "Eternal Tome",
        "Haste Vial", "Seeking Shield", "Spirit Fox", "Phoenix",
    },
    15: {
        "Super Witch", "Witch", "Balloon", "Lava Hound", "Healer",
        "Bat Spell", "Freeze Spell", "Rage Spell", "Clone Spell",
        "Grand Warden", "Archer Queen", "Eternal Tome", "Giant Arrow",
        "Barbarian King", "Royal Champion", "Diggy", "Phoenix",
    },
    14: {
        "Electro Dragon", "Balloon", "Hog Rider", "Miner", "Healer",
        "Rage Spell", "Freeze Spell", "Lightning Spell", "Grand Warden",
        "Archer Queen", "Eternal Tome", "Unicorn",
    },
    13: {
        "Yeti", "Bowler", "Balloon", "Lava Hound", "Healer", "Rage Spell",
        "Heal Spell", "Freeze Spell", "Haste Spell", "Archer Queen",
        "Grand Warden", "Royal Champion", "Barbarian King",
    },
    12: {
        "Bowler", "Witch", "Electro Dragon", "Balloon", "Rage Spell",
        "Heal Spell", "Freeze Spell", "Bat Spell", "Grand Warden",
        "Archer Queen", "Barbarian King",
    },
    11: {
        "Electro Dragon", "Balloon", "Hog Rider", "Miner", "Rage Spell",
        "Heal Spell", "Freeze Spell", "Grand Warden", "Archer Queen",
        "Barbarian King",
    },
    10: {
        "Golem", "Bowler", "Witch", "Lava Hound", "Balloon", "Rage Spell",
        "Heal Spell", "Jump Spell", "Haste Spell", "Archer Queen",
        "Barbarian King",
    },
    9: {
        "Golem", "Hog Rider", "Lava Hound", "Balloon", "Heal Spell",
        "Rage Spell", "Haste Spell", "Poison Spell", "Archer Queen",
        "Barbarian King",
    },
}

_META_SUPPORT: set[str] = {
    "Wizard", "Baby Dragon", "Valkyrie", "Wall Breaker", "Super Wall Breaker",
    "Ice Golem", "Headhunter", "Druid", "Super Wizard", "Poison Spell",
    "Invisibility Spell", "Minion", "Diggy", "Frosty", "Unicorn",
}

_MEM_CACHE: dict[str, tuple[float, Any]] = {}


def json_loads(data: bytes | str) -> Any:
    if orjson is not None:
        return orjson.loads(data)
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return _stdlib_json.loads(data)


def json_dumps(obj: Any, pretty: bool = False) -> str:
    if orjson is not None:
        opts = orjson.OPT_INDENT_2 if pretty else 0
        return orjson.dumps(obj, option=opts).decode("utf-8")
    return _stdlib_json.dumps(obj, indent=2 if pretty else None, ensure_ascii=False)


# SPEC §11: sanitize names to alphanumeric + limited Unicode
def sanitize_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = "".join(
        ch for ch in value
        if (ch.isalnum() or ch in " _-.!'()&") and ord(ch) >= 32
    )
    return " ".join(cleaned.split())[:64]


# SPEC §4 & §11: validate tag regex ^#[0289CGJLPQRUVY]{3,12}$
def normalize_tag(raw_tag: str) -> str:
    tag = raw_tag.strip().upper()
    if not tag.startswith("#"):
        tag = "#" + tag
    if not TAG_REGEX.match(tag):
        raise ValueError(
            f"Invalid tag format '{raw_tag}'. Expected ^#[0289CGJLPQRUVY]{{3,12}}$."
        )
    return tag


def encode_tag(tag: str) -> str:
    # SPEC §4: URL-encode '#' -> '%23'
    return urllib.parse.quote(tag, safe="")


def _meta_weight(th: int, name: str) -> float:
    clamped = max(9, min(17, th)) if th else 16
    if name in _META_CORE_BY_TH.get(clamped, set()):
        return 3.0
    if name in _META_SUPPORT:
        return 2.0
    return 1.0


# SPEC §4: client-side token-bucket throttle at 8 RPS with burst of 3
class TokenBucket:
    def __init__(self, rate: float = 8.0, capacity: float = 3.0) -> None:
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.updated = time.monotonic()

    def acquire(self) -> None:
        while True:
            now = time.monotonic()
            elapsed = now - self.updated
            self.updated = now
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return
            time.sleep((1.0 - self.tokens) / self.rate)


_BUCKET = TokenBucket(rate=8.0, capacity=3.0)


def _cache_file(endpoint: str, tag: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", tag.lstrip("#"))
    return Path.home() / ".cache" / "coc-strategist" / f"{endpoint}_{safe}.json"


def _read_cache(endpoint: str, tag: str, ttl: int) -> Any | None:
    if ttl <= 0:
        return None
    key = f"{endpoint}:{tag}"
    now = time.time()
    entry = _MEM_CACHE.get(key)
    if entry is not None:
        ts, data = entry
        if now - ts < ttl:
            return data
    path = _cache_file(endpoint, tag)
    try:
        if path.exists():
            payload = json_loads(path.read_bytes())
            if isinstance(payload, dict) and now - float(payload.get("ts", 0)) < ttl:
                data = payload.get("data")
                _MEM_CACHE[key] = (float(payload["ts"]), data)
                return data
    except OSError:
        pass
    except Exception:
        pass
    return None


def _write_cache(endpoint: str, tag: str, data: Any, ttl: int) -> None:
    if ttl <= 0:
        return
    now = time.time()
    _MEM_CACHE[f"{endpoint}:{tag}"] = (now, data)
    path = _cache_file(endpoint, tag)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json_dumps({"ts": now, "data": data}), encoding="utf-8")
    except OSError:
        pass


def _http_get(url: str, token: str, timeout: float = 15.0) -> tuple[int, bytes]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if httpx is not None:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, headers=headers)
            return resp.status_code, resp.content

    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class APIError(Exception):
    def __init__(self, exit_code: int, message: str, status: int = 0, body: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.status = status
        self.body = body or {}


def fetch_endpoint(
    endpoint: str,
    tag: str,
    token: str,
    base_url: str,
    ttl_override: int | None = None,
) -> Any:
    ttl = ENDPOINT_TTLS[endpoint] if ttl_override is None else ttl_override
    cached = _read_cache(endpoint, tag, ttl)
    if cached is not None:
        return cached

    path = ENDPOINT_PATHS[endpoint].format(tag=encode_tag(tag))
    url = f"{base_url.rstrip('/')}{path}"

    # SPEC §4: exponential backoff with jitter on 429, max 3 attempts
    for attempt in range(3):
        _BUCKET.acquire()
        try:
            status, raw_bytes = _http_get(url, token)
        except Exception as exc:
            raise APIError(2, f"Network/timeout error while calling {endpoint}: {exc}") from exc

        body: dict[str, Any] = {}
        if raw_bytes:
            try:
                parsed = json_loads(raw_bytes)
                if isinstance(parsed, dict):
                    body = parsed
            except Exception:
                parsed = None
        else:
            parsed = None

        if status == 200:
            if parsed is None:
                raise APIError(2, f"Invalid JSON received from {endpoint}.")
            _write_cache(endpoint, tag, parsed, ttl)
            return parsed

        if status == 429:
            if attempt < 2:
                wait = min((2 ** attempt) * 0.5 + random.uniform(0.0, 0.3), 30.0)
                time.sleep(wait)
                continue
            raise APIError(5, "Error: 429 Too Many Requests — rate limited after 3 attempts.", status=429, body=body)

        reason = str(body.get("reason", ""))
        detail = str(body.get("message", ""))

        if status == 400:
            raise APIError(1, f"Error: 400 {reason or 'badRequest'} — invalid tag format ({tag}).", status=400, body=body)

        if status == 403:
            # SPEC §4 & §5 Mode B: detect accessDenied.invalidIp and report egress IP
            if "invalidip" in reason.lower() or "ip" in detail.lower():
                match = IPV4_REGEX.search(detail)
                egress_ip = match.group(1) if match else "unknown"
                raise APIError(
                    3,
                    f"Your egress IP is {egress_ip} — whitelist it at developer.clashofclans.com or switch to the hosted MCP server.",
                    status=403,
                    body=body,
                )
            raise APIError(3, f"Error: 403 {reason or 'accessDenied'} — {detail or 'access denied'}.", status=403, body=body)

        if status == 404:
            raise APIError(4, f"Error: 404 {reason or 'notFound'} — tag {tag} not found.", status=404, body=body)

        if status in (500, 503):
            raise APIError(
                2,
                f"Error: {status} {reason or 'serviceUnavailable'} — Supercell API maintenance; retry after 60s.",
                status=status,
                body=body,
            )

        raise APIError(2, f"Error: HTTP {status} ({reason}) — {detail}".strip(), status=status, body=body)

    raise APIError(5, "Error: 429 Too Many Requests — retries exhausted.")


def _normalize_item_list(items: list[dict[str, Any]], th: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        lv = int(item.get("level", item.get("lv", 0)) or 0)
        cap = int(item.get("maxLevel", item.get("cap", 0)) or 0)
        # SPEC §6 rule 1: strip maxed items
        if cap <= 0 or lv >= cap:
            continue
        name = sanitize_name(item.get("name", ""))
        if not name:
            continue
        # SPEC §6 rule 3: compute delta
        entry: dict[str, Any] = {
            "name": name,
            "lv": lv,
            "cap": cap,
            "deficit": cap - lv,
        }
        # SPEC §6 rule 2: drop "village": "home", preserve non-home village tags
        village = item.get("village")
        if village and village != "home":
            entry["village"] = village
        if item.get("upgrading"):
            entry["upgrading"] = True
        result.append(entry)

    # SPEC §6 rule 4: sort by deficit desc, then meta-relevance desc
    result.sort(key=lambda x: (-x["deficit"], -_meta_weight(th, x["name"]), x["name"]))
    return result


# SPEC §6: normalize player profile into compact tactical JSON
def normalize_player(raw: dict[str, Any]) -> dict[str, Any]:
    th = int(raw.get("townHallLevel", raw.get("th", 0)) or 0)

    raw_troops = list(raw.get("troops") or [])
    raw_pets = list(raw.get("pets") or [])
    if not raw_pets and raw_troops:
        filtered_troops: list[dict[str, Any]] = []
        for t in raw_troops:
            if t.get("name") in KNOWN_PETS and t.get("village", "home") == "home":
                raw_pets.append(t)
            else:
                filtered_troops.append(t)
        raw_troops = filtered_troops

    norm_heroes: list[dict[str, Any]] = []
    extra_equip: list[dict[str, Any]] = []
    seen_equip: set[str] = set()

    for hero in raw.get("heroes") or []:
        lv = int(hero.get("level", hero.get("lv", 0)) or 0)
        cap = int(hero.get("maxLevel", hero.get("cap", 0)) or 0)
        name = sanitize_name(hero.get("name", ""))
        if not name or cap <= 0:
            continue
        raw_eq = list(hero.get("equipment") or hero.get("equip") or [])
        norm_eq = _normalize_item_list(raw_eq, th)
        for eq in norm_eq:
            seen_equip.add(eq["name"])

        # SPEC §6 rule 1: strip maxed heroes; keep any non-maxed equipment in heroEquipment
        if lv >= cap:
            extra_equip.extend(norm_eq)
            continue

        h_entry: dict[str, Any] = {
            "name": name,
            "lv": lv,
            "cap": cap,
            "deficit": cap - lv,
            "equip": norm_eq,
        }
        village = hero.get("village")
        if village and village != "home":
            h_entry["village"] = village
        if hero.get("upgrading"):
            h_entry["upgrading"] = True
        norm_heroes.append(h_entry)

    norm_heroes.sort(key=lambda x: (-x["deficit"], -_meta_weight(th, x["name"]), x["name"]))

    # Include unequipped or orphaned non-maxed equipment from top-level heroEquipment
    top_equip = _normalize_item_list(list(raw.get("heroEquipment") or []), th)
    merged_equip: list[dict[str, Any]] = list(extra_equip)
    for eq in top_equip:
        if eq["name"] not in seen_equip:
            seen_equip.add(eq["name"])
            merged_equip.append(eq)
    merged_equip.sort(key=lambda x: (-x["deficit"], -_meta_weight(th, x["name"]), x["name"]))

    out: dict[str, Any] = {
        "tag": raw.get("tag", ""),
        "name": sanitize_name(raw.get("name", "")),
        "th": th,
    }
    if "townHallWeaponLevel" in raw:
        out["thWeapon"] = raw["townHallWeaponLevel"]
    if "builderHallLevel" in raw:
        out["bh"] = raw["builderHallLevel"]
    if "trophies" in raw:
        out["trophies"] = raw["trophies"]
    if "warStars" in raw:
        out["warStars"] = raw["warStars"]
    if "warPreference" in raw:
        out["warPreference"] = raw["warPreference"]

    clan = raw.get("clan")
    if isinstance(clan, dict) and clan.get("tag"):
        out["clan"] = {
            "tag": clan.get("tag", ""),
            "name": sanitize_name(clan.get("name", "")),
            "level": clan.get("clanLevel", 0),
        }

    out["heroes"] = norm_heroes
    if merged_equip:
        out["heroEquipment"] = merged_equip
    out["troops"] = _normalize_item_list(raw_troops, th)
    out["spells"] = _normalize_item_list(list(raw.get("spells") or []), th)
    out["pets"] = _normalize_item_list(raw_pets, th)

    if isinstance(raw.get("warReadiness"), dict):
        out["warReadiness"] = raw["warReadiness"]
    return out


def normalize_battlelog(raw: dict[str, Any] | list[Any]) -> dict[str, Any]:
    items = raw.get("items", []) if isinstance(raw, dict) else list(raw)
    battles: list[dict[str, Any]] = []
    attack_stars: list[int] = []
    attack_dest: list[float] = []

    for b in items[:25]:
        is_attack = bool(b.get("attack", True))
        stars = int(b.get("stars", 0) or 0)
        dest = float(b.get("destructionPercentage", 0.0) or 0.0)
        if is_attack:
            attack_stars.append(stars)
            attack_dest.append(dest)
        army = {}
        for unit in b.get("army") or []:
            uname = sanitize_name(unit.get("name", ""))
            if uname:
                army[uname] = int(unit.get("count", 1) or 1)
        entry: dict[str, Any] = {
            "battleType": b.get("battleType", "unknown"),
            "attack": is_attack,
            "stars": stars,
            "destructionPercentage": dest,
        }
        if b.get("opponentPlayerTag"):
            entry["opponentTag"] = b["opponentPlayerTag"]
        if army:
            entry["army"] = army
        battles.append(entry)

    return {
        "count": len(battles),
        "avgStars": round(sum(attack_stars) / len(attack_stars), 2) if attack_stars else 0.0,
        "avgDestruction": round(sum(attack_dest) / len(attack_dest), 1) if attack_dest else 0.0,
        "battles": battles,
    }


def normalize_clan(raw: dict[str, Any]) -> dict[str, Any]:
    th_dist: dict[str, int] = {}
    for m in raw.get("memberList") or []:
        th_key = str(m.get("townHallLevel", 0))
        th_dist[th_key] = th_dist.get(th_key, 0) + 1

    out: dict[str, Any] = {
        "tag": raw.get("tag", ""),
        "name": sanitize_name(raw.get("name", "")),
        "clanLevel": raw.get("clanLevel", 0),
        "warFrequency": raw.get("warFrequency", "unknown"),
        "warWinStreak": raw.get("warWinStreak", 0),
        "warWins": raw.get("warWins", 0),
        "warLosses": raw.get("warLosses", 0),
        "warTies": raw.get("warTies", 0),
        "isWarLogPublic": bool(raw.get("isWarLogPublic", True)),
        "members": raw.get("members", 0),
        "requiredTrophies": raw.get("requiredTrophies", 0),
    }
    if th_dist:
        out["thDistribution"] = dict(sorted(th_dist.items(), key=lambda kv: int(kv[0]), reverse=True))
    return out


def normalize_members(raw: dict[str, Any] | list[Any]) -> dict[str, Any]:
    items = raw.get("items", []) if isinstance(raw, dict) else list(raw)
    roster: list[dict[str, Any]] = []
    for m in items:
        roster.append({
            "tag": m.get("tag", ""),
            "name": sanitize_name(m.get("name", "")),
            "th": int(m.get("townHallLevel", 0) or 0),
            "role": m.get("role", ""),
            "trophies": int(m.get("trophies", 0) or 0),
            "donations": int(m.get("donations", 0) or 0),
            "donationsReceived": int(m.get("donationsReceived", 0) or 0),
        })
    roster.sort(key=lambda x: (-x["th"], -x["trophies"], x["name"]))
    return {"count": len(roster), "members": roster}


# SPEC §6 rule 5: aggregate war metrics and emit compact war board JSON
def normalize_war(raw: dict[str, Any]) -> dict[str, Any]:
    state = raw.get("state", "unknown")
    team_size = int(raw.get("teamSize", 0) or 0)
    attacks_per_member = int(raw.get("attacksPerMember", 2) or 2)

    raw_clan = raw.get("clan") or {}
    raw_opp = raw.get("opponent") or {}

    opp_by_tag: dict[str, dict[str, Any]] = {}
    opp_th_spread: dict[str, int] = {}
    norm_opp_members: list[dict[str, Any]] = []

    for om in raw_opp.get("members") or []:
        oth = int(om.get("townHallLevel", 0) or 0)
        opp_th_spread[str(oth)] = opp_th_spread.get(str(oth), 0) + 1
        best = om.get("bestOpponentAttack") or {}
        entry = {
            "tag": om.get("tag", ""),
            "name": sanitize_name(om.get("name", "")),
            "th": oth,
            "mapPosition": int(om.get("mapPosition", 0) or 0),
            "bestStars": int(best.get("stars", 0) or 0),
            "bestDestruction": float(best.get("destructionPercentage", 0.0) or 0.0),
        }
        opp_by_tag[entry["tag"]] = entry
        norm_opp_members.append(entry)
    norm_opp_members.sort(key=lambda x: x["mapPosition"])

    norm_clan_members: list[dict[str, Any]] = []
    all_stars: list[int] = []
    all_dest: list[float] = []
    missed_attacks = 0
    mismatch_total = 0

    for cm in raw_clan.get("members") or []:
        cth = int(cm.get("townHallLevel", 0) or 0)
        attacks = cm.get("attacks") or []
        used = len(attacks)
        remaining = max(0, attacks_per_member - used)
        missed_attacks += remaining
        stars_sum = 0
        dest_list: list[float] = []
        member_mismatches = 0
        for atk in attacks:
            st = int(atk.get("stars", 0) or 0)
            ds = float(atk.get("destructionPercentage", 0.0) or 0.0)
            stars_sum += st
            dest_list.append(ds)
            all_stars.append(st)
            all_dest.append(ds)
            defender = opp_by_tag.get(atk.get("defenderTag", ""))
            if defender and cth < defender["th"]:
                member_mismatches += 1
        mismatch_total += member_mismatches

        m_entry: dict[str, Any] = {
            "tag": cm.get("tag", ""),
            "name": sanitize_name(cm.get("name", "")),
            "th": cth,
            "mapPosition": int(cm.get("mapPosition", 0) or 0),
            "attacksUsed": used,
            "attacksRemaining": remaining,
            "starsEarned": stars_sum,
            "avgDestruction": round(sum(dest_list) / used, 1) if used else 0.0,
            "mismatchCount": member_mismatches,
        }
        if "heroLevelAvg" in cm:
            m_entry["heroLevelAvg"] = cm["heroLevelAvg"]
        norm_clan_members.append(m_entry)
    norm_clan_members.sort(key=lambda x: x["mapPosition"])

    return {
        "state": state,
        "teamSize": team_size,
        "attacksPerMember": attacks_per_member,
        "preparationStartTime": raw.get("preparationStartTime", ""),
        "startTime": raw.get("startTime", ""),
        "endTime": raw.get("endTime", ""),
        "clan": {
            "tag": raw_clan.get("tag", ""),
            "name": sanitize_name(raw_clan.get("name", "")),
            "clanLevel": int(raw_clan.get("clanLevel", 0) or 0),
            "stars": int(raw_clan.get("stars", 0) or 0),
            "destructionPercentage": float(raw_clan.get("destructionPercentage", 0.0) or 0.0),
            "attacks": int(raw_clan.get("attacks", len(all_stars)) or 0),
            "avgStars": round(sum(all_stars) / len(all_stars), 2) if all_stars else 0.0,
            "avgDestruction": round(sum(all_dest) / len(all_dest), 1) if all_dest else 0.0,
            "missedAttacks": missed_attacks,
            "thMismatchCount": mismatch_total,
            "members": norm_clan_members,
        },
        "opponent": {
            "tag": raw_opp.get("tag", ""),
            "name": sanitize_name(raw_opp.get("name", "")),
            "clanLevel": int(raw_opp.get("clanLevel", 0) or 0),
            "stars": int(raw_opp.get("stars", 0) or 0),
            "destructionPercentage": float(raw_opp.get("destructionPercentage", 0.0) or 0.0),
            "attacks": int(raw_opp.get("attacks", 0) or 0),
            "thSpread": dict(sorted(opp_th_spread.items(), key=lambda kv: int(kv[0]), reverse=True)),
            "members": norm_opp_members,
        },
    }


def normalize_cwl(raw: dict[str, Any]) -> dict[str, Any]:
    clans: list[dict[str, Any]] = []
    for c in raw.get("clans") or []:
        th_spread: dict[str, int] = {}
        for m in c.get("members") or []:
            th_key = str(m.get("townHallLevel", 0))
            th_spread[th_key] = th_spread.get(th_key, 0) + 1
        clans.append({
            "tag": c.get("tag", ""),
            "name": sanitize_name(c.get("name", "")),
            "clanLevel": int(c.get("clanLevel", 0) or 0),
            "thSpread": dict(sorted(th_spread.items(), key=lambda kv: int(kv[0]), reverse=True)),
        })

    rounds: list[dict[str, Any]] = []
    for idx, r in enumerate(raw.get("rounds") or [], start=1):
        war_tags = [wt for wt in (r.get("warTags") or []) if wt and wt != "#0"]
        rounds.append({"round": idx, "warTags": war_tags})

    return {
        "state": raw.get("state", "unknown"),
        "season": raw.get("season", ""),
        "clans": clans,
        "rounds": rounds,
    }


NORMALIZERS = {
    "player": normalize_player,
    "battlelog": normalize_battlelog,
    "clan": normalize_clan,
    "members": normalize_members,
    "war": normalize_war,
    "cwl": normalize_cwl,
}


def _parse_args(argv: list[str]) -> dict[str, Any]:
    raw_flag = False
    token_val: str | None = None
    base_url_val: str | None = None
    ttl_val: int | None = None
    positionals: list[str] = []

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--help", "-h"):
            print(HELP_TEXT)
            sys.exit(0)
        elif arg == "--raw":
            raw_flag = True
        elif arg == "--token":
            i += 1
            if i >= len(argv):
                raise ValueError("--token requires a value.")
            token_val = argv[i]
        elif arg.startswith("--token="):
            token_val = arg.split("=", 1)[1]
        elif arg == "--base-url":
            i += 1
            if i >= len(argv):
                raise ValueError("--base-url requires a value.")
            base_url_val = argv[i]
        elif arg.startswith("--base-url="):
            base_url_val = arg.split("=", 1)[1]
        elif arg == "--cache-ttl":
            i += 1
            if i >= len(argv):
                raise ValueError("--cache-ttl requires an integer value.")
            ttl_val = int(argv[i])
        elif arg.startswith("--cache-ttl="):
            ttl_val = int(arg.split("=", 1)[1])
        elif arg.startswith("-"):
            raise ValueError(f"Unknown option: {arg}")
        else:
            positionals.append(arg)
        i += 1

    if len(positionals) < 2:
        raise ValueError("Missing required <command> and <tag>. Run with --help for usage.")

    command = positionals[0].lower()
    if command not in NORMALIZERS:
        raise ValueError(f"Unknown command '{command}'. Run with --help for usage.")

    return {
        "command": command,
        "tag": positionals[1],
        "raw": raw_flag,
        "token": token_val,
        "base_url": base_url_val,
        "cache_ttl": ttl_val,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        opts = _parse_args(sys.argv[1:] if argv is None else argv)
    except ValueError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1

    try:
        tag = normalize_tag(opts["tag"])
    except ValueError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1

    # SPEC §5 Mode B: read COC_API_TOKEN and COC_API_BASE_URL from environment
    token = (opts["token"] or os.environ.get("COC_API_TOKEN", "")).strip()
    if not token:
        sys.stderr.write(
            "Error: COC_API_TOKEN is not set. Set COC_API_TOKEN in your environment, "
            "pass --token, or connect to the hosted coc-strategist MCP server.\n"
        )
        return 1

    base_url = (opts["base_url"] or os.environ.get("COC_API_BASE_URL", DEFAULT_BASE_URL)).strip() or DEFAULT_BASE_URL
    command = opts["command"]
    ttl_override = opts["cache_ttl"]

    try:
        raw_data = fetch_endpoint(command, tag, token, base_url, ttl_override=ttl_override)
    except APIError as exc:
        # SPEC §4 & §7: private war log (403 accessDenied on war command) -> fallback + exit 10
        if command == "war" and exc.status == 403 and exc.exit_code == 3 and "invalidIp" not in str(exc):
            fallback_clan: dict[str, Any] = {}
            fallback_members: dict[str, Any] = {}
            fallback_warlog: list[dict[str, Any]] = []
            try:
                fallback_clan = fetch_endpoint("clan", tag, token, base_url, ttl_override=ttl_override)
            except APIError:
                pass
            try:
                fallback_members = fetch_endpoint("members", tag, token, base_url, ttl_override=ttl_override)
            except APIError:
                pass
            try:
                wl_raw = fetch_endpoint("warlog", tag, token, base_url, ttl_override=ttl_override)
                fallback_warlog = list(wl_raw.get("items") or [])[:10]
            except APIError:
                fallback_warlog = []

            if opts["raw"]:
                out_obj = {
                    "privateWarLog": True,
                    "clan": fallback_clan,
                    "members": fallback_members,
                    "warlog": fallback_warlog,
                }
            else:
                out_obj = {
                    "privateWarLog": True,
                    "state": "privateWarLog",
                    "clan": normalize_clan(fallback_clan) if fallback_clan else {"tag": tag},
                    "roster": normalize_members(fallback_members) if fallback_members else {"count": 0, "members": []},
                    "recentWarLog": [
                        {
                            "result": w.get("result", ""),
                            "teamSize": w.get("teamSize", 0),
                            "opponentName": sanitize_name((w.get("opponent") or {}).get("name", "")),
                            "destruction": (w.get("clan") or {}).get("destructionPercentage", 0.0),
                        }
                        for w in fallback_warlog
                    ],
                }
            sys.stderr.write("Notice: War log is private (403 accessDenied); emitted fallback roster and warlog data.\n")
            print(json_dumps(out_obj))
            return 10

        sys.stderr.write(f"{exc}\n")
        return exc.exit_code

    output_data = raw_data if opts["raw"] else NORMALIZERS[command](raw_data)
    print(json_dumps(output_data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
