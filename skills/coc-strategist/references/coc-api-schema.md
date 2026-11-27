# Official Clash of Clans API Reference

Base URL: `https://api.clashofclans.com/v1`

## Authentication & Tag Encoding

- Register an account and generate a JWT API token at `https://developer.clashofclans.com`.
- Each JWT token is locked to one or more **static public IPv4 addresses**.
- Include these headers on every HTTP request:
  - `Authorization: Bearer <JWT_TOKEN>`
  - `Accept: application/json`
- Validate player and clan tags against `^#[0289CGJLPQRUVY]{3,12}$` before calling any endpoint.
- URL-encode `#` as `%23` in path parameters (for example, `#2PP` becomes `%232PP`).

## Endpoint Reference

| Use Case | Method & Path | Example Request | Key Response Fields | TTL Cache |
| :--- | :--- | :--- | :--- | :--- |
| **Player Profile & Upgrades** | `GET /players/{playerTag}` | `GET /v1/players/%232PP` | `townHallLevel`, `townHallWeaponLevel`, `builderHallLevel`, `heroes[].{name,level,maxLevel,equipment[]}`, `heroEquipment[].{name,level,maxLevel}`, `troops[].{name,level,maxLevel}`, `spells[]`, `pets[]`, `warStars`, `attackWins`, `defenseWins`, `donations` | 5 min |
| **Battle Log** | `GET /players/{playerTag}/battlelog` | `GET /v1/players/%232PP/battlelog` | Recent attacks/defenses — army composition used, stars, destruction % | 2 min |
| **Token Verification** | `POST /players/{playerTag}/verifytoken` | `POST /v1/players/%232PP/verifytoken` | Ownership verification for secure features | — |
| **Clan Info** | `GET /clans/{clanTag}` | `GET /v1/clans/%232PP` | `clanLevel`, `warWinStreak`, `warWins`, `warLosses`, `warTies`, `members`, `requiredTrophies`, `badgeUrls` | 5 min |
| **Clan Members** | `GET /clans/{clanTag}/members` | `GET /v1/clans/%232PP/members` | Per-member `townHallLevel`, `role`, `donations`, `trophies` | 5 min |
| **Clan War Log** | `GET /clans/{clanTag}/warlog` | `GET /v1/clans/%232PP/warlog` | Historical war results — `result`, `teamSize`, `opponent`, destruction % | 10 min |
| **Current War** | `GET /clans/{clanTag}/currentwar` | `GET /v1/clans/%232PP/currentwar` | `state` (preparation/inWar/warEnded), `members[].attacks[]`, `opponent.members[]`, star counts | 2 min |
| **CWL League Group** | `GET /clans/{clanTag}/currentwar/leaguegroup` | `GET /v1/clans/%232PP/currentwar/leaguegroup` | CWL group clans, rounds, war tags | 5 min |
| **CWL Individual War** | `GET /clanwarleagues/wars/{warTag}` | `GET /v1/clanwarleagues/wars/%238Q2J9` | Per-round detailed war data | 2 min |

## Rate Limits & Throttling

| Constraint | Value | Mitigation |
| :--- | :--- | :--- |
| **Requests per second (per token/IP)** | ~10 RPS (community-observed, not officially documented) | Client-side token-bucket throttle at 8 RPS with burst of 3. |
| **429 Too Many Requests** | Temporary block ~30 seconds; extends if hammered. | Exponential backoff with jitter: `wait = min(2^attempt * 500ms + rand(0,300)ms, 30s)`. |
| **Pagination** | `after` cursor + `limit` (default 20, max varies). | Always follow `paging.cursors.after`; never hardcode offsets. |

## Error Codes & Handling

| HTTP Status | `reason` Field | Skill Behavior |
| :--- | :--- | :--- |
| `200` | — | Parse and normalize response. |
| `400` | `badRequest` | Invalid tag format → prompt user to re-check. |
| `403` | `accessDenied` | Private war log → graceful fallback to clan roster + warlog. |
| `403` | `accessDenied.invalidIp` | IP mismatch → print reported IP, suggest whitelist or switch to hosted MCP. |
| `404` | `notFound` | Tag doesn't exist → ask user to verify tag. |
| `429` | `requestThrottled` | Backoff + retry (max 3 attempts). |
| `500`/`503` | `internalServerError`/`serviceUnavailable` | Supercell maintenance → inform user, retry after 60s. |
