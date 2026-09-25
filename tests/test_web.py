from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI

from lease_lurker.service import LeaseService
from lease_lurker.vendor import VendorLookup
from lease_lurker.web import _lease_url, create_app

from .conftest import FakeProvider, NoNames, make_lease


def make_test_app(settings, now, *, fail: bool = False) -> tuple[FastAPI, FakeProvider]:
    provider = FakeProvider(
        [make_lease(now, hostname="<script>alert(1)</script>")], fail=fail
    )
    service = LeaseService(
        provider,
        settings,
        VendorLookup({6: {"001122": "Example Vendor"}}),
        NoNames(),
        clock=lambda: now,
    )
    return create_app(settings, service), provider


@asynccontextmanager
async def app_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            yield client


async def test_html_search_is_localized_and_escaped(settings, now) -> None:
    app, _ = make_test_app(settings, now)
    async with app_client(app) as client:
        response = await client.get("/", headers={"Accept-Language": "en"})
        assert response.status_code == 200
        assert ">Search<" in response.text
        assert "Example Vendor" in response.text
        assert "<script>alert(1)</script>" not in response.text
        assert "&lt;script&gt;" in response.text
        assert "Office <span>192.0.2.0/24</span>" in response.text
        assert 'href="/leases?subnet=3&amp;per_page=10"' in response.text
        assert "Lab <span>203.0.113.0/24</span>" in response.text
        assert 'class="theme-toggle"' in response.text
        assert "lease-lurker-theme" in response.text
        theme_script = await client.get("/static/theme.js")
        stylesheet = await client.get("/static/style.css")
        assert 'localStorage.setItem("lease-lurker-theme", theme)' in theme_script.text
        assert "prefers-color-scheme: dark" in stylesheet.text
        assert ':root[data-theme="dark"]' in stylesheet.text


async def test_search_no_results_and_locale_cookie(settings, now) -> None:
    app, _ = make_test_app(settings, now)
    async with app_client(app) as client:
        switched = await client.get("/locale/en", follow_redirects=False)
        assert switched.status_code == 303
        assert "lease_lurker_locale=en" in switched.headers["set-cookie"]
        client.cookies.set("lease_lurker_locale", "en")
        response = await client.get("/leases?q=does-not-exist")
        assert "No matching active leases found" in response.text


async def test_manual_refresh_and_health(settings, now) -> None:
    app, provider = make_test_app(settings, now)
    async with app_client(app) as client:
        assert (await client.get("/health/live")).json() == {"status": "ok"}
        assert (await client.get("/health/ready")).status_code == 200
        response = await client.post(
            "/refresh", data={"q": "pc", "subnet": "1"}, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/leases?q=pc&subnet=1"
        assert provider.calls == 1


async def test_subnet_tabs_filter_and_preserve_query(settings, now) -> None:
    app, _ = make_test_app(settings, now)
    async with app_client(app) as client:
        selected = await client.get("/leases?q=pc&subnet=1")
        assert selected.status_code == 200
        assert (
            'href="/leases?q=pc&amp;subnet=1&amp;per_page=10" aria-current="page"'
            in selected.text
        )
        assert "<th>Subnetz</th>" not in selected.text

        unknown = await client.get("/leases?subnet=999")
        assert unknown.status_code == 200
        assert 'href="/leases?per_page=10" aria-current="page"' in unknown.text
        assert "<th>Subnetz</th>" in unknown.text

        empty = await client.get("/leases?subnet=3")
        assert empty.status_code == 200
        assert "Keine passenden aktiven Leases gefunden" in empty.text


def test_lease_url_preserves_filter_and_pagination() -> None:
    assert _lease_url("lab pc", 3, 2) == "/leases?q=lab+pc&subnet=3&page=2"
    assert _lease_url("", None) == "/leases"


async def test_page_size_url_cookie_and_all_option(settings, now) -> None:
    provider = FakeProvider(
        [make_lease(now, hostname=f"pc-{index:03}") for index in range(12)]
    )
    service = LeaseService(
        provider, settings, VendorLookup({}), NoNames(), clock=lambda: now
    )
    app = create_app(settings, service)
    async with app_client(app) as client:
        response = await client.get("/leases?per_page=all")
        assert response.status_code == 200
        assert response.text.count("<tbody>") == 1
        assert "Seite 1 von" not in response.text
        assert "lease_lurker_page_size=all" in response.headers["set-cookie"]

        cookie_response = await client.get("/leases")
        assert '<option value="all" selected>Alle</option>' in cookie_response.text

        invalid = await client.get("/leases?per_page=invalid")
        assert '<option value="10" selected>10</option>' in invalid.text


async def test_column_filters_and_hostname_warning_are_rendered(settings, now) -> None:
    configured = settings.model_copy(deep=True)
    configured.web.hostname_regex = r"(iai|elab)-([a-z]+\d{3}|[a-z\d]+)"
    app, _ = make_test_app(configured, now)
    async with app_client(app) as client:
        response = await client.get(
            "/leases?hostname=script&vendor=Example%20Vendor&remaining_max_minutes=120&hostname_warning=true"
        )
        assert response.status_code == 200
        assert "Der Kea-Hostname entspricht nicht" in response.text
        assert 'class="column-filter active"' in response.text
        assert "Alle Filter zurücksetzen" in response.text
        assert 'name="remaining_max_minutes" value="120"' in response.text


async def test_empty_remaining_filter_is_ignored(settings, now) -> None:
    configured = settings.model_copy(deep=True)
    configured.web.hostname_regex = r"(iai|elab)-([a-z]+\d{3}|[a-z\d]+)"
    app, _ = make_test_app(configured, now)
    async with app_client(app) as client:
        response = await client.get(
            "/leases?hostname_warning=true&remaining_max_minutes="
        )
        assert response.status_code == 200
        assert 'name="hostname_warning" value="true" checked' in response.text

        refreshed = await client.post(
            "/refresh",
            data={"hostname_warning": "true", "remaining_max_minutes": ""},
            follow_redirects=False,
        )
        assert refreshed.status_code == 303
        assert refreshed.headers["location"] == "/leases?hostname_warning=true"


async def test_all_optional_form_values_may_be_empty(settings, now) -> None:
    app, _ = make_test_app(settings, now)
    empty_fields = {
        "subnet": "",
        "per_page": "",
        "hostname": "",
        "ip": "",
        "mac": "",
        "vendor": "",
        "remaining_max_minutes": "",
    }
    async with app_client(app) as client:
        response = await client.get("/leases", params=empty_fields)
        assert response.status_code == 200

        refreshed = await client.post(
            "/refresh", data=empty_fields, follow_redirects=False
        )
        assert refreshed.status_code == 303
        assert refreshed.headers["location"] == "/leases"


@pytest.mark.parametrize(
    ("parameter", "value"),
    [
        ("remaining_max_minutes", "invalid"),
        ("remaining_max_minutes", "0"),
        ("subnet", "invalid"),
        ("subnet", "0"),
    ],
)
async def test_invalid_optional_numbers_return_422(
    settings, now, parameter: str, value: str
) -> None:
    app, _ = make_test_app(settings, now)
    async with app_client(app) as client:
        response = await client.get("/leases", params={parameter: value})
        assert response.status_code == 422


async def test_unavailable_page_and_readiness(settings, now) -> None:
    app, _ = make_test_app(settings, now, fail=True)
    async with app_client(app) as client:
        response = await client.get("/")
        assert response.status_code == 503
        assert "Lease-Daten sind derzeit nicht verfügbar" in response.text
        assert (await client.get("/health/ready")).status_code == 503
