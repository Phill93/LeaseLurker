from __future__ import annotations

from dev.mock_kea import COMMANDS, command_response


def test_mock_lists_required_commands() -> None:
    response = command_response({"command": "list-commands"})
    assert response[0]["result"] == 0
    assert response[0]["arguments"] == COMMANDS


def test_mock_filters_leases_by_subnet() -> None:
    visible = command_response(
        {"command": "lease4-get-all", "arguments": {"subnets": [1]}},
        now=1_800_000_000,
    )[0]
    assert visible["result"] == 0
    assert len(visible["arguments"]["leases"]) == 2
    assert {lease["subnet-id"] for lease in visible["arguments"]["leases"]} == {1}

    empty = command_response(
        {"command": "lease4-get-all", "arguments": {"subnets": [99]}},
        now=1_800_000_000,
    )[0]
    assert empty["result"] == 3


def test_mock_returns_subnets_status_and_errors() -> None:
    assert command_response({"command": "subnet4-list"})[0]["result"] == 0
    assert command_response({"command": "status-get"})[0]["result"] == 0
    assert command_response({"command": "unknown"})[0]["result"] == 1
    assert command_response([])[0]["result"] == 1
