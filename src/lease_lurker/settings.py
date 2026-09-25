"""Validated application configuration."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, Field, HttpUrl, SecretStr, model_validator


class KeaSettings(BaseModel):
    url: HttpUrl = HttpUrl("http://host.docker.internal:8000/")
    username: str | None = None
    password: SecretStr | None = None
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    @model_validator(mode="after")
    def credentials_are_complete(self) -> KeaSettings:
        if (self.username is None) != (self.password is None):
            raise ValueError("Kea username and password must be configured together")
        return self


class CacheSettings(BaseModel):
    ttl_seconds: int = Field(default=30, ge=1, le=3600)
    stale_after_seconds: int = Field(default=300, ge=1, le=86400)

    @model_validator(mode="after")
    def stale_period_is_longer_than_ttl(self) -> CacheSettings:
        if self.stale_after_seconds < self.ttl_seconds:
            raise ValueError("stale_after_seconds must be at least ttl_seconds")
        return self


class ApiSettings(BaseModel):
    token: Annotated[SecretStr, Field(min_length=32)] | None = None


class SubnetRule(BaseModel):
    id: int = Field(gt=0)
    visible: bool = False
    name: str | None = Field(default=None, min_length=1, max_length=100)


class WebSettings(BaseModel):
    default_locale: str = "de"
    page_size: Annotated[int, Field(ge=10, le=200)] | None = 50
    page_size_options: list[Annotated[int, Field(ge=10, le=200)] | None] = Field(
        default_factory=lambda: [25, 50, 100, 200, None]
    )
    hostname_regex: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def supported_locale(self) -> WebSettings:
        if self.default_locale not in {"de", "en"}:
            raise ValueError("default_locale must be 'de' or 'en'")
        if len(self.page_size_options) != len(set(self.page_size_options)):
            raise ValueError("page_size_options must be unique")
        if self.hostname_regex is not None:
            try:
                re.compile(self.hostname_regex, re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"hostname_regex is invalid: {exc}") from exc
        return self

    @property
    def allowed_page_sizes(self) -> tuple[int | None, ...]:
        values = list(self.page_size_options)
        if self.page_size not in values:
            values.append(self.page_size)
        return tuple(values)


class Settings(BaseModel):
    kea: KeaSettings = Field(default_factory=KeaSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    subnets: list[SubnetRule] = Field(default_factory=list)
    web: WebSettings = Field(default_factory=WebSettings)
    log_level: str = "INFO"

    @model_validator(mode="after")
    def subnet_ids_are_unique(self) -> Settings:
        ids = [rule.id for rule in self.subnets]
        if len(ids) != len(set(ids)):
            raise ValueError("subnet IDs must be unique")
        return self

    @property
    def visible_subnet_ids(self) -> list[int]:
        return [rule.id for rule in self.subnets if rule.visible]

    @property
    def subnet_name_overrides(self) -> dict[int, str]:
        return {rule.id: rule.name for rule in self.subnets if rule.name is not None}


def load_settings(path: Path | None = None) -> Settings:
    """Load YAML settings and apply deployment environment overrides."""
    config_path = path or Path(
        os.environ.get("LEASELURKER_CONFIG", "/etc/lease-lurker/config.yaml")
    )
    raw: dict[str, Any] = {}
    if config_path.exists():
        parsed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if parsed is not None:
            if not isinstance(parsed, dict):
                raise ValueError("configuration root must be a mapping")
            raw = parsed

    kea = raw.setdefault("kea", {})
    if not isinstance(kea, dict):
        raise ValueError("kea configuration must be a mapping")
    overrides = {
        "url": os.environ.get("LEASELURKER_KEA_URL"),
        "username": os.environ.get("LEASELURKER_KEA_USERNAME"),
        "password": os.environ.get("LEASELURKER_KEA_PASSWORD"),
    }
    for key, value in overrides.items():
        if value is not None:
            kea[key] = value
    api = raw.setdefault("api", {})
    if not isinstance(api, dict):
        raise ValueError("api configuration must be a mapping")
    if api_token := os.environ.get("LEASELURKER_API_TOKEN"):
        api["token"] = api_token
    if log_level := os.environ.get("LEASELURKER_LOG_LEVEL"):
        raw["log_level"] = log_level
    return Settings.model_validate(raw)
