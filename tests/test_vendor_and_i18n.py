from __future__ import annotations

from lease_lurker.i18n import select_locale, translator
from lease_lurker.providers import CompositeDeviceNameResolver
from lease_lurker.vendor import VendorLookup


def test_vendor_uses_longest_prefix() -> None:
    lookup = VendorLookup(
        {6: {"001122": "Large"}, 7: {"0011223": "Medium"}, 9: {"001122334": "Small"}}
    )
    assert lookup.lookup("00:11:22:33:44:55") == "Small"
    assert lookup.lookup("ff:ff:ff:ff:ff:ff") is None


def test_locale_cookie_wins_then_accept_language() -> None:
    assert select_locale("en", "de", "de") == "en"
    assert select_locale(None, "fr-FR, en;q=0.8", "de") == "en"
    assert select_locale(None, None, "de") == "de"
    assert translator("en")("search") == "Search"


class Resolver:
    def __init__(self, result: str | None) -> None:
        self.result = result

    @property
    def name(self) -> str:
        return "test"

    def resolve(self, mac_address: str) -> str | None:
        return self.result


def test_composite_resolver_stops_at_first_result() -> None:
    resolver = CompositeDeviceNameResolver((Resolver(None), Resolver("Desk 42")))
    assert resolver.resolve("00:11:22:33:44:55") == "Desk 42"
    assert CompositeDeviceNameResolver().resolve("00:11:22:33:44:55") is None
