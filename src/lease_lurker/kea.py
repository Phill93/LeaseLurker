"""Read-only Kea Control Agent adapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from lease_lurker.models import Lease, Subnet
from lease_lurker.settings import KeaSettings


class KeaError(RuntimeError):
    """Raised for transport, protocol, or capability failures."""


class KeaProvider:
    """Kea adapter whose command allowlist contains only read operations."""

    REQUIRED_COMMANDS = frozenset({"lease4-get-all", "subnet4-list"})
    ALLOWED_COMMANDS = REQUIRED_COMMANDS | {"list-commands", "status-get"}

    def __init__(
        self, settings: KeaSettings, client: httpx.AsyncClient | None = None
    ) -> None:
        auth = None
        if settings.username and settings.password:
            auth = (settings.username, settings.password.get_secret_value())
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=str(settings.url),
            auth=auth,
            timeout=settings.timeout_seconds,
        )

    async def _command(
        self, command: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if command not in self.ALLOWED_COMMANDS:
            raise KeaError(f"Kea command is not read-only allowlisted: {command}")
        payload: dict[str, Any] = {"command": command, "service": ["dhcp4"]}
        if arguments is not None:
            payload["arguments"] = arguments
        try:
            response = await self._client.post("", json=payload)
            response.raise_for_status()
            document = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise KeaError("Kea Control Agent request failed") from exc
        if not isinstance(document, list) or len(document) != 1:
            raise KeaError("Kea returned an unexpected response envelope")
        result = document[0]
        if not isinstance(result, dict):
            raise KeaError("Kea returned an invalid response object")
        code = result.get("result")
        if code not in {0, 3}:
            text = str(result.get("text", "unknown Kea error"))
            raise KeaError(f"Kea command {command} failed: {text}")
        return result

    async def check_capabilities(self) -> None:
        result = await self._command("list-commands")
        arguments = result.get("arguments", {})
        if isinstance(arguments, list):
            commands = arguments
        elif isinstance(arguments, dict):
            commands = arguments.get("commands", [])
        else:
            commands = []
        available = {str(item) for item in commands}
        missing = self.REQUIRED_COMMANDS - available
        if missing:
            raise KeaError(
                f"Kea is missing required commands: {', '.join(sorted(missing))}"
            )

    async def get_subnets(self) -> list[Subnet]:
        result = await self._command("subnet4-list")
        arguments = result.get("arguments", {})
        items = arguments.get("subnets", []) if isinstance(arguments, dict) else []
        if not isinstance(items, list):
            raise KeaError("Kea subnet list is invalid")
        subnets: list[Subnet] = []
        for item in items:
            if not isinstance(item, dict):
                raise KeaError("Kea subnet entry is invalid")
            subnet_id = int(item["id"])
            prefix = str(item["subnet"])
            shared_network = str(item.get("shared-network", "")).strip()
            subnets.append(
                Subnet(
                    id=subnet_id,
                    prefix=prefix,
                    name=shared_network or prefix,
                )
            )
        return subnets

    async def get_leases(self, subnet_ids: list[int]) -> list[Lease]:
        if not subnet_ids:
            return []
        result = await self._command("lease4-get-all", {"subnets": subnet_ids})
        arguments = result.get("arguments", {})
        items = arguments.get("leases", []) if isinstance(arguments, dict) else []
        if not isinstance(items, list):
            raise KeaError("Kea lease list is invalid")
        leases: list[Lease] = []
        try:
            for item in items:
                if not isinstance(item, dict):
                    raise TypeError
                leases.append(
                    Lease(
                        ip_address=str(item["ip-address"]),
                        hostname=str(item.get("hostname", "")).rstrip("."),
                        mac_address=normalize_mac(str(item["hw-address"])),
                        subnet_id=int(item["subnet-id"]),
                        starts_at=datetime.fromtimestamp(int(item["cltt"]), UTC),
                        valid_lifetime=timedelta(seconds=int(item["valid-lft"])),
                        state=int(item.get("state", 0)),
                    )
                )
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise KeaError("Kea lease entry is invalid") from exc
        return leases

    async def is_reachable(self) -> bool:
        try:
            await self._command("status-get")
        except KeaError:
            return False
        return True

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def normalize_mac(value: str) -> str:
    """Return a canonical 48-bit colon-separated MAC address."""
    compact = "".join(character for character in value if character.isalnum()).lower()
    if len(compact) != 12 or any(
        character not in "0123456789abcdef" for character in compact
    ):
        raise ValueError("invalid MAC address")
    return ":".join(compact[index : index + 2] for index in range(0, 12, 2))
