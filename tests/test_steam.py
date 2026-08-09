"""Tests for Steam ID normalization. Pure functions -- no network, no Discord."""
import pytest

from reporter.steam import parse_steam_id, SteamIdError

# A real, well-known public SteamID64 used purely as a fixed arithmetic anchor.
ID64 = 76561198012345678


class TestSteamID64:
    def test_plain_id64(self):
        assert parse_steam_id("76561198012345678") == ID64

    def test_strips_whitespace(self):
        assert parse_steam_id("  76561198012345678  ") == ID64

    def test_rejects_number_below_id64_base(self):
        # 17 digits alone isn't enough; it must sit above the base offset.
        with pytest.raises(SteamIdError):
            parse_steam_id("12345678901234567")


class TestProfileUrls:
    def test_profiles_url(self):
        assert parse_steam_id("https://steamcommunity.com/profiles/76561198012345678") == ID64

    def test_profiles_url_trailing_slash(self):
        assert parse_steam_id("https://steamcommunity.com/profiles/76561198012345678/") == ID64

    def test_profiles_url_no_scheme(self):
        assert parse_steam_id("steamcommunity.com/profiles/76561198012345678") == ID64

    def test_vanity_url_returns_sentinel_for_async_lookup(self):
        # Vanity names can't be converted with arithmetic -- they need an API call,
        # so the parser hands back the name for the resolver to look up.
        assert parse_steam_id("https://steamcommunity.com/id/somevanityname") == "somevanityname"


class TestLegacyFormats:
    def test_steam2(self):
        # STEAM_X:Y:Z  ->  Z*2 + Y + 76561197960265728
        assert parse_steam_id("STEAM_0:0:26039975") == 76561198012345678

    def test_steam2_odd_auth_server(self):
        assert parse_steam_id("STEAM_1:1:26039975") == 76561198012345679

    def test_steam3(self):
        assert parse_steam_id("[U:1:52079950]") == 76561198012345678

    def test_steam3_without_brackets(self):
        assert parse_steam_id("U:1:52079950") == 76561198012345678


class TestRejections:
    @pytest.mark.parametrize("bad", [
        "",
        "   ",
        "not a steam id",
        "https://example.com/profiles/123",
        "76561198012345678extra",
        "STEAM_0:2:123",          # auth server must be 0 or 1
        "[U:9:52079950]",         # unsupported account type
    ])
    def test_rejects_garbage(self, bad):
        with pytest.raises(SteamIdError):
            parse_steam_id(bad)
