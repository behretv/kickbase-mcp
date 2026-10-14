# kickbase-mcp

MCP server for [Kickbase](https://www.kickbase.com/) (Bundesliga fantasy
football) built on the unofficial, community-documented
[API v4](https://github.com/kevinskyba/kickbase-api-doc).

It exposes your squad, budget, lineup, the transfer market, player stats,
fixtures and real trading operations — so an AI assistant can build buy/sell
strategies and (if you let it) execute them.

## Install

```bash
uv sync
```

## Credentials

The server needs `KICKBASE_EMAIL` and `KICKBASE_PASSWORD`, resolved in this
order:

1. Environment variables
2. `.env` file (see `.env.example`)

### Proton Pass (`pass-cli`)

Put secret references in `.env`:

```dotenv
KICKBASE_EMAIL="pass://MyVault/Kickbase/username"
KICKBASE_PASSWORD="pass://MyVault/Kickbase/password"
```

then launch the server through `pass-cli run`, which injects the resolved
values as environment variables:

```bash
pass-cli run --env-file .env -- uv run kickbase-mcp
```

## Run

```bash
uv run kickbase-mcp          # stdio transport (default)
```

## MCP client config

With plain `.env` credentials:

```json
{
  "mcpServers": {
    "kickbase": {
      "command": "uv",
      "args": ["--directory", "/path/to/kickbase-mcp", "run", "kickbase-mcp"]
    }
  }
}
```

With Proton Pass injection:

```json
{
  "mcpServers": {
    "kickbase": {
      "command": "pass-cli",
      "args": [
        "run", "--env-file", "/path/to/kickbase-mcp/.env", "--",
        "uv", "--directory", "/path/to/kickbase-mcp", "run", "kickbase-mcp"
      ]
    }
  }
}
```

## Tools

Read:
`list_leagues`, `get_my_status`, `get_league_overview`, `get_league_ranking`,
`get_activity_feed`, `get_my_squad`, `get_my_lineup`, `get_market`,
`get_market_player`, `search_players`, `get_scouted_players`,
`get_player_profile`, `get_player_performance`,
`get_player_market_value_history`, `get_player_transfer_history`,
`get_manager_squad`, `get_manager_transfers`, `get_user_teamcenter`,
`get_fixtures`, `get_competition_table`

Trades (real side effects on your team):
`place_offer`, `withdraw_offer`, `accept_offer`, `decline_offer`,
`list_player_for_sale`, `remove_player_from_market`,
`sell_player_to_kickbase`, `set_lineup`, `scout_player`, `unscout_player`,
`collect_daily_bonus`

Strategy:
`analyze_transfer_market` — one call that combines your budget, squad flags
(injuries, falling value, low averages), every market listing scored by
points-per-million, expiry urgency and next-fixture opponent strength.

## Typical strategy prompt

> Check my budget and squad, find weak players I should sell and undervalued
> players on the market with good upcoming fixtures, then propose concrete
> trades — but ask before executing anything.
