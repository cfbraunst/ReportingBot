"""Steam ID normalization and profile name lookup.

parse_steam_id() is pure and offline. Vanity URLs are the one case that can't be
resolved with arithmetic, so it returns the vanity name as a str and leaves the
API call to resolve_name().
"""
import re
from typing import Union

import aiohttp

from reporter.config import STEAM_API_KEY

# Offset between a 32-bit account ID and a 64-bit SteamID.
ID64_BASE = 76561197960265728

_ID64_RE = re.compile(r"^\d{17}$")
_PROFILES_RE = re.compile(r"steamcommunity\.com/profiles/(\d{17})/?$", re.I)
_VANITY_RE = re.compile(r"steamcommunity\.com/id/([A-Za-z0-9_-]+)/?$", re.I)
_STEAM2_RE = re.compile(r"^STEAM_([0-5]):([01]):(\d+)$", re.I)
_STEAM3_RE = re.compile(r"^\[?U:1:(\d+)\]?$", re.I)

API_BASE = "https://api.steampowered.com"


class SteamIdError(ValueError):
    """Raised when input can't be understood as a Steam identifier."""


class SteamLookupError(RuntimeError):
    """Raised when Steam is reachable but the profile can't be used."""


def parse_steam_id(raw: str) -> Union[int, str]:
    """Normalize any Steam identifier.

    Returns an int SteamID64, or a str vanity name needing an API lookup.
    """
    if not raw or not raw.strip():
        raise SteamIdError("Empty input.")

    text = raw.strip().strip("<>")

    if m := _PROFILES_RE.search(text):
        return _validate_id64(int(m.group(1)))

    if m := _VANITY_RE.search(text):
        return m.group(1)

    if _ID64_RE.match(text):
        return _validate_id64(int(text))

    if m := _STEAM2_RE.match(text):
        auth_server, account_num = int(m.group(2)), int(m.group(3))
        return _validate_id64(account_num * 2 + auth_server + ID64_BASE)

    if m := _STEAM3_RE.match(text):
        return _validate_id64(int(m.group(1)) + ID64_BASE)

    raise SteamIdError(f"Not a recognizable Steam ID: `{raw[:60]}`")


def _validate_id64(value: int) -> int:
    if value <= ID64_BASE:
        raise SteamIdError("Number is too small to be a valid SteamID64.")
    return value


async def resolve_vanity(session: aiohttp.ClientSession, vanity: str) -> int:
    """Turn a /id/<name> vanity into a SteamID64."""
    url = f"{API_BASE}/ISteamUser/ResolveVanityURL/v1/"
    params = {"key": STEAM_API_KEY, "vanityurl": vanity}
    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
        resp.raise_for_status()
        data = await resp.json()

    response = data.get("response", {})
    if response.get("success") != 1:
        raise SteamLookupError(f"No Steam profile found for vanity URL `{vanity}`.")
    return int(response["steamid"])


async def resolve_name(session: aiohttp.ClientSession, steam_id64: int) -> str:
    """Fetch a profile's display name. Raises if missing or private."""
    url = f"{API_BASE}/ISteamUser/GetPlayerSummaries/v2/"
    params = {"key": STEAM_API_KEY, "steamids": str(steam_id64)}
    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
        resp.raise_for_status()
        data = await resp.json()

    players = data.get("response", {}).get("players", [])
    if not players:
        raise SteamLookupError(f"No Steam account exists with ID `{steam_id64}`.")

    name = players[0].get("personaname")
    if not name:
        raise SteamLookupError("That profile is private -- no display name available.")
    return name


async def lookup(raw: str) -> tuple[int, str]:
    """Full path: raw input -> (steam_id64, display_name)."""
    parsed = parse_steam_id(raw)
    async with aiohttp.ClientSession() as session:
        steam_id64 = (
            await resolve_vanity(session, parsed) if isinstance(parsed, str) else parsed
        )
        name = await resolve_name(session, steam_id64)
    return steam_id64, name
