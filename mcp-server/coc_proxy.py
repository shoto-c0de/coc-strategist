#!/usr/bin/env python3
"""Shared Clash of Clans API proxy with key-pool rotation, TTL cache, rate limits, and normalizer."""

from __future__ import annotations

import json as _stdlib_json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from typing import Any

# Global Rule 1: optional httpx/orjson with stdlib fallbacks
try:
    import httpx  # type: ignore
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore

try:
    import orjson  # type: ignore
except ImportError:  # pragma: no cover
    orjson = None  # type: ignore

DEFAULT_BASE_URL = "https://api.clashofclans.com/v1"
TAG_REGEX = re.compile(r"^#[0289CGJLPQRUVY]{3,12}$")

# SPEC §4: per-endpoint TTL cache durations (seconds)
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
    "L.A.S.S.I", "Electro Owl", "Mighty Yak", "Unicorn", "Frosty",
    "Diggy", "Poison Lizard", "Phoenix", "Spirit Fox", "Angry Jelly", "Sneezy",
}

_META_CORE_BY_TH: dict[int, set[str]] = {
    17: {"Root Rider", "Electro Titan", "Healer", "Rage Spell", "Heal Spell", "Freeze Spell", "Overgrowth Spell", "Barbarian King", "Archer Queen", "Grand Warden", "Royal Champion", "Giant Gauntlet", "Rage Vial", "Giant Arrow", "Healer Puppet", "Eternal Tome", "Haste Vial", "Seeking Shield", "Spirit Fox", "Phoenix"},
    16: {"Root Rider", "Thrower", "Electro Titan", "Healer", "Rage Spell", "Heal Spell", "Freeze Spell", "Overgrowth Spell", "Barbarian King", "Archer Queen", "Grand Warden", "Royal Champion", "Giant Gauntlet", "Rage Vial", "Giant Arrow", "Healer Puppet", "Eternal Tome", "Haste Vial", "Seeking Shield", "Spirit Fox", "Phoenix"},
    15: {"Super Witch", "Witch", "Balloon", "Lava Hound", "Healer", "Bat Spell", "Freeze Spell", "Rage Spell", "Clone Spell", "Grand Warden", "Archer Queen", "Eternal Tome", "Giant Arrow", "Barbarian King", "Royal Champion", "Diggy", "Phoenix"},
    14: {"Electro Dragon", "Balloon", "Hog Rider", "Miner", "Healer", "Rage Spell", "Freeze Spell", "Lightning Spell", "Grand Warden", "Archer Queen", "Eternal Tome", "Unicorn"},
    13: {"Yeti", "Bowler", "Balloon", "Lava Hound", "Healer", "Rage Spell", "Heal Spell", "Freeze Spell", "Haste Spell", "Archer Queen", "Grand Warden", "Royal Champion", "Barbarian King"},
    12: {"Bowler", "Witch", "Electro Dragon", "Balloon", "Rage Spell", "Heal Spell", "Freeze Spell", "Bat Spell", "Grand Warden", "Archer Queen", "Barbarian King"},
    11: {"Electro Dragon", "Balloon", "Hog Rider", "Miner", "Rage Spell", "Heal Spell", "Freeze Spell", "Grand Warden", "Archer Queen", "Barbarian King"},
    10: {"Golem", "Bowler", "Witch", "Lava Hound", "Balloon", "Rage Spell", "Heal Spell", "Jump Spell", "Haste Spell", "Archer Queen", "Barbarian King"},
    9: {"Golem", "Hog Rider", "Lava Hound", "Balloon", "Heal Spell", "Rage Spell", "Haste Spell", "Poison Spell", "Archer Queen", "Barbarian King"},
}

_META_SUPPORT: set[str] = {
    "Wizard", "Baby Dragon", "Valkyrie", "Wall Breaker", "Super Wall Breaker",
    "Ice Golem", "Headhunter", "Druid", "Super Wizard", "Poison Spell",
    "Invisibility Spell", "Minion", "Diggy", "Frosty", "Unicorn",
}


def json_loads(data: bytes | str) -> Any:
    if orjson is not None:
        return orjson.loads(data)
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return _stdlib_json.loads(data)


def json_dumps(obj: Any) -> str:
    if orjson is not None:
        return orjson.dumps(obj).decode("utf-8")
    return _stdlib_json.dumps(obj, ensure_ascii=False)


# SPEC §11: sanitize player and clan names
def sanitize_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = "".join(
        ch for ch in value
        if (ch.isalnum() or ch in " _-.!'()&") and ord(ch) >= 32
    )
    return " ".join(cleaned.split())[:64]


def validate_tag(raw_tag: str) -> str:
    if not isinstance(raw_tag, str):
        raise ValueError("Tag must be a string.")
    tag = raw_tag.strip().upper()
    if not tag.startswith("#"):
        tag = "#" + tag
    if not TAG_REGEX.match(tag):
        raise ValueError(f"Invalid tag format '{raw_tag}'. Expected ^#[0289CGJLPQRUVY]{{3,12}}$.")
    return tag


def _meta_weight(th: int, name: str) -> float:
    clamped = max(9, min(17, th)) if th else 16
    if name in _META_CORE_BY_TH.get(clamped, set()):
        return 3.0
    if name in _META_SUPPORT:
        return 2.0
    return 1.0


class ProxyError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class CoCProxy:
    """Thread-safe Clash of Clans API proxy for the MCP server."""

    def __init__(
        self,
        keys: list[str] | None = None,
        base_url: str | None = None,
        upstream_rps: float = 8.0,
        upstream_burst: float = 3.0,
        ip_rpm_limit: int = 30,
    ) -> None:
        if keys is None:
            raw_pool = os.environ.get("COC_API_KEYS", "")
            keys = [k.strip() for k in raw_pool.split(",") if k.strip()]
            if not keys:
                single = os.environ.get("COC_API_TOKEN", "").strip()
                if single:
                    keys = [single]
        self._keys = keys
        self._key_idx = 0
        self._key_lock = threading.Lock()

        self._base_url = (base_url or os.environ.get("COC_API_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")

        # SPEC §5 Mode A: upstream 8 RPS token-bucket throttle
        self._rate = upstream_rps
        self._capacity = upstream_burst
        self._tokens = upstream_burst
        self._bucket_updated = time.monotonic()
        self._bucket_lock = threading.Lock()

        # SPEC §5 Mode A: in-memory TTL cache
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_lock = threading.Lock()

        # SPEC §5 Mode A & §11: per-requester-IP 30 req/min limiter
        self._ip_rpm_limit = ip_rpm_limit
        self._ip_windows: dict[str, deque[float]] = {}
        self._ip_lock = threading.Lock()

    def check_ip_rate_limit(self, client_ip: str) -> None:
        now = time.monotonic()
        with self._ip_lock:
            dq = self._ip_windows.setdefault(client_ip, deque())
            while dq and now - dq[0] >= 60.0:
                dq.popleft()
            if len(dq) >= self._ip_rpm_limit:
                raise ProxyError(429, "Rate limit exceeded (30 requests/minute per IP). Retry shortly.")
            dq.append(now)

    def _next_key(self) -> str:
        with self._key_lock:
            if not self._keys:
                raise ProxyError(503, "Server misconfigured: COC_API_KEYS is not set.")
            key = self._keys[self._key_idx % len(self._keys)]
            self._key_idx += 1
            return key

    def _acquire_upstream_token(self) -> None:
        while True:
            with self._bucket_lock:
                now = time.monotonic()
                elapsed = now - self._bucket_updated
                self._bucket_updated = now
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait_for = (1.0 - self._tokens) / self._rate
            time.sleep(wait_for)

    def _http_get(self, url: str, token: str, timeout: float = 15.0) -> tuple[int, bytes]:
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

    def fetch(self, endpoint: str, raw_tag: str) -> Any:
        tag = validate_tag(raw_tag)
        ttl = ENDPOINT_TTLS[endpoint]
        cache_key = f"{endpoint}:{tag}"

        now = time.time()
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached is not None and (now - cached[0]) < ttl:
                return cached[1]

        encoded = urllib.parse.quote(tag, safe="")
        url = f"{self._base_url}{ENDPOINT_PATHS[endpoint].format(tag=encoded)}"

        for attempt in range(3):
            self._acquire_upstream_token()
            token = self._next_key()
            try:
                status, raw_bytes = self._http_get(url, token)
            except Exception as exc:
                raise ProxyError(502, f"Upstream network error: {exc}") from exc

            body: dict[str, Any] = {}
            parsed: Any = None
            if raw_bytes:
                try:
                    parsed = json_loads(raw_bytes)
                    if isinstance(parsed, dict):
                        body = parsed
                except Exception:
                    parsed = None

            if status == 200 and parsed is not None:
                with self._cache_lock:
                    self._cache[cache_key] = (time.time(), parsed)
                return parsed

            if status == 429:
                if attempt < 2:
                    wait = min((2 ** attempt) * 0.5 + random.uniform(0.0, 0.3), 30.0)
                    time.sleep(wait)
                    continue
                raise ProxyError(429, "Upstream Clash of Clans API rate limit exhausted.")

            reason = str(body.get("reason", ""))
            if status == 400:
                raise ProxyError(400, f"Invalid tag request ({reason or 'badRequest'}).")
            if status == 403:
                raise ProxyError(403, f"Access denied ({reason or 'accessDenied'}).")
            if status == 404:
                raise ProxyError(404, f"Tag {tag} not found.")
            if status in (500, 503):
                raise ProxyError(status, "Supercell API temporarily unavailable; retry after 60s.")
            raise ProxyError(status or 502, f"Upstream error HTTP {status}.")

        raise ProxyError(429, "Upstream Clash of Clans API rate limit exhausted.")

    # SPEC §6 normalizer methods
    def _normalize_items(self, items: list[dict[str, Any]], th: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in items:
            lv = int(item.get("level", item.get("lv", 0)) or 0)
            cap = int(item.get("maxLevel", item.get("cap", 0)) or 0)
            # SPEC §6 rule 1: strip maxed items
            if cap <= 0 or lv >= cap:
                continue
            name = sanitize_name(item.get("name", ""))
            if not name:
                continue
            # SPEC §6 rule 3: add deficit
            entry: dict[str, Any] = {"name": name, "lv": lv, "cap": cap, "deficit": cap - lv}
            # SPEC §6 rule 2: drop "village": "home"
            village = item.get("village")
            if village and village != "home":
                entry["village"] = village
            out.append(entry)
        # SPEC §6 rule 4: sort by deficit desc then meta-relevance
        out.sort(key=lambda x: (-x["deficit"], -_meta_weight(th, x["name"]), x["name"]))
        return out

    def get_player(self, tag: str) -> dict[str, Any]:
        raw = self.fetch("player", tag)
        th = int(raw.get("townHallLevel", 0) or 0)

        raw_troops = list(raw.get("troops") or [])
        raw_pets = list(raw.get("pets") or [])
        if not raw_pets and raw_troops:
            kept: list[dict[str, Any]] = []
            for t in raw_troops:
                if t.get("name") in KNOWN_PETS and t.get("village", "home") == "home":
                    raw_pets.append(t)
                else:
                    kept.append(t)
            raw_troops = kept

        heroes: list[dict[str, Any]] = []
        extra_equip: list[dict[str, Any]] = []
        seen_eq: set[str] = set()
        for h in raw.get("heroes") or []:
            lv = int(h.get("level", 0) or 0)
            cap = int(h.get("maxLevel", 0) or 0)
            hname = sanitize_name(h.get("name", ""))
            if not hname or cap <= 0:
                continue
            eq_list = self._normalize_items(list(h.get("equipment") or []), th)
            for eq in eq_list:
                seen_eq.add(eq["name"])
            if lv >= cap:
                extra_equip.extend(eq_list)
                continue
            h_entry: dict[str, Any] = {
                "name": hname,
                "lv": lv,
                "cap": cap,
                "deficit": cap - lv,
                "equip": eq_list,
            }
            if h.get("village") and h["village"] != "home":
                h_entry["village"] = h["village"]
            heroes.append(h_entry)
        heroes.sort(key=lambda x: (-x["deficit"], -_meta_weight(th, x["name"]), x["name"]))

        top_eq = self._normalize_items(list(raw.get("heroEquipment") or []), th)
        merged_eq = list(extra_equip)
        for eq in top_eq:
            if eq["name"] not in seen_eq:
                seen_eq.add(eq["name"])
                merged_eq.append(eq)
        merged_eq.sort(key=lambda x: (-x["deficit"], -_meta_weight(th, x["name"]), x["name"]))

        res: dict[str, Any] = {
            "tag": raw.get("tag", ""),
            "name": sanitize_name(raw.get("name", "")),
            "th": th,
            "trophies": raw.get("trophies", 0),
            "warStars": raw.get("warStars", 0),
            "heroes": heroes,
            "troops": self._normalize_items(raw_troops, th),
            "spells": self._normalize_items(list(raw.get("spells") or []), th),
            "pets": self._normalize_items(raw_pets, th),
        }
        if "townHallWeaponLevel" in raw:
            res["thWeapon"] = raw["townHallWeaponLevel"]
        if "builderHallLevel" in raw:
            res["bh"] = raw["builderHallLevel"]
        if merged_eq:
            res["heroEquipment"] = merged_eq
        return res

    def get_player_battlelog(self, tag: str) -> dict[str, Any]:
        raw = self.fetch("battlelog", tag)
        items = raw.get("items", []) if isinstance(raw, dict) else list(raw)
        battles: list[dict[str, Any]] = []
        for b in items[:25]:
            army = {
                sanitize_name(u.get("name", "")): int(u.get("count", 1) or 1)
                for u in (b.get("army") or [])
                if sanitize_name(u.get("name", ""))
            }
            entry: dict[str, Any] = {
                "battleType": b.get("battleType", "unknown"),
                "attack": bool(b.get("attack", True)),
                "stars": int(b.get("stars", 0) or 0),
                "destructionPercentage": float(b.get("destructionPercentage", 0.0) or 0.0),
            }
            if army:
                entry["armySignature"] = army
            battles.append(entry)
        return {"count": len(battles), "battles": battles}

    def get_clan_summary(self, tag: str) -> dict[str, Any]:
        raw = self.fetch("clan", tag)
        th_dist: dict[str, int] = {}
        for m in raw.get("memberList") or []:
            k = str(m.get("townHallLevel", 0))
            th_dist[k] = th_dist.get(k, 0) + 1
        return {
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
            "thDistribution": dict(sorted(th_dist.items(), key=lambda kv: int(kv[0]), reverse=True)),
        }

    def get_clan_members(self, tag: str) -> dict[str, Any]:
        raw = self.fetch("members", tag)
        items = raw.get("items", []) if isinstance(raw, dict) else list(raw)
        roster: list[dict[str, Any]] = []
        for m in items:
            th = int(m.get("townHallLevel", 0) or 0)
            trophies = int(m.get("trophies", 0) or 0)
            donations = int(m.get("donations", 0) or 0)
            readiness_score = round(th * 10 + min(trophies / 200.0, 30.0) + min(donations / 200.0, 10.0), 1)
            roster.append({
                "tag": m.get("tag", ""),
                "name": sanitize_name(m.get("name", "")),
                "th": th,
                "role": m.get("role", ""),
                "trophies": trophies,
                "donations": donations,
                "readinessScore": readiness_score,
            })
        roster.sort(key=lambda x: (-x["readinessScore"], -x["th"], x["name"]))
        return {"count": len(roster), "members": roster}

    def get_war_board(self, clan_tag: str) -> dict[str, Any]:
        try:
            raw = self.fetch("war", clan_tag)
        except ProxyError as exc:
            if exc.status == 403:
                # SPEC §4: private war log fallback
                summary = self.get_clan_summary(clan_tag)
                roster = self.get_clan_members(clan_tag)
                warlog: list[dict[str, Any]] = []
                try:
                    wl = self.fetch("warlog", clan_tag)
                    warlog = list(wl.get("items") or [])[:10]
                except ProxyError:
                    pass
                return {
                    "privateWarLog": True,
                    "state": "privateWarLog",
                    "clan": summary,
                    "roster": roster,
                    "recentWarLog": warlog,
                }
            raise

        team_size = int(raw.get("teamSize", 0) or 0)
        apm = int(raw.get("attacksPerMember", 2) or 2)
        raw_clan = raw.get("clan") or {}
        raw_opp = raw.get("opponent") or {}

        opp_spread: dict[str, int] = {}
        opp_members: list[dict[str, Any]] = []
        opp_by_tag: dict[str, int] = {}
        for om in raw_opp.get("members") or []:
            oth = int(om.get("townHallLevel", 0) or 0)
            opp_spread[str(oth)] = opp_spread.get(str(oth), 0) + 1
            best = om.get("bestOpponentAttack") or {}
            opp_by_tag[om.get("tag", "")] = oth
            opp_members.append({
                "tag": om.get("tag", ""),
                "name": sanitize_name(om.get("name", "")),
                "th": oth,
                "mapPosition": int(om.get("mapPosition", 0) or 0),
                "bestStars": int(best.get("stars", 0) or 0),
                "bestDestruction": float(best.get("destructionPercentage", 0.0) or 0.0),
            })

        clan_members: list[dict[str, Any]] = []
        stars_list: list[int] = []
        dest_list: list[float] = []
        missed = 0
        mismatches = 0
        for cm in raw_clan.get("members") or []:
            cth = int(cm.get("townHallLevel", 0) or 0)
            atks = cm.get("attacks") or []
            used = len(atks)
            rem = max(0, apm - used)
            missed += rem
            mm = 0
            st_sum = 0
            for a in atks:
                st = int(a.get("stars", 0) or 0)
                ds = float(a.get("destructionPercentage", 0.0) or 0.0)
                st_sum += st
                stars_list.append(st)
                dest_list.append(ds)
                dth = opp_by_tag.get(a.get("defenderTag", ""), cth)
                if cth < dth:
                    mm += 1
            mismatches += mm
            clan_members.append({
                "tag": cm.get("tag", ""),
                "name": sanitize_name(cm.get("name", "")),
                "th": cth,
                "mapPosition": int(cm.get("mapPosition", 0) or 0),
                "attacksUsed": used,
                "attacksRemaining": rem,
                "starsEarned": st_sum,
                "mismatchCount": mm,
            })

        return {
            "state": raw.get("state", "unknown"),
            "teamSize": team_size,
            "attacksPerMember": apm,
            "endTime": raw.get("endTime", ""),
            "clan": {
                "tag": raw_clan.get("tag", ""),
                "name": sanitize_name(raw_clan.get("name", "")),
                "stars": int(raw_clan.get("stars", 0) or 0),
                "destructionPercentage": float(raw_clan.get("destructionPercentage", 0.0) or 0.0),
                "avgStars": round(sum(stars_list) / len(stars_list), 2) if stars_list else 0.0,
                "avgDestruction": round(sum(dest_list) / len(dest_list), 1) if dest_list else 0.0,
                "missedAttacks": missed,
                "thMismatchCount": mismatches,
                "members": clan_members,
            },
            "opponent": {
                "tag": raw_opp.get("tag", ""),
                "name": sanitize_name(raw_opp.get("name", "")),
                "stars": int(raw_opp.get("stars", 0) or 0),
                "destructionPercentage": float(raw_opp.get("destructionPercentage", 0.0) or 0.0),
                "thSpread": dict(sorted(opp_spread.items(), key=lambda kv: int(kv[0]), reverse=True)),
                "members": opp_members,
            },
        }

    def get_cwl_group(self, clan_tag: str) -> dict[str, Any]:
        norm_tag = validate_tag(clan_tag)
        raw = self.fetch("cwl", norm_tag)

        clans: list[dict[str, Any]] = []
        own_avg_th = 0.0
        group_avgs: list[float] = []
        for c in raw.get("clans") or []:
            members = c.get("members") or []
            th_spread: dict[str, int] = {}
            ths: list[int] = []
            for m in members:
                th = int(m.get("townHallLevel", 0) or 0)
                ths.append(th)
                th_spread[str(th)] = th_spread.get(str(th), 0) + 1
            avg_th = round(sum(ths) / len(ths), 2) if ths else 0.0
            if c.get("tag") == norm_tag:
                own_avg_th = avg_th
            elif avg_th:
                group_avgs.append(avg_th)
            clans.append({
                "tag": c.get("tag", ""),
                "name": sanitize_name(c.get("name", "")),
                "clanLevel": int(c.get("clanLevel", 0) or 0),
                "avgTh": avg_th,
                "thSpread": dict(sorted(th_spread.items(), key=lambda kv: int(kv[0]), reverse=True)),
            })

        rounds: list[dict[str, Any]] = []
        for idx, r in enumerate(raw.get("rounds") or [], start=1):
            war_tags = [wt for wt in (r.get("warTags") or []) if wt and wt != "#0"]
            rounds.append({"round": idx, "warTags": war_tags})

        opp_max_avg = max(group_avgs) if group_avgs else own_avg_th
        th_gap = round(opp_max_avg - own_avg_th, 2)
        mismatch_risk = "HIGH" if th_gap >= 1.0 else ("MEDIUM" if th_gap >= 0.4 else "LOW")

        return {
            "state": raw.get("state", "unknown"),
            "season": raw.get("season", ""),
            "mismatchRisk": mismatch_risk,
            "ownAvgTh": own_avg_th,
            "clans": clans,
            "rounds": rounds,
        }
