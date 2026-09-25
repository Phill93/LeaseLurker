"""Lease snapshot, filtering, and search logic."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import ceil

from lease_lurker.models import LeaseSnapshot, LeaseView, Subnet
from lease_lurker.providers import DeviceNameResolver, DhcpLeaseProvider
from lease_lurker.settings import Settings
from lease_lurker.vendor import VendorLookup

LOGGER = logging.getLogger(__name__)


class SnapshotUnavailableError(RuntimeError):
    """Raised when no lease snapshot can be served."""


@dataclass(frozen=True, slots=True)
class SnapshotResult:
    snapshot: LeaseSnapshot
    stale: bool
    refresh_error: str | None = None


@dataclass(frozen=True, slots=True)
class SearchPage:
    items: tuple[LeaseView, ...]
    page: int
    pages: int
    total: int


@dataclass(frozen=True, slots=True)
class LeaseFilters:
    hostname: str = ""
    ip: str = ""
    mac: str = ""
    vendor: str = ""
    remaining_max_minutes: int | None = None
    hostname_warning: bool = False


class LeaseService:
    def __init__(
        self,
        provider: DhcpLeaseProvider,
        settings: Settings,
        vendors: VendorLookup,
        device_names: DeviceNameResolver,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider = provider
        self._settings = settings
        self._vendors = vendors
        self._device_names = device_names
        self._clock = clock or (lambda: datetime.now(UTC))
        self._snapshot: LeaseSnapshot | None = None
        self._refresh_lock = asyncio.Lock()
        self._capabilities_ok = False
        self._hostname_pattern = (
            re.compile(settings.web.hostname_regex, re.IGNORECASE)
            if settings.web.hostname_regex
            else None
        )

    async def initialize(self) -> None:
        await self._provider.check_capabilities()
        self._capabilities_ok = True

    async def snapshot(self, *, force: bool = False) -> SnapshotResult:
        now = self._clock()
        if not force and self._is_fresh(now):
            return SnapshotResult(self._snapshot_or_raise(), stale=False)

        async with self._refresh_lock:
            now = self._clock()
            if not force and self._is_fresh(now):
                return SnapshotResult(self._snapshot_or_raise(), stale=False)
            try:
                snapshot = await self._build_snapshot(now)
            except Exception as exc:
                LOGGER.exception("Kea lease snapshot refresh failed")
                if self._snapshot is None:
                    raise SnapshotUnavailableError(
                        "No lease snapshot is available"
                    ) from exc
                age = now - self._snapshot.refreshed_at
                stale_limit = timedelta(
                    seconds=self._settings.cache.stale_after_seconds
                )
                if age > stale_limit:
                    raise SnapshotUnavailableError("Lease snapshot is too old") from exc
                return SnapshotResult(
                    self._snapshot, stale=True, refresh_error=type(exc).__name__
                )
            self._snapshot = snapshot
            return SnapshotResult(snapshot, stale=False)

    def _is_fresh(self, now: datetime) -> bool:
        if self._snapshot is None:
            return False
        return now - self._snapshot.refreshed_at < timedelta(
            seconds=self._settings.cache.ttl_seconds
        )

    def _snapshot_or_raise(self) -> LeaseSnapshot:
        if self._snapshot is None:
            raise SnapshotUnavailableError("No lease snapshot is available")
        return self._snapshot

    async def _build_snapshot(self, now: datetime) -> LeaseSnapshot:
        visible_id_list = self._settings.visible_subnet_ids
        all_subnets, leases = await asyncio.gather(
            self._provider.get_subnets(),
            self._provider.get_leases(visible_id_list),
        )
        overrides = self._settings.subnet_name_overrides
        discovered_subnets = {subnet.id: subnet for subnet in all_subnets}
        visible_subnets = tuple(
            Subnet(
                id=subnet.id,
                prefix=subnet.prefix,
                name=overrides.get(subnet.id, subnet.name),
            )
            for subnet_id in visible_id_list
            if (subnet := discovered_subnets.get(subnet_id)) is not None
        )
        subnets = {subnet.id: subnet for subnet in visible_subnets}
        subnet_order = {
            subnet.id: index for index, subnet in enumerate(visible_subnets)
        }
        views = []
        for lease in leases:
            if lease.subnet_id not in subnets or not lease.is_active(now):
                continue
            views.append(
                LeaseView(
                    lease=lease,
                    subnet=subnets[lease.subnet_id],
                    vendor=(
                        self._vendors.lookup(lease.mac_address)
                        if lease.mac_address
                        else None
                    ),
                    device_name=(
                        self._device_names.resolve(lease.mac_address)
                        if lease.mac_address
                        else None
                    ),
                    hostname_valid=(
                        self._hostname_pattern.fullmatch(lease.hostname) is not None
                        if self._hostname_pattern is not None
                        else None
                    ),
                )
            )
        views.sort(
            key=lambda view: (
                subnet_order[view.subnet.id],
                view.lease.ip_address,
            )
        )
        return LeaseSnapshot(
            leases=tuple(views), subnets=visible_subnets, refreshed_at=now
        )

    def search(
        self,
        snapshot: LeaseSnapshot,
        query: str,
        page: int,
        subnet_id: int | None = None,
        *,
        filters: LeaseFilters | None = None,
        page_size: int | None = -1,
        now: datetime | None = None,
    ) -> SearchPage:
        cleaned = query.strip().casefold()
        mac_fragment = "".join(char for char in cleaned if char in "0123456789abcdef")
        selected_filters = filters or LeaseFilters()
        hostname_filter = selected_filters.hostname.strip().casefold()
        ip_filter = selected_filters.ip.strip().casefold()
        raw_mac_filter = selected_filters.mac.strip().casefold()
        filter_mac = "".join(
            char for char in raw_mac_filter if char in "0123456789abcdef"
        )
        vendor_filter = selected_filters.vendor.strip().casefold()
        current = now or self._clock()

        def matches_filters(view: LeaseView) -> bool:
            if (
                hostname_filter
                and hostname_filter not in view.lease.hostname.casefold()
            ):
                return False
            if ip_filter and ip_filter not in view.lease.ip_address.casefold():
                return False
            if raw_mac_filter:
                if not filter_mac:
                    return False
                if view.lease.mac_address is None:
                    return False
                if filter_mac not in view.lease.mac_address.replace(":", ""):
                    return False
            if vendor_filter:
                if vendor_filter == "~unknown":
                    if view.vendor is not None:
                        return False
                elif view.vendor is None or view.vendor.casefold() != vendor_filter:
                    return False
            if selected_filters.remaining_max_minutes is not None:
                remaining = view.lease.expires_at - current
                if remaining >= timedelta(
                    minutes=selected_filters.remaining_max_minutes
                ):
                    return False
            return not (
                selected_filters.hostname_warning and view.hostname_valid is not False
            )

        matches = tuple(
            view
            for view in snapshot.leases
            if (subnet_id is None or view.subnet.id == subnet_id)
            and matches_filters(view)
            and (
                not cleaned
                or (len(cleaned) >= 2 and cleaned in view.lease.hostname.casefold())
                or (len(cleaned) >= 2 and cleaned in view.lease.ip_address)
                or (
                    len(mac_fragment) >= 4
                    and view.lease.mac_address is not None
                    and mac_fragment in view.lease.mac_address.replace(":", "")
                )
            )
        )
        effective_page_size = (
            self._settings.web.page_size if page_size == -1 else page_size
        )
        if effective_page_size is None:
            return SearchPage(
                items=matches,
                page=1,
                pages=1,
                total=len(matches),
            )
        pages = max(1, ceil(len(matches) / effective_page_size))
        selected_page = min(max(page, 1), pages)
        start = (selected_page - 1) * effective_page_size
        return SearchPage(
            items=matches[start : start + effective_page_size],
            page=selected_page,
            pages=pages,
            total=len(matches),
        )

    async def ready(self) -> bool:
        if not self._capabilities_ok:
            return False
        if self._snapshot is not None:
            age = self._clock() - self._snapshot.refreshed_at
            if age <= timedelta(seconds=self._settings.cache.stale_after_seconds):
                return True
        return await self._provider.is_reachable()

    async def close(self) -> None:
        await self._provider.close()
