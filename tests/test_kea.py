from __future__ import annotations

import httpx
import pytest

from lease_lurker.kea import KeaError, KeaProvider, normalize_mac
from lease_lurker.settings import KeaSettings


def client_for(payload: object, status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload, request=request)

    return httpx.AsyncClient(
        base_url="http://kea.test/", transport=httpx.MockTransport(handler)
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("00-11-22-33-44-55", "00:11:22:33:44:55"),
        ("0011.2233.4455", "00:11:22:33:44:55"),
        ("001122334455", "00:11:22:33:44:55"),
    ],
)
def test_normalize_mac(value: str, expected: str) -> None:
    assert normalize_mac(value) == expected


def test_normalize_mac_rejects_invalid_value() -> None:
    with pytest.raises(ValueError):
        normalize_mac("nope")


async def test_parses_subnets_and_leases(now) -> None:
    responses = iter(
        [
            [
                {
                    "result": 0,
                    "arguments": {"subnets": [{"id": 1, "subnet": "192.0.2.0/24"}]},
                }
            ],
            [
                {
                    "result": 0,
                    "arguments": {
                        "leases": [
                            {
                                "ip-address": "192.0.2.42",
                                "hostname": "pc.example.",
                                "hw-address": "00-11-22-33-44-55",
                                "subnet-id": 1,
                                "cltt": int(now.timestamp()),
                                "valid-lft": 3600,
                                "state": 0,
                            }
                        ]
                    },
                }
            ],
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(responses), request=request)

    client = httpx.AsyncClient(
        base_url="http://kea.test/", transport=httpx.MockTransport(handler)
    )
    provider = KeaProvider(KeaSettings(url="http://kea.test/"), client)
    subnets = await provider.get_subnets()
    leases = await provider.get_leases([1])
    assert subnets[0].name == "192.0.2.0/24"
    assert leases[0].hostname == "pc.example"
    assert leases[0].mac_address == "00:11:22:33:44:55"
    assert await provider.get_leases([]) == []


async def test_capability_check_reports_missing_command() -> None:
    provider = KeaProvider(
        KeaSettings(url="http://kea.test/"),
        client_for([{"result": 0, "arguments": {"commands": ["subnet4-list"]}}]),
    )
    with pytest.raises(KeaError, match="lease4-get-all"):
        await provider.check_capabilities()


async def test_capability_check_accepts_native_list_shape() -> None:
    provider = KeaProvider(
        KeaSettings(url="http://kea.test/"),
        client_for([{"result": 0, "arguments": ["lease4-get-all", "subnet4-list"]}]),
    )
    await provider.check_capabilities()


@pytest.mark.parametrize(
    "payload",
    [
        {"not": "a list"},
        [],
        ["invalid"],
        [{"result": 1, "text": "denied"}],
    ],
)
async def test_protocol_errors(payload: object) -> None:
    provider = KeaProvider(KeaSettings(url="http://kea.test/"), client_for(payload))
    with pytest.raises(KeaError):
        await provider.get_subnets()


async def test_transport_error_and_reachability() -> None:
    provider = KeaProvider(
        KeaSettings(url="http://kea.test/"), client_for({"error": True}, 500)
    )
    assert await provider.is_reachable() is False


async def test_command_allowlist() -> None:
    provider = KeaProvider(KeaSettings(url="http://kea.test/"), client_for([]))
    with pytest.raises(KeaError, match="allowlisted"):
        await provider._command("lease4-del")  # type: ignore[attr-defined]
