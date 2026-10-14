"""Kickbase MCP server — tools for squad, market, fixtures and trading."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastmcp import FastMCP

from .client import KickbaseClient, KickbaseError, position_name, status_name
from .config import Settings, load_settings

mcp = FastMCP(
    "kickbase",
    instructions=(
        "Tools for the Kickbase fantasy football game: inspect your squad, "
        "budget, lineup and the transfer market, analyze players and fixtures, "
        "and execute trades (offers, sales, lineup changes). "
        "Tools that trade execute real transactions on the user's team."
    ),
)

_settings: Settings | None = None
_client: KickbaseClient | None = None


def _get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def _get_client() -> KickbaseClient:
    global _client
    if _client is None:
        s = _get_settings()
        _client = KickbaseClient(s.email, s.password)
    return _client


async def _league(league_id: str | None) -> str:
    if league_id:
        return league_id
    s = _get_settings()
    if s.league_id:
        return s.league_id
    return await _get_client().league_id(None)


# ---------------------------------------------------------------------------
# helpers: decode kickbase's abbreviated field names into readable dicts
# ---------------------------------------------------------------------------


def _fmt_money(v: float | None) -> int | None:
    return int(v) if isinstance(v, (int, float)) else None


def _expiry_hours(exs: float | None) -> float | None:
    """exs is either a seconds-until-expiry duration or an epoch timestamp."""
    if not isinstance(exs, (int, float)) or exs <= 0:
        return None
    if exs > 1_000_000:  # epoch timestamp
        remaining = (exs - datetime.now(UTC).timestamp()) / 3600
        return round(remaining, 1)
    return round(exs / 3600, 1)


def _player(p: dict[str, Any]) -> dict[str, Any]:
    """Decode a player entry from squad/market/lineup responses."""
    return {
        "id": str(p.get("i", "")),
        "name": p.get("n"),
        "firstName": p.get("fn"),
        "teamId": str(p.get("tid", "")),
        "position": position_name(p.get("pos")),
        "status": status_name(p.get("st")),
        "marketValue": _fmt_money(p.get("mv")),
        "marketValueTrend": p.get("mvt"),
        "marketValueTrend24h": p.get("tfhmvt"),
        "marketValueTrendMatchday": p.get("sdmvt"),
        "totalPoints": p.get("p"),
        "averagePoints": p.get("ap"),
        "price": _fmt_money(p.get("prc")),
        "expirySeconds": p.get("exs"),
        "expiresInHours": _expiry_hours(p.get("exs")),
        "offerCount": p.get("ofc"),
        "sellerUserId": p.get("uoid"),
        "onTransferMarket": p.get("iotm"),
        "listedDate": p.get("dt"),
        "number": p.get("nbr") or p.get("nb"),
        "lineupOrder": p.get("lo"),
        "raw": p,
    }


def _players(j: dict[str, Any] | list) -> list[dict[str, Any]]:
    items = j.get("it", []) if isinstance(j, dict) else j
    return [_player(p) for p in items]


def _team_names(table: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """teamId -> {name, position, points, goalDiff} from competition table."""
    j = table.get("value", table)
    out: dict[str, dict[str, Any]] = {}
    for row in j.get("it", []):
        out[str(row.get("tid"))] = {
            "name": row.get("tn"),
            "leaguePosition": row.get("cp"),
            "leaguePoints": row.get("sp"),
            "goalDiff": row.get("gd"),
        }
    return out


def _next_fixtures(
    matchdays: dict[str, Any], current_day: int, n_days: int = 3
) -> dict[str, list[dict[str, Any]]]:
    """teamId -> list of upcoming fixtures (opponent, home/away, day, date)."""
    j = matchdays.get("value", matchdays)
    per_team: dict[str, list[dict[str, Any]]] = {}
    for md in j.get("it", []):
        day = md.get("day")
        if not isinstance(day, int) or day < current_day or day >= current_day + n_days:
            continue
        for m in md.get("it", []):
            for side, opp_side, home in (("t1", "t2", True), ("t2", "t1", False)):
                tid = str(m.get(side, ""))
                per_team.setdefault(tid, []).append(
                    {
                        "day": m.get("day", day),
                        "date": m.get("dt"),
                        "home": home,
                        "opponentId": str(m.get(opp_side, "")),
                        "opponent": m.get(f"{opp_side}sy"),
                    }
                )
    for fixtures in per_team.values():
        fixtures.sort(key=lambda f: f["day"])
    return per_team


# ---------------------------------------------------------------------------
# account / league tools
# ---------------------------------------------------------------------------


@mcp.tool
async def list_leagues() -> list[dict[str, Any]]:
    """List all Kickbase leagues the account is in (id, name, budget, users)."""
    leagues = await _get_client().list_leagues()
    return [
        {
            "id": str(lg.get("i")),
            "name": lg.get("n"),
            "competitionId": str(lg.get("cpi", "")),
            "budget": lg.get("b"),
            "teamValue": lg.get("tv"),
            "admin": lg.get("adm"),
            "raw": lg,
        }
        for lg in leagues
    ]


@mcp.tool
async def get_my_status(league_id: str | None = None) -> dict[str, Any]:
    """Get your status in a league: budget, team value, points and placement."""
    lid = await _league(league_id)
    client = _get_client()
    me, budget = await asyncio.gather(client.league_me(lid), client.league_budget(lid))
    return {
        "leagueId": lid,
        "leagueName": me.get("lnm"),
        "competitionId": str(me.get("cpi", "")),
        "budget": budget.get("b", me.get("b")),
        "budgetDelta": budget.get("pbas"),
        "userName": me.get("un"),
        "rawMe": me,
        "rawBudget": budget,
    }


@mcp.tool
async def get_league_overview(league_id: str | None = None) -> dict[str, Any]:
    """League overview: name, competition, members and settings."""
    lid = await _league(league_id)
    j = await _get_client().league_overview(lid)
    return {
        "id": str(j.get("i", lid)),
        "name": j.get("lnm"),
        "competitionId": str(j.get("cpi", "")),
        "competitionName": j.get("cpn"),
        "creationDate": j.get("dt"),
        "managers": [
            {"id": str(u.get("i")), "name": u.get("n")} for u in j.get("us", [])
        ],
        "raw": j,
    }


@mcp.tool
async def get_league_ranking(
    league_id: str | None = None, day: int | None = None
) -> dict[str, Any]:
    """League table of managers (season points, matchday points, team values)."""
    lid = await _league(league_id)
    j = await _get_client().league_ranking(lid, day)
    users = [
        {
            "userId": str(u.get("i")),
            "name": u.get("n"),
            "seasonPoints": u.get("sp"),
            "matchDayPoints": u.get("mdp"),
            "seasonPlacement": u.get("spl"),
            "matchDayPlacement": u.get("mdpl"),
            "teamValue": u.get("tv"),
            "admin": u.get("adm"),
        }
        for u in j.get("us", [])
    ]
    users.sort(key=lambda u: u["seasonPlacement"] or 999)
    return {"day": j.get("day"), "managers": users, "raw": j}


@mcp.tool
async def get_activity_feed(
    league_id: str | None = None, start: int = 0, max_items: int = 20
) -> Any:
    """League activity feed (transfers, market events, comments)."""
    lid = await _league(league_id)
    return await _get_client().activity_feed(lid, start, max_items)


# ---------------------------------------------------------------------------
# squad tools
# ---------------------------------------------------------------------------


@mcp.tool
async def get_my_squad(league_id: str | None = None) -> list[dict[str, Any]]:
    """Your full squad with market value, trend, points, status and position."""
    lid = await _league(league_id)
    j = await _get_client().squad(lid)
    return _players(j)


@mcp.tool
async def get_my_lineup(league_id: str | None = None) -> list[dict[str, Any]]:
    """Your current starting eleven and bench players."""
    lid = await _league(league_id)
    j = await _get_client().lineup(lid)
    return _players(j)


@mcp.tool
async def set_lineup(
    player_ids: list[str],
    formation: str = "1",
    league_id: str | None = None,
) -> Any:
    """Set the starting eleven. REAL CHANGE to your team.

    player_ids: exactly 11 player ids in lineup order.
    formation: kickbase formation type code (use the current value from
    get_my_lineup context or the app; '1' is a common default).
    """
    lid = await _league(league_id)
    if len(player_ids) != 11:
        raise KickbaseError("Lineup requires exactly 11 player ids")
    return await _get_client().set_lineup(lid, formation, player_ids)


# ---------------------------------------------------------------------------
# market tools (read)
# ---------------------------------------------------------------------------


@mcp.tool
async def get_market(league_id: str | None = None) -> dict[str, Any]:
    """Players currently on the transfer market with price, expiry and offers.

    sellerUserId is null for players listed by Kickbase itself (buy instantly
    at the listed price via place_offer) and set for manager listings.
    """
    lid = await _league(league_id)
    j = await _get_client().market(lid)
    return {
        "day": j.get("day"),
        "teamValue": j.get("tv"),
        "marketValueUpdateDate": j.get("mvud"),
        "players": _players(j),
    }


@mcp.tool
async def get_market_player(
    player_id: str, league_id: str | None = None
) -> dict[str, Any]:
    """Details of one market player including all offers made so far."""
    lid = await _league(league_id)
    j = await _get_client().market_player(lid, player_id)
    offers = [
        {
            "id": str(o.get("i", "")),
            "price": o.get("prc"),
            "userId": str(o.get("uoid", "")),
            "userName": o.get("unm"),
            "date": o.get("dt"),
            "validUntil": o.get("exp"),
            "raw": o,
        }
        for o in j.get("ofs", j.get("it", []))
        if isinstance(o, dict)
    ]
    return {"player": _player(j), "offers": offers, "raw": j}


@mcp.tool
async def search_players(
    query: str,
    league_id: str | None = None,
    max_items: int = 20,
) -> Any:
    """Search for any Bundesliga player by name (not only market listings)."""
    lid = await _league(league_id)
    client = _get_client()
    cid = await client.competition_id(lid)
    return await client.search_players(cid, lid, query, max_items)


@mcp.tool
async def get_scouted_players(league_id: str | None = None) -> Any:
    """Your watchlist / scouted players."""
    lid = await _league(league_id)
    return await _get_client().scouted_players(lid)


# ---------------------------------------------------------------------------
# player info tools
# ---------------------------------------------------------------------------


@mcp.tool
async def get_player_profile(
    player_id: str, league_id: str | None = None
) -> dict[str, Any]:
    """Full player profile: stats, market value, status and club info."""
    lid = await _league(league_id)
    j = await _get_client().player(lid, player_id)
    return {"player": _player(j) if isinstance(j, dict) else j, "raw": j}


@mcp.tool
async def get_player_performance(player_id: str, league_id: str | None = None) -> Any:
    """Matchday-by-matchday points history for a player."""
    lid = await _league(league_id)
    j = await _get_client().player_performance(lid, player_id)
    out = []
    for entry in j.get("it", []):
        hist = [
            {
                "day": h.get("day"),
                "points": h.get("p"),
                "opponent1": h.get("t1"),
                "opponent2": h.get("t2"),
                "goals": (h.get("t1g"), h.get("t2g")),
                "status": status_name(h.get("st")),
                "current": h.get("cur"),
                "raw": h,
            }
            for h in entry.get("ph", [])
        ]
        out.append(
            {"teamId": entry.get("ti"), "teamName": entry.get("n"), "history": hist}
        )
    return out


@mcp.tool
async def get_player_market_value_history(
    player_id: str,
    timeframe: int = 30,
    league_id: str | None = None,
) -> Any:
    """Market value history for a player. timeframe = days back to look."""
    lid = await _league(league_id)
    return await _get_client().player_market_value(lid, player_id, timeframe)


@mcp.tool
async def get_player_transfer_history(
    player_id: str,
    league_id: str | None = None,
    start: int = 0,
) -> Any:
    """Transfer history: who bought/sold this player and at which price."""
    lid = await _league(league_id)
    return await _get_client().player_transfer_history(lid, player_id, start)


# ---------------------------------------------------------------------------
# managers / other users
# ---------------------------------------------------------------------------


@mcp.tool
async def get_manager_squad(
    user_id: str, league_id: str | None = None
) -> list[dict[str, Any]]:
    """Another manager's squad. Get user ids from get_league_ranking."""
    lid = await _league(league_id)
    j = await _get_client().manager_squad(lid, user_id)
    return _players(j)


@mcp.tool
async def get_manager_transfers(
    user_id: str, league_id: str | None = None, start: int = 0
) -> Any:
    """A manager's recent buy/sell transactions."""
    lid = await _league(league_id)
    return await _get_client().manager_transfers(lid, user_id, start)


@mcp.tool
async def get_user_teamcenter(
    user_id: str, league_id: str | None = None, day: int | None = None
) -> Any:
    """Team center of a user (points per player for a matchday)."""
    lid = await _league(league_id)
    return await _get_client().user_teamcenter(lid, user_id, day)


# ---------------------------------------------------------------------------
# competition / fixtures
# ---------------------------------------------------------------------------


@mcp.tool
async def get_fixtures(
    league_id: str | None = None, day: int | None = None
) -> dict[str, Any]:
    """Bundesliga fixtures grouped by matchday (all or a specific day)."""
    lid = await _league(league_id)
    client = _get_client()
    cid = await client.competition_id(lid)
    j = await client.matchdays(cid)
    v = j.get("value", j)
    matchdays = []
    for md in v.get("it", []):
        if day and md.get("day") != day:
            continue
        matchdays.append(
            {
                "day": md.get("day"),
                "matches": [
                    {
                        "id": str(m.get("mi", "")),
                        "date": m.get("dt"),
                        "home": m.get("t1sy") or str(m.get("t1")),
                        "away": m.get("t2sy") or str(m.get("t2")),
                        "homeTeamId": str(m.get("t1", "")),
                        "awayTeamId": str(m.get("t2", "")),
                        "result": (m.get("t1g"), m.get("t2g")),
                        "live": m.get("il"),
                        "raw": m,
                    }
                    for m in md.get("it", [])
                ],
            }
        )
    return {"competitionId": cid, "currentDay": v.get("day"), "matchdays": matchdays}


@mcp.tool
async def get_competition_table(league_id: str | None = None) -> list[dict[str, Any]]:
    """Real Bundesliga table: team strength for fixture difficulty analysis."""
    lid = await _league(league_id)
    client = _get_client()
    cid = await client.competition_id(lid)
    j = await client.competition_table(cid)
    rows = _team_names(j)
    return [{"teamId": tid, **info} for tid, info in rows.items()]


# ---------------------------------------------------------------------------
# trade tools (REAL side effects)
# ---------------------------------------------------------------------------


@mcp.tool
async def place_offer(
    player_id: str,
    price: int,
    league_id: str | None = None,
) -> Any:
    """Place an offer on a market player. REAL TRANSACTION.

    For Kickbase-listed players (sellerUserId null), offering the listed price
    buys the player instantly if your budget covers it. For manager listings
    the offer goes to the manager for accept/decline.
    """
    lid = await _league(league_id)
    return await _get_client().place_offer(lid, player_id, price)


@mcp.tool
async def withdraw_offer(
    player_id: str,
    offer_id: str,
    league_id: str | None = None,
) -> Any:
    """Withdraw your own pending offer on a market player."""
    lid = await _league(league_id)
    return await _get_client().withdraw_offer(lid, player_id, offer_id)


@mcp.tool
async def accept_offer(
    player_id: str,
    offer_id: str,
    league_id: str | None = None,
) -> Any:
    """Accept a manager's offer on one of your listed players. REAL SALE."""
    lid = await _league(league_id)
    return await _get_client().accept_offer(lid, player_id, offer_id)


@mcp.tool
async def decline_offer(
    player_id: str,
    offer_id: str,
    league_id: str | None = None,
) -> Any:
    """Decline a manager's offer on one of your listed players."""
    lid = await _league(league_id)
    return await _get_client().decline_offer(lid, player_id, offer_id)


@mcp.tool
async def list_player_for_sale(
    player_id: str,
    price: int,
    league_id: str | None = None,
) -> Any:
    """Put one of your squad players on the transfer market at an asking price."""
    lid = await _league(league_id)
    return await _get_client().list_for_sale(lid, player_id, price)


@mcp.tool
async def remove_player_from_market(
    player_id: str,
    league_id: str | None = None,
) -> Any:
    """Take your listed player off the transfer market (cancel the listing)."""
    lid = await _league(league_id)
    return await _get_client().remove_from_market(lid, player_id)


@mcp.tool
async def sell_player_to_kickbase(
    player_id: str,
    league_id: str | None = None,
) -> Any:
    """Accept Kickbase's system offer on a listed player: instant sale. REAL SALE."""
    lid = await _league(league_id)
    return await _get_client().sell_to_kickbase(lid, player_id)


@mcp.tool
async def scout_player(player_id: str, league_id: str | None = None) -> Any:
    """Add a player to your watchlist."""
    lid = await _league(league_id)
    return await _get_client().scout_player(lid, player_id)


@mcp.tool
async def unscout_player(player_id: str, league_id: str | None = None) -> Any:
    """Remove a player from your watchlist."""
    lid = await _league(league_id)
    return await _get_client().unscout_player(lid, player_id)


@mcp.tool
async def collect_daily_bonus() -> Any:
    """Collect the daily login bonus if available."""
    return await _get_client().collect_bonus()


# ---------------------------------------------------------------------------
# strategy
# ---------------------------------------------------------------------------


@mcp.tool
async def analyze_transfer_market(
    league_id: str | None = None,
    horizon_matchdays: int = 3,
) -> dict[str, Any]:
    """Composite analysis for buy/sell strategy.

    Returns your budget, squad valuation flags, and every market listing
    scored by points-per-million, market-value trend, expiry urgency and
    upcoming opponent strength (next N matchdays). Use this to decide which
    players to sell and which market bargains to buy.
    """
    lid = await _league(league_id)
    client = _get_client()
    cid = await client.competition_id(lid)
    me, budget, squad, market, matchdays, table = await asyncio.gather(
        client.league_me(lid),
        client.league_budget(lid),
        client.squad(lid),
        client.market(lid),
        client.matchdays(cid),
        client.competition_table(cid),
    )
    teams = _team_names(table)
    current_day = market.get("day") or matchdays.get("value", matchdays).get("day") or 1
    fixtures = _next_fixtures(matchdays, current_day, horizon_matchdays)

    def _fixture_note(tid: str) -> dict[str, Any]:
        team = teams.get(tid, {})
        upcoming = fixtures.get(tid, [])
        strength = []
        for f in upcoming:
            opp = teams.get(f["opponentId"], {})
            strength.append(
                {
                    **f,
                    "opponentName": opp.get("name") or f["opponent"],
                    "opponentPosition": opp.get("leaguePosition"),
                }
            )
        return {"team": team.get("name"), "nextFixtures": strength}

    squad_analysis = []
    for p in _players(squad):
        flags = []
        if p["status"] not in ("fit", "unknown(0)"):
            flags.append(f"status:{p['status']}")
        if p["onTransferMarket"]:
            flags.append("already_listed")
        if isinstance(p["averagePoints"], (int, float)) and p["averagePoints"] < 60:
            flags.append("low_avg_points")
        if (
            isinstance(p["marketValueTrend"], (int, float))
            and p["marketValueTrend"] < 0
        ):
            flags.append("falling_value")
        squad_analysis.append(
            {
                "id": p["id"],
                "name": p["name"],
                "position": p["position"],
                "marketValue": p["marketValue"],
                "marketValueTrend": p["marketValueTrend"],
                "averagePoints": p["averagePoints"],
                "totalPoints": p["totalPoints"],
                "offerCount": p["offerCount"],
                "flags": flags,
                **_fixture_note(p["teamId"]),
            }
        )

    market_analysis = []
    for p in _players(market):
        price = p["price"] or p["marketValue"]
        ppm = (
            round(p["averagePoints"] / (price / 1_000_000), 2)
            if price and p["averagePoints"]
            else None
        )
        expiry_h = _expiry_hours(p["expirySeconds"])
        market_analysis.append(
            {
                "id": p["id"],
                "name": f"{p.get('firstName') or ''} {p['name'] or ''}".strip(),
                "position": p["position"],
                "status": p["status"],
                "price": price,
                "marketValue": p["marketValue"],
                "marketValueTrend": p["marketValueTrend"],
                "averagePoints": p["averagePoints"],
                "totalPoints": p["totalPoints"],
                "pointsPerMillion": ppm,
                "offerCount": p["offerCount"],
                "expiresInHours": expiry_h,
                "seller": "kickbase" if not p["sellerUserId"] else "manager",
                "sellerUserId": p["sellerUserId"],
                **_fixture_note(p["teamId"]),
            }
        )
    market_analysis.sort(key=lambda x: x["pointsPerMillion"] or 0, reverse=True)

    available = budget.get("b", me.get("b"))
    hints = []
    expiring = [m for m in market_analysis if (m["expiresInHours"] or 999) < 6]
    if expiring:
        hints.append(
            f"{len(expiring)} listing(s) expire within 6h: "
            f"{[m['name'] for m in expiring]}"
        )
    injured = [
        s["name"]
        for s in squad_analysis
        if any(f.startswith("status:") for f in s["flags"])
    ]
    if injured:
        hints.append(f"Squad players with status problems: {injured}")

    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "leagueId": lid,
        "budget": available,
        "currentMatchday": current_day,
        "squad": squad_analysis,
        "market": market_analysis,
        "leagueTable": teams,
        "hints": hints,
    }


# ---------------------------------------------------------------------------


def main() -> None:
    # Fail fast on missing config so users get a clear error at startup.
    _get_settings()
    mcp.run()


if __name__ == "__main__":
    main()
