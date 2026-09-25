from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
from fastapi import FastAPI
from pydantic import SecretStr

from lease_lurker.service import LeaseService
from lease_lurker.vendor import VendorLookup
from lease_lurker.web import create_app

from .conftest import FakeProvider, NoNames, make_lease

TOKEN = "test-api-token-with-at-least-32-characters"


@asynccontextmanager
async def app_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            yield client


def make_api_app(settings, now, *, leases=None, fail: bool = False, clock=None):
    configured = settings.model_copy(deep=True)
    configured.api.token = SecretStr(TOKEN)
    provider = FakeProvider(leases or [make_lease(now)], fail=fail)
    service = LeaseService(
        provider,
        configured,
        VendorLookup({6: {"001122": "Example Vendor"}}),
        NoNames(),
        clock=clock or (lambda: now),
    )
    return create_app(configured, service), provider


def authorization(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_api_is_disabled_without_token_but_docs_remain_available(
    settings, now
) -> None:
    provider = FakeProvider([make_lease(now)])
    service = LeaseService(
        provider, settings, VendorLookup({}), NoNames(), clock=lambda: now
    )
    app = create_app(settings, service)
    async with app_client(app) as client:
        response = await client.get("/api/v1/leases")
        assert response.status_code == 503
        assert provider.calls == 0
        assert (await client.get("/api/docs")).status_code == 200
        assert (await client.get("/api/openapi.json")).status_code == 200


async def test_api_requires_valid_bearer_token(settings, now) -> None:
    app, provider = make_api_app(settings, now)
    async with app_client(app) as client:
        missing = await client.get("/api/v1/leases")
        invalid = await client.get(
            "/api/v1/leases", headers=authorization("wrong-token")
        )
        assert missing.status_code == 401
        assert invalid.status_code == 401
        assert missing.headers["www-authenticate"] == "Bearer"
        assert provider.calls == 0


async def test_api_returns_enriched_lease_and_pagination(settings, now) -> None:
    configured = settings.model_copy(deep=True)
    configured.web.hostname_regex = r"(iai|elab)-([a-z]+\d{3}|[a-z\d]+)"
    configured.api.token = SecretStr(TOKEN)
    provider = FakeProvider([make_lease(now, hostname="iai-pc042")])
    service = LeaseService(
        provider,
        configured,
        VendorLookup({6: {"001122": "Example Vendor"}}),
        NoNames(),
        clock=lambda: now,
    )
    app = create_app(configured, service)

    async with app_client(app) as client:
        response = await client.get(
            "/api/v1/leases", params={"q": "pc042"}, headers=authorization()
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["pagination"] == {
        "page": 1,
        "per_page": 50,
        "pages": 1,
        "total": 1,
    }
    assert payload["snapshot"] == {
        "refreshed_at": "2026-09-07T12:00:00Z",
        "stale": False,
    }
    assert payload["items"][0] == {
        "ip_address": "192.0.2.42",
        "hostname": "iai-pc042",
        "device_name": None,
        "mac_address": "00:11:22:33:44:55",
        "vendor": "Example Vendor",
        "subnet": {"id": 1, "prefix": "192.0.2.0/24", "name": "Office"},
        "starts_at": "2026-09-07T12:00:00Z",
        "expires_at": "2026-09-07T13:00:00Z",
        "valid_lifetime_seconds": 3600,
        "remaining_seconds": 0,
        "state": 0,
        "hostname_valid": True,
    }


async def test_api_search_filters_and_all_paging(settings, now) -> None:
    leases = [
        make_lease(now, hostname="iai-pc042"),
        make_lease(
            now,
            hostname="other-client",
            ip="203.0.113.9",
            mac=None,
            subnet_id=3,
        ),
    ]
    app, _ = make_api_app(settings, now, leases=leases)
    async with app_client(app) as client:
        by_ip = await client.get(
            "/api/v1/leases",
            params={"q": "203.0.113", "per_page": "all"},
            headers=authorization(),
        )
        unknown_subnet = await client.get(
            "/api/v1/leases", params={"subnet": 2}, headers=authorization()
        )

    assert by_ip.status_code == 200
    assert [item["hostname"] for item in by_ip.json()["items"]] == ["other-client"]
    assert by_ip.json()["pagination"] == {
        "page": 1,
        "per_page": None,
        "pages": 1,
        "total": 1,
    }
    assert unknown_subnet.json()["items"] == []


async def test_api_validates_paging(settings, now) -> None:
    app, _ = make_api_app(settings, now)
    async with app_client(app) as client:
        for value in ("0", "201", "invalid"):
            response = await client.get(
                "/api/v1/leases",
                params={"per_page": value},
                headers=authorization(),
            )
            assert response.status_code == 422


async def test_api_marks_stale_snapshot_and_returns_503_without_one(
    settings, now
) -> None:
    current = [now]
    app, provider = make_api_app(settings, now, clock=lambda: current[0])
    async with app_client(app) as client:
        first = await client.get("/api/v1/leases", headers=authorization())
        assert first.status_code == 200
        provider.fail = True
        current[0] += timedelta(seconds=31)
        stale = await client.get("/api/v1/leases", headers=authorization())
        assert stale.status_code == 200
        assert stale.json()["snapshot"]["stale"] is True

    failed_app, _ = make_api_app(settings, now, fail=True)
    async with app_client(failed_app) as client:
        unavailable = await client.get("/api/v1/leases", headers=authorization())
        assert unavailable.status_code == 503


async def test_openapi_documents_bearer_security(settings, now) -> None:
    app, _ = make_api_app(settings, now)
    async with app_client(app) as client:
        schema = (await client.get("/api/openapi.json")).json()

    operation = schema["paths"]["/api/v1/leases"]["get"]
    assert operation["security"] == [{"HTTPBearer": []}]
    assert schema["components"]["securitySchemes"]["HTTPBearer"] == {
        "type": "http",
        "scheme": "bearer",
    }
