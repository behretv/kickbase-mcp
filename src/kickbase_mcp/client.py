"""Async client for the unofficial Kickbase API v4.

Auth is cookie-based: POST /v4/user/login returns a token in ``tkn`` which is
sent as the ``kkstrauth`` cookie on subsequent requests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

BASE_URL = "https://api.kickbase.com"
AUTH_COOKIE = "kkstrauth"

POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
STATUSES = {
    0: "fit",
    1: "injured",
    2: "stricken",
    4: "rehab",
    8: "red_card_suspension",
    16: "yellow_red_suspension",
    32: "fifth_yellow_suspension",
    64: "not_in_team",
    128: "not_in_league",
    256: "absent",
}


class KickbaseError(Exception):
    pass


class KickbaseAuthError(KickbaseError):
    pass


def position_name(code: int | None) -> str:
    return POSITIONS.get(code or 0, f"unknown({code})")


def status_name(code: int | None) -> str:
    return STATUSES.get(code or 0, f"unknown({code})")


class KickbaseClient:
    def __init__(self, email: str, password: str) -> None:
        self._email = email
        self._password = password
        self._token: str | None = None
        self._token_exp: datetime | None = None
        self._user: dict[str, Any] = {}
        self._leagues: dict[str, Any] | None = None
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=30.0,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        self._league_cache: dict[str, str] = {}  # league_id -> competition_id

    async def close(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ auth

    @property
    def user(self) -> dict[str, Any]:
        return self._user

    async def login(self) -> dict[str, Any]:
        r = await self._http.post(
            "/v4/user/login",
            json={"em": self._email, "loy": False, "pass": self._password, "rep": {}},
        )
        if r.status_code == 401:
            raise KickbaseAuthError("Invalid Kickbase credentials")
        if r.status_code != 200:
            raise KickbaseAuthError(
                f"Login failed: HTTP {r.status_code} {r.text[:200]}"
            )
        j = r.json()
        self._token = j.get("tkn")
        if not self._token:
            raise KickbaseAuthError(f"Login response missing token: {list(j)}")
        self._token_exp = _parse_dt(j.get("tknex"))
        self._user = j.get("u", {})
        self._leagues = j.get("srvl")
        return j

    def _token_valid(self) -> bool:
        if not self._token:
            return False
        if self._token_exp is None:
            return True
        # refresh one day early like the reference client
        return self._token_exp > datetime.now(UTC) - timedelta(days=1)

    async def _request(
        self, method: str, path: str, *, retry: bool = True, **kwargs: Any
    ) -> Any:
        if not self._token_valid():
            await self.login()
        r = await self._http.request(
            method, path, cookies={AUTH_COOKIE: self._token or ""}, **kwargs
        )
        if r.status_code == 401 and retry:
            await self.login()
            return await self._request(method, path, retry=False, **kwargs)
        if r.status_code == 404:
            raise KickbaseError(f"Not found: {method} {path}")
        if r.status_code not in (200, 201):
            raise KickbaseError(
                f"{method} {path} failed: HTTP {r.status_code} {r.text[:300]}"
            )
        if r.status_code == 201 or not r.content:
            return {}
        return r.json()

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return await self._request("POST", path, json=body or {})

    async def delete(self, path: str) -> Any:
        return await self._request("DELETE", path)

    # ------------------------------------------------------------ resolution

    async def league_id(self, league: str | None = None) -> str:
        """Resolve a league id from an explicit id/name or the only league."""
        if league:
            leagues = await self.list_leagues()
            for lg in leagues:
                if (
                    str(lg.get("i")) == league
                    or lg.get("n", "").lower() == league.lower()
                ):
                    return str(lg["i"])
            # it might be a raw id not present in the listing; pass it through
            if league.isdigit():
                return league
            raise KickbaseError(
                f"League '{league}' not found in: {[lg.get('n') for lg in leagues]}"
            )
        leagues = await self.list_leagues()
        if not leagues:
            raise KickbaseError("No leagues found for this account")
        if len(leagues) > 1:
            raise KickbaseError(
                f"Multiple leagues found; specify league_id. "
                f"Available: {[(str(lg.get('i')), lg.get('n')) for lg in leagues]}"
            )
        return str(leagues[0]["i"])

    async def competition_id(self, league_id: str) -> str:
        if league_id not in self._league_cache:
            overview = await self.get(f"/v4/leagues/{league_id}/overview")
            self._league_cache[league_id] = str(overview.get("cpi", "1"))
        return self._league_cache[league_id]

    # ------------------------------------------------------------ leagues/me

    async def list_leagues(self) -> list[dict[str, Any]]:
        j = await self.get("/v4/leagues/selection")
        return j.get("it", []) if isinstance(j, dict) else []

    async def league_me(self, league_id: str) -> dict[str, Any]:
        return await self.get(f"/v4/leagues/{league_id}/me")

    async def league_budget(self, league_id: str) -> dict[str, Any]:
        return await self.get(f"/v4/leagues/{league_id}/me/budget")

    async def league_overview(self, league_id: str) -> dict[str, Any]:
        return await self.get(
            f"/v4/leagues/{league_id}/overview",
            params={"includeManagersAndBattles": "true"},
        )

    async def league_ranking(
        self, league_id: str, day: int | None = None
    ) -> dict[str, Any]:
        params = {"dayNumber": day} if day else None
        return await self.get(f"/v4/leagues/{league_id}/ranking", params=params)

    async def squad(self, league_id: str) -> dict[str, Any]:
        return await self.get(f"/v4/leagues/{league_id}/squad")

    async def lineup(self, league_id: str) -> dict[str, Any]:
        return await self.get(f"/v4/leagues/{league_id}/lineup")

    async def set_lineup(
        self, league_id: str, formation: str, player_ids: list[str]
    ) -> Any:
        return await self.post(
            f"/v4/leagues/{league_id}/lineup",
            {"type": formation, "players": player_ids},
        )

    async def my_eleven(self, league_id: str) -> dict[str, Any]:
        return await self.get(f"/v4/leagues/{league_id}/teamcenter/myeleven")

    async def activity_feed(
        self, league_id: str, start: int = 0, max_items: int = 20
    ) -> Any:
        return await self.get(
            f"/v4/leagues/{league_id}/activitiesFeed",
            params={"start": start, "max": max_items},
        )

    # --------------------------------------------------------------- market

    async def market(self, league_id: str) -> dict[str, Any]:
        return await self.get(f"/v4/leagues/{league_id}/market")

    async def market_player(self, league_id: str, player_id: str) -> dict[str, Any]:
        return await self.get(f"/v4/leagues/{league_id}/market/{player_id}")

    async def place_offer(self, league_id: str, player_id: str, price: int) -> Any:
        return await self.post(
            f"/v4/leagues/{league_id}/market/{player_id}/offers", {"price": price}
        )

    async def withdraw_offer(
        self, league_id: str, player_id: str, offer_id: str
    ) -> Any:
        return await self.delete(
            f"/v4/leagues/{league_id}/market/{player_id}/offers/{offer_id}"
        )

    async def accept_offer(self, league_id: str, player_id: str, offer_id: str) -> Any:
        return await self.delete(
            f"/v4/leagues/{league_id}/market/{player_id}/offers/{offer_id}/accept"
        )

    async def decline_offer(self, league_id: str, player_id: str, offer_id: str) -> Any:
        return await self.delete(
            f"/v4/leagues/{league_id}/market/{player_id}/offers/{offer_id}/decline"
        )

    async def list_for_sale(self, league_id: str, player_id: str, price: int) -> Any:
        return await self.post(
            f"/v4/leagues/{league_id}/market/", {"playerId": player_id, "price": price}
        )

    async def remove_from_market(self, league_id: str, player_id: str) -> Any:
        return await self.delete(f"/v4/leagues/{league_id}/market/{player_id}")

    async def sell_to_kickbase(self, league_id: str, player_id: str) -> Any:
        return await self.delete(f"/v4/leagues/{league_id}/market/{player_id}/sell")

    # -------------------------------------------------------------- players

    async def player(self, league_id: str, player_id: str) -> dict[str, Any]:
        return await self.get(f"/v4/leagues/{league_id}/players/{player_id}")

    async def player_performance(
        self, league_id: str, player_id: str
    ) -> dict[str, Any]:
        return await self.get(
            f"/v4/leagues/{league_id}/players/{player_id}/performance"
        )

    async def player_market_value(
        self, league_id: str, player_id: str, timeframe: int = 30
    ) -> Any:
        return await self.get(
            f"/v4/leagues/{league_id}/players/{player_id}/marketvalue/{timeframe}"
        )

    async def player_transfer_history(
        self, league_id: str, player_id: str, start: int = 0
    ) -> Any:
        return await self.get(
            f"/v4/leagues/{league_id}/players/{player_id}/transferHistory",
            params={"start": start},
        )

    async def search_players(
        self, competition_id: str, league_id: str, query: str, max_items: int = 20
    ) -> Any:
        return await self.get(
            f"/v4/competitions/{competition_id}/players/search",
            params={
                "leagueId": league_id,
                "query": query,
                "start": 0,
                "max": max_items,
            },
        )

    async def scouted_players(self, league_id: str) -> Any:
        return await self.get(f"/v4/leagues/{league_id}/scoutedplayers")

    async def scout_player(self, league_id: str, player_id: str) -> Any:
        return await self.post(f"/v4/leagues/{league_id}/scoutedplayers/{player_id}")

    async def unscout_player(self, league_id: str, player_id: str) -> Any:
        return await self.delete(f"/v4/leagues/{league_id}/scoutedplayers/{player_id}")

    # ------------------------------------------------------------- managers

    async def manager_squad(self, league_id: str, user_id: str) -> dict[str, Any]:
        return await self.get(f"/v4/leagues/{league_id}/managers/{user_id}/squad")

    async def manager_dashboard(self, league_id: str, user_id: str) -> dict[str, Any]:
        return await self.get(f"/v4/leagues/{league_id}/managers/{user_id}/dashboard")

    async def manager_transfers(
        self, league_id: str, user_id: str, start: int = 0
    ) -> Any:
        return await self.get(
            f"/v4/leagues/{league_id}/managers/{user_id}/transfer",
            params={"start": start},
        )

    async def user_teamcenter(
        self, league_id: str, user_id: str, day: int | None = None
    ) -> dict[str, Any]:
        params = {"dayNumber": day} if day else None
        return await self.get(
            f"/v4/leagues/{league_id}/users/{user_id}/teamcenter", params=params
        )

    # ---------------------------------------------------------- competitions

    async def matchdays(self, competition_id: str) -> dict[str, Any]:
        return await self.get(f"/v4/competitions/{competition_id}/matchdays")

    async def competition_table(self, competition_id: str) -> dict[str, Any]:
        return await self.get(f"/v4/competitions/{competition_id}/table")

    async def competition_player_performance(
        self, competition_id: str, player_id: str
    ) -> dict[str, Any]:
        return await self.get(
            f"/v4/competitions/{competition_id}/players/{player_id}/performance"
        )

    async def match_details(self, match_id: str) -> dict[str, Any]:
        return await self.get(f"/v4/matches/{match_id}/details")

    # ----------------------------------------------------------------- bonus

    async def collect_bonus(self) -> Any:
        return await self.get("/v4/bonus/collect")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, AttributeError):
        return None
