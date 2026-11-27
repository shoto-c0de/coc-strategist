---
name: coc-strategist
description: >-
  Fetch live player, clan, and war data from the official Clash of Clans API;
  build data-backed upgrade roadmaps, war strategies, and CWL rotation plans;
  and analyze base or village screenshots to recommend attack plans, troop
  compositions, spell timing, and hero equipment loadouts. Activate whenever a
  user shares a #TAG, asks about CoC upgrade or war strategy, or attaches a
  base/village screenshot.
license: MIT
compatibility: >-
  Requires Python 3.10+ with httpx (or the hosted coc-strategist MCP server
  as a zero-setup alternative). Multimodal image input required for base
  screenshot analysis.
metadata:
  version: "2.0.0"
  author: "<your-name>"
  api: "https://api.clashofclans.com/v1"
---

# CoC Strategist

Deliver live Clash of Clans upgrade roadmaps, war strategy analysis, CWL rotation guidance, and multimodal base attack plans by fusing normalized API data with screenshot inspection.

## When to Activate

- User shares a Clash of Clans player or clan `#TAG`.
- User asks about CoC upgrade priority, lab/builder queues, war readiness, CWL strategy, or target selection.
- User attaches a screenshot of an enemy war base or their own village.

## Data Plane Selection

If an MCP server named `coc-strategist` is connected, prefer its 6 tools:

- `coc_get_player`
- `coc_get_player_battlelog`
- `coc_get_clan_summary`
- `coc_get_clan_members`
- `coc_get_war_board`
- `coc_get_cwl_group`

Otherwise, run `scripts/coc_client.py` inside this skill directory. If no `coc-strategist` MCP server is connected and `COC_API_TOKEN` is unset, instruct the user to either connect the hosted MCP URL (`https://coc-mcp.yourhost.dev/mcp`) or set the local Mode B environment variables:

```text
Environment:
  COC_API_TOKEN=eyJ...     # Required
  COC_API_BASE_URL=...     # Optional (default: https://api.clashofclans.com/v1)
```

## Script Usage

### `coc_client.py`

Usage: `coc_client.py <command> [options]`

Run with `--help` first; treat as a black box.

| Exit Code | Meaning |
| :--- | :--- |
| `0` | Success |
| `1` | Invalid tag format |
| `2` | Network / timeout error |
| `3` | 403 — IP mismatch (prints detected IP) |
| `4` | 404 — Tag not found |
| `5` | 429 — Rate limited (retries exhausted) |
| `10` | Private war log (fallback data printed to stdout) |

### `upgrade_calc.py`

Usage: `upgrade_calc.py [options]`

Run with `--help` first; treat as a black box.

### `war_analyzer.py`

Usage: `war_analyzer.py [options]`

Run with `--help` first; treat as a black box.

## Screenshot Analysis

When an image is attached, classify it first as **enemy war base** or **own village**. Then load `references/vision-rubric.md` and follow the Fusion Gate Safety Rule verbatim:

> **Never recommend a troop, spell, siege, or equipment that the attacker has not unlocked or is currently upgrading.** Every visual recommendation must be cross-validated against `GET /players/{attacker_tag}`. If the user has not provided their `#TAG`, the output must include: *"⚠️ This army comp assumes max TH{X} troops. Share your #TAG so I can verify your actual levels."*

## Strategy References

- Load `references/th-meta.md` when the player's Town Hall level is known.
- Load `references/normalizer-schema.md` when interpreting compact tactical JSON.
- Load `assets/output-templates.md` before writing any Upgrade Report or Attack Plan.

## Error Handling

| Status | Reason | What to Tell the User |
| :--- | :--- | :--- |
| `400` | `badRequest` | The tag format is invalid; ask the user to verify the `#TAG`. |
| `403` | `accessDenied` | The clan war log is private; present fallback roster and war log data. |
| `403` | `accessDenied.invalidIp` | Report the detected egress IP and advise whitelisting it at `developer.clashofclans.com` or switching to the hosted MCP server. |
| `404` | `notFound` | The player or clan tag was not found; ask the user to double-check it. |
| `429` | `requestThrottled` | API rate limit hit after retries; advise waiting ~30 seconds before retrying. |
| `500`/`503` | `internalServerError`/`serviceUnavailable` | Supercell API is under maintenance or unavailable; advise retrying after 60 seconds. |

## Security Rules

- Never echo `COC_API_TOKEN`, keys, or auth headers in responses or logs.
- Validate every tag against `^#[0289CGJLPQRUVY]{3,12}$` before running queries.
- Never store persistent player data outside transient execution.
- Sanitize player and clan names to alphanumeric and limited Unicode before rendering.
- Pass structured JSON only between scripts and analysis steps rather than raw unparsed text.
