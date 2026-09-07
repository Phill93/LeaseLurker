"""Validated application configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

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


class SubnetRule(BaseModel):
    id: int = Field(gt=0)
    visible: bool = False
    name: str | None = Field(default=None, min_length=1, max_length=100)


class WebSettings(BaseModel):
    default_locale: str = "de"
    page_size: int = Field(default=50, ge=10, le=200)

    @model_validator(mode="after")
    def supported_locale(self) -> WebSettings:
        if self.default_locale not in {"de", "en"}:
            raise ValueError("default_locale must be 'de' or 'en'")
        return self


class Settings(BaseModel):
    kea: KeaSettings = Field(default_factory=KeaSettings)
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
    if log_level := os.environ.get("LEASELURKER_LOG_LEVEL"):
        raw["log_level"] = log_level
    return Settings.model_validate(raw)
