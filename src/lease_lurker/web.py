"""FastAPI application factory and HTML endpoints."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from lease_lurker import __version__
from lease_lurker.i18n import select_locale, translator
from lease_lurker.kea import KeaProvider
from lease_lurker.providers import CompositeDeviceNameResolver
from lease_lurker.service import LeaseFilters, LeaseService, SnapshotUnavailableError
from lease_lurker.settings import Settings, load_settings
from lease_lurker.vendor import VendorLookup

LOGGER = logging.getLogger(__name__)
PACKAGE_DIR = Path(__file__).parent
PAGE_SIZE_COOKIE = "lease_lurker_page_size"


def _remaining(expires_at: datetime, now: datetime) -> str:
    seconds = max(0, int((expires_at - now).total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min"


def _optional_positive_int(value: str | None, field: str) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"{field} must be an integer"
        ) from exc
    if parsed < 1:
        raise HTTPException(status_code=422, detail=f"{field} must be at least 1")
    return parsed


def create_app(
    settings: Settings | None = None,
    service: LeaseService | None = None,
) -> FastAPI:
    configured = settings or load_settings()
    lease_service = service or LeaseService(
        provider=KeaProvider(configured.kea),
        settings=configured,
        vendors=VendorLookup(),
        device_names=CompositeDeviceNameResolver(),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            await lease_service.initialize()
        except Exception:
            LOGGER.exception("Kea capability check failed; readiness remains degraded")
        app.state.last_manual_refresh = 0.0
        yield
        await lease_service.close()

    app = FastAPI(
        title="LeaseLurker",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = configured
    app.state.lease_service = lease_service
    templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
    templates.env.filters["remaining"] = _remaining
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    async def render_leases(
        request: Request,
        query: str,
        page: int,
        subnet: int | None = None,
        force: bool = False,
        per_page: str | None = None,
        filters: LeaseFilters | None = None,
    ) -> HTMLResponse:
        return await _render_leases(
            request=request,
            query=query,
            page=page,
            subnet=subnet,
            force=force,
            per_page=per_page,
            filters=filters or LeaseFilters(),
            service=lease_service,
            settings=configured,
            templates=templates,
        )

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return await render_leases(request, "", 1)

    @app.get("/leases", response_class=HTMLResponse)
    async def leases(
        request: Request,
        q: str = Query(default="", max_length=100),
        page: int = Query(default=1, ge=1),
        subnet: str | None = Query(default=None, max_length=20),
        per_page: str | None = Query(default=None, max_length=10),
        hostname: str = Query(default="", max_length=100),
        ip: str = Query(default="", max_length=45),
        mac: str = Query(default="", max_length=50),
        vendor: str = Query(default="", max_length=200),
        remaining_max_minutes: str | None = Query(default=None, max_length=10),
        hostname_warning: bool = Query(default=False),
    ) -> HTMLResponse:
        return await render_leases(
            request,
            q,
            page,
            _optional_positive_int(subnet, "subnet"),
            per_page=per_page,
            filters=LeaseFilters(
                hostname=hostname,
                ip=ip,
                mac=mac,
                vendor=vendor,
                remaining_max_minutes=_optional_positive_int(
                    remaining_max_minutes, "remaining_max_minutes"
                ),
                hostname_warning=hostname_warning,
            ),
        )

    @app.post("/refresh")
    async def refresh(
        request: Request,
        q: str = Form(default=""),
        subnet: str | None = Form(default=None),
        per_page: str | None = Form(default=None),
        hostname: str = Form(default=""),
        ip: str = Form(default=""),
        mac: str = Form(default=""),
        vendor: str = Form(default=""),
        remaining_max_minutes: str | None = Form(default=None),
        hostname_warning: bool = Form(default=False),
    ) -> RedirectResponse:
        now = time.monotonic()
        if now - app.state.last_manual_refresh >= 5:
            app.state.last_manual_refresh = now
            try:
                await lease_service.snapshot(force=True)
            except SnapshotUnavailableError:
                LOGGER.warning("Manual lease refresh failed")
        target = _lease_url(
            q,
            _optional_positive_int(subnet, "subnet"),
            per_page=per_page,
            filters=LeaseFilters(
                hostname=hostname,
                ip=ip,
                mac=mac,
                vendor=vendor,
                remaining_max_minutes=_optional_positive_int(
                    remaining_max_minutes, "remaining_max_minutes"
                ),
                hostname_warning=hostname_warning,
            ),
        )
        return RedirectResponse(target, status_code=303)

    @app.get("/locale/{locale}")
    async def locale(locale: str) -> RedirectResponse:
        selected = locale if locale in {"de", "en"} else configured.web.default_locale
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            "lease_lurker_locale",
            selected,
            max_age=31_536_000,
            httponly=True,
            samesite="lax",
        )
        return response

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready() -> HTMLResponse:
        if await lease_service.ready():
            return HTMLResponse("ready", status_code=200)
        return HTMLResponse("not ready", status_code=503)

    return app


async def _render_leases(
    *,
    request: Request,
    query: str,
    page: int,
    subnet: int | None,
    force: bool,
    per_page: str | None,
    filters: LeaseFilters,
    service: LeaseService,
    settings: Settings,
    templates: Jinja2Templates,
) -> HTMLResponse:
    locale = select_locale(
        request.cookies.get("lease_lurker_locale"),
        request.headers.get("accept-language"),
        settings.web.default_locale,
    )
    translate = translator(locale)
    try:
        snapshot_result = await service.snapshot(force=force)
    except SnapshotUnavailableError:
        return templates.TemplateResponse(
            request=request,
            name="unavailable.html",
            context={"locale": locale, "t": translate},
            status_code=503,
        )
    subnets = snapshot_result.snapshot.subnets
    visible_ids = {item.id for item in subnets}
    selected_subnet = subnet if subnet in visible_ids else None
    cookie_page_size = request.cookies.get(PAGE_SIZE_COOKIE)
    effective_page_size, page_size_token = _select_page_size(
        per_page,
        cookie_page_size,
        settings,
    )
    now = datetime.now(snapshot_result.snapshot.refreshed_at.tzinfo)
    result = service.search(
        snapshot_result.snapshot,
        query,
        page,
        subnet_id=selected_subnet,
        filters=filters,
        page_size=effective_page_size,
        now=now,
    )
    scoped_leases = (
        snapshot_result.snapshot.leases
        if selected_subnet is None
        else tuple(
            item
            for item in snapshot_result.snapshot.leases
            if item.subnet.id == selected_subnet
        )
    )
    vendors = sorted(
        {item.vendor for item in scoped_leases if item.vendor is not None},
        key=str.casefold,
    )
    response = templates.TemplateResponse(
        request=request,
        name="leases.html",
        context={
            "locale": locale,
            "t": translate,
            "query": query,
            "result": result,
            "subnets": subnets,
            "selected_subnet": selected_subnet,
            "lease_url": _lease_url,
            "filters": filters,
            "filter_active": any(
                (
                    filters.hostname,
                    filters.ip,
                    filters.mac,
                    filters.vendor,
                    filters.remaining_max_minutes,
                    filters.hostname_warning,
                )
            ),
            "vendors": vendors,
            "has_unknown_vendor": any(item.vendor is None for item in scoped_leases),
            "page_size_token": page_size_token,
            "page_size_options": settings.web.allowed_page_sizes,
            "page_size_value": effective_page_size,
            "reset_filters_url": _lease_url(
                query, selected_subnet, per_page=page_size_token
            ),
            "clear_filter_urls": {
                "hostname": _lease_url(
                    query,
                    selected_subnet,
                    per_page=page_size_token,
                    filters=replace(filters, hostname=""),
                ),
                "hostname_warning": _lease_url(
                    query,
                    selected_subnet,
                    per_page=page_size_token,
                    filters=replace(filters, hostname_warning=False),
                ),
                "hostname_group": _lease_url(
                    query,
                    selected_subnet,
                    per_page=page_size_token,
                    filters=replace(filters, hostname="", hostname_warning=False),
                ),
                "ip": _lease_url(
                    query,
                    selected_subnet,
                    per_page=page_size_token,
                    filters=replace(filters, ip=""),
                ),
                "mac": _lease_url(
                    query,
                    selected_subnet,
                    per_page=page_size_token,
                    filters=replace(filters, mac=""),
                ),
                "vendor": _lease_url(
                    query,
                    selected_subnet,
                    per_page=page_size_token,
                    filters=replace(filters, vendor=""),
                ),
                "remaining_max_minutes": _lease_url(
                    query,
                    selected_subnet,
                    per_page=page_size_token,
                    filters=replace(filters, remaining_max_minutes=None),
                ),
            },
            "snapshot": snapshot_result,
            "now": now,
        },
    )
    if per_page is not None:
        response.set_cookie(
            PAGE_SIZE_COOKIE,
            page_size_token,
            max_age=31_536_000,
            httponly=True,
            samesite="lax",
        )
    return response


def _page_size_token(page_size: int | None) -> str:
    return "all" if page_size is None else str(page_size)


def _select_page_size(
    requested: str | None,
    cookie: str | None,
    settings: Settings,
) -> tuple[int | None, str]:
    allowed = {
        _page_size_token(value): value for value in settings.web.allowed_page_sizes
    }
    default = settings.web.page_size
    if requested is not None:
        if requested in allowed:
            return allowed[requested], requested
        return default, _page_size_token(default)
    if cookie is not None and cookie in allowed:
        return allowed[cookie], cookie
    return default, _page_size_token(default)


def _lease_url(
    query: str,
    subnet: int | None = None,
    page: int = 1,
    per_page: str | None = None,
    filters: LeaseFilters | None = None,
) -> str:
    parameters: dict[str, str | int] = {}
    if query:
        parameters["q"] = query
    if subnet is not None:
        parameters["subnet"] = subnet
    if page > 1:
        parameters["page"] = page
    if per_page:
        parameters["per_page"] = per_page
    selected_filters = filters or LeaseFilters()
    if selected_filters.hostname:
        parameters["hostname"] = selected_filters.hostname
    if selected_filters.ip:
        parameters["ip"] = selected_filters.ip
    if selected_filters.mac:
        parameters["mac"] = selected_filters.mac
    if selected_filters.vendor:
        parameters["vendor"] = selected_filters.vendor
    if selected_filters.remaining_max_minutes is not None:
        parameters["remaining_max_minutes"] = selected_filters.remaining_max_minutes
    if selected_filters.hostname_warning:
        parameters["hostname_warning"] = "true"
    return f"/leases?{urlencode(parameters)}" if parameters else "/leases"
