"""Authenticated read-only JSON API."""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from lease_lurker.service import LeaseFilters, LeaseService, SnapshotUnavailableError

router = APIRouter(prefix="/api/v1", tags=["leases"])
bearer = HTTPBearer(auto_error=False)


class ApiSubnet(BaseModel):
    id: int
    prefix: str
    name: str


class ApiLease(BaseModel):
    ip_address: str
    hostname: str
    device_name: str | None
    mac_address: str | None
    vendor: str | None
    subnet: ApiSubnet
    starts_at: datetime
    expires_at: datetime
    valid_lifetime_seconds: int
    remaining_seconds: int
    state: int
    hostname_valid: bool | None


class ApiPagination(BaseModel):
    page: int
    per_page: int | None
    pages: int
    total: int


class ApiSnapshot(BaseModel):
    refreshed_at: datetime
    stale: bool


class LeaseListResponse(BaseModel):
    items: list[ApiLease]
    pagination: ApiPagination
    snapshot: ApiSnapshot


def _require_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)],
) -> None:
    configured = request.app.state.settings.api.token
    if configured is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LeaseLurker API is not configured",
        )
    if credentials is None or not secrets.compare_digest(
        credentials.credentials, configured.get_secret_value()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _page_size(value: str) -> int | None:
    if value == "all":
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="per_page must be an integer from 1 to 200 or 'all'",
        ) from exc
    if not 1 <= parsed <= 200:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="per_page must be an integer from 1 to 200 or 'all'",
        )
    return parsed


@router.get(
    "/leases",
    response_model=LeaseListResponse,
    summary="Search active leases",
    responses={
        401: {"description": "Invalid or missing bearer token"},
        503: {"description": "API not configured or lease data unavailable"},
    },
)
async def list_leases(
    request: Request,
    _: Annotated[None, Security(_require_token)],
    q: Annotated[str, Query(max_length=100)] = "",
    subnet: Annotated[int | None, Query(gt=0)] = None,
    hostname: Annotated[str, Query(max_length=100)] = "",
    ip: Annotated[str, Query(max_length=45)] = "",
    mac: Annotated[str, Query(max_length=50)] = "",
    vendor: Annotated[str, Query(max_length=200)] = "",
    remaining_max_minutes: Annotated[int | None, Query(gt=0)] = None,
    hostname_warning: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[str, Query(max_length=3)] = "50",
) -> LeaseListResponse:
    service: LeaseService = request.app.state.lease_service
    try:
        snapshot = await service.snapshot()
    except SnapshotUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Lease data is currently unavailable",
        ) from exc

    now = datetime.now(snapshot.snapshot.refreshed_at.tzinfo)
    selected_page_size = _page_size(per_page)
    result = service.search(
        snapshot.snapshot,
        q,
        page,
        subnet_id=subnet,
        filters=LeaseFilters(
            hostname=hostname,
            ip=ip,
            mac=mac,
            vendor=vendor,
            remaining_max_minutes=remaining_max_minutes,
            hostname_warning=hostname_warning,
        ),
        page_size=selected_page_size,
        now=now,
    )
    return LeaseListResponse(
        items=[
            ApiLease(
                ip_address=view.lease.ip_address,
                hostname=view.lease.hostname,
                device_name=view.device_name,
                mac_address=view.lease.mac_address,
                vendor=view.vendor,
                subnet=ApiSubnet(
                    id=view.subnet.id,
                    prefix=view.subnet.prefix,
                    name=view.subnet.name,
                ),
                starts_at=view.lease.starts_at,
                expires_at=view.lease.expires_at,
                valid_lifetime_seconds=int(view.lease.valid_lifetime.total_seconds()),
                remaining_seconds=max(
                    0, int((view.lease.expires_at - now).total_seconds())
                ),
                state=view.lease.state,
                hostname_valid=view.hostname_valid,
            )
            for view in result.items
        ],
        pagination=ApiPagination(
            page=result.page,
            per_page=selected_page_size,
            pages=result.pages,
            total=result.total,
        ),
        snapshot=ApiSnapshot(
            refreshed_at=snapshot.snapshot.refreshed_at,
            stale=snapshot.stale,
        ),
    )
