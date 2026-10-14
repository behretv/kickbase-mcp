# Agent notes

Operational knowledge for developing this MCP server. User-facing docs live
in README.md.

## Commands

- Run server locally: `uv run kickbase-mcp` (stdio)
- With Proton Pass creds: `pass-cli run --env-file .env -- uv run kickbase-mcp`
- Lint: `uv run ruff check src/`
- No test suite yet — verify changes with a direct client call, e.g.
  `pass-cli run --env-file .env -- uv run python -c "..."`

## Layout

- `src/kickbase_mcp/client.py` — async API wrapper (auth, endpoints)
- `src/kickbase_mcp/server.py` — FastMCP tools
- `src/kickbase_mcp/config.py` — credential resolution
  (env vars → `.env` via dotenv; `pass://` refs must be injected by
  `pass-cli run` at launch)

Personal automation (data collection, models, timers) lives in the sibling
repo `../kickbase-agent` — not here.

## API gotchas (learned the hard way)

- **pass-cli injects at spawn.** Changing a Proton Pass entry does nothing to
  already-running processes — respawn the server after credential updates.
  The local pass-cli cache can also serve a stale value briefly.
- **API fields are cryptic single letters.** Known decodes: `mppu`=squad
  size, `mpst`=max players per Bundesliga club, `b`=budget, `iotm`=on
  transfer market, `mvgl`=MV gain/loss vs purchase, `sdmvt`=matchday MV
  delta, `tfhmvt`=24h MV delta, `tty`=1 buy/2 sell in transfers. `amd` in
  league settings appears to be the auto-sell-matchday-MVP rule.
- **`player_market_value` only returns data for timeframe=365** — smaller
  windows return empty `it`. Entries are `{dt: days-since-epoch, mv}` with
  `mv: 0` backfilled before the player entered the pool.
- **`player_performance` includes future matchdays** — entries have
  `p: null`/`mp: null` for unplayed days; always filter by date.
- **Player search** (`/v4/competitions/{id}/players/search`) is substring
  match, max 50/page; empty query returns only the first 50 — sweep a–z for
  the full pool (~465 players).
- **Feed types** (`activitiesFeed`): `t:3` = Kickbase lists a player,
  `t:15` = transfer (`byr`/`slr`, `trp`), `t:17` = matchday placement,
  `t:22` = daily login bonus (`bn`, `day` streak), `t:26` = achievement
  badge, `t:32` = auto-sold matchday MVP (`trp` = market value, `rsn:1`).
- **Admin settings endpoint is admin-only** — league rules must be inferred
  from overview flags + observed feed behavior.
- **Trades are real.** `place_offer`, `accept_offer`,
  `list_player_for_sale`, `remove_player_from_market`,
  `sell_player_to_kickbase`, `set_lineup` mutate the user's actual team —
  always confirm before calling.
