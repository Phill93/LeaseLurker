"""Extension contracts for DHCP servers and device-name resolvers."""

from __future__ import annotations

from typing import Protocol

from lease_lurker.models import Lease, Subnet


class DhcpLeaseProvider(Protocol):
    async def check_capabilities(self) -> None:
        """Raise when required read-only operations are unavailable."""

    async def get_subnets(self) -> list[Subnet]: ...

    async def get_leases(self, subnet_ids: list[int]) -> list[Lease]: ...

    async def is_reachable(self) -> bool: ...

    async def close(self) -> None: ...


class DeviceNameResolver(Protocol):
    @property
    def name(self) -> str: ...

    def resolve(self, mac_address: str) -> str | None: ...


class CompositeDeviceNameResolver:
    """Resolve device names in configured adapter order."""

    def __init__(self, resolvers: tuple[DeviceNameResolver, ...] = ()) -> None:
        self._resolvers = resolvers

    @property
    def name(self) -> str:
        return "composite"

    def resolve(self, mac_address: str) -> str | None:
        for resolver in self._resolvers:
            if result := resolver.resolve(mac_address):
                return result
        return None
