# Compact Tactical JSON Normalizer Schema

Raw `/players/{tag}` payloads are 15–50 KB. The normalizer compresses responses to ~1.5 KB of tactical JSON for deterministic scripts and low-token reasoning.

## Normalizer Rules

1. **Strip maxed items** — If `level == maxLevel` for a troop/spell/hero/equipment/pet, omit it entirely.
2. **Collapse village field** — Remove `"village": "home"` (redundant for 99% of queries; Builder Base items are tagged separately).
3. **Compute deltas** — Add a `deficit` field: `maxLevel - level` for every non-maxed item.
4. **Rank by priority** — Sort non-maxed items by `deficit` descending, then by meta-relevance tag.
5. **Aggregate war metrics** — Replace per-attack arrays with computed averages: `avgStars`, `avgDestruction`, `missedAttacks`, `thMismatchCount`.
6. **Output token estimate** — Target ≤ 400 tokens for a typical TH15–TH17 player with 10–15 non-maxed items.

## Compact Tactical JSON Example

```json
{
  "tag": "#2PP",
  "name": "Warrior",
  "th": 16,
  "thWeapon": 4,
  "bh": 10,
  "trophies": 5800,
  "warStars": 1247,
  "heroes": [
    {"name": "Barbarian King", "lv": 90, "cap": 95, "deficit": 5,
     "equip": [
       {"name": "Giant Gauntlet", "lv": 22, "cap": 27, "deficit": 5},
       {"name": "Rage Vial", "lv": 12, "cap": 18, "deficit": 6}
     ]},
    {"name": "Grand Warden", "lv": 70, "cap": 70, "equip": []}
  ],
  "troops": [
    {"name": "Root Rider", "lv": 2, "cap": 3, "deficit": 1},
    {"name": "Electro Titan", "lv": 2, "cap": 3, "deficit": 1},
    {"name": "Thrower", "lv": 1, "cap": 2, "deficit": 1}
  ],
  "spells": [
    {"name": "Overgrowth Spell", "lv": 2, "cap": 4, "deficit": 2}
  ],
  "pets": [
    {"name": "Spirit Fox", "lv": 8, "cap": 10, "deficit": 2}
  ],
  "warReadiness": {
    "avgStars": 2.1,
    "avgDestruction": 78.4,
    "missedAttacks": 2,
    "last10Wars": "7W-3L"
  }
}
```

## Field-by-Field Annotation

| Field | Type | Description |
| :--- | :--- | :--- |
| `tag` | `string` | Validated Clash of Clans tag (`#...`). |
| `name` | `string` | Sanitized player name (control/injection characters stripped). |
| `th` | `int` | Home Village Town Hall level (`townHallLevel`). |
| `thWeapon` | `int` | Town Hall Giga weapon level (`townHallWeaponLevel`, if present). |
| `bh` | `int` | Builder Hall level (`builderHallLevel`, if present). |
| `trophies` | `int` | Current Home Village trophy count. |
| `warStars` | `int` | Career Clan War stars earned. |
| `heroes[]` | `array` | Non-maxed heroes with `{name, lv, cap, deficit, equip[]}`. Maxed heroes are stripped; any non-maxed equipment on a maxed hero moves to `heroEquipment[]`. |
| `heroes[].equip[]` | `array` | Non-maxed hero equipment with `{name, lv, cap, deficit}`. |
| `heroEquipment[]` | `array` | Optional array of additional non-maxed equipment items not nested under an unmaxed hero. |
| `troops[]` | `array` | Non-maxed troops sorted by `deficit` desc, then TH meta weight. `"village": "home"` is omitted; Builder Base items retain `"village": "builderBase"`. |
| `spells[]` | `array` | Non-maxed spells sorted by `deficit` desc, then TH meta weight. |
| `pets[]` | `array` | Non-maxed Hero Pets sorted by `deficit` desc, then TH meta weight. |
| `warReadiness` | `object` | Optional aggregated war metrics: `avgStars`, `avgDestruction`, `missedAttacks`, `thMismatchCount` / `last10Wars`. |
