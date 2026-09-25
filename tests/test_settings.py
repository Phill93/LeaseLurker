from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from lease_lurker.settings import Settings, load_settings


def test_loads_yaml_and_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        "kea:\n  url: http://from-file:8000/\nsubnets:\n  - id: 7\n    visible: true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LEASELURKER_KEA_URL", "http://from-env:9000/")
    monkeypatch.setenv("LEASELURKER_API_TOKEN", "a" * 32)
    monkeypatch.setenv("LEASELURKER_LOG_LEVEL", "debug")
    loaded = load_settings(config)
    assert str(loaded.kea.url) == "http://from-env:9000/"
    assert loaded.visible_subnet_ids == [7]
    assert loaded.log_level == "debug"
    assert loaded.api.token is not None
    assert loaded.api.token.get_secret_value() == "a" * 32


def test_missing_config_uses_safe_defaults(tmp_path: Path) -> None:
    loaded = load_settings(tmp_path / "missing.yaml")
    assert loaded.visible_subnet_ids == []
    assert loaded.web.default_locale == "de"
    assert loaded.web.allowed_page_sizes == (25, 50, 100, 200, None)


def test_web_settings_allow_custom_paging_and_hostname_regex() -> None:
    loaded = Settings.model_validate(
        {
            "web": {
                "page_size": None,
                "page_size_options": [20, 40, None],
                "hostname_regex": r"(iai|elab)-([a-z]+\d{3}|[a-z\d]+)",
            }
        }
    )
    assert loaded.web.allowed_page_sizes == (20, 40, None)
    assert loaded.web.page_size is None


def test_page_size_default_is_added_to_allowed_options() -> None:
    loaded = Settings.model_validate(
        {"web": {"page_size": 10, "page_size_options": [25, None]}}
    )
    assert loaded.web.allowed_page_sizes == (25, None, 10)


@pytest.mark.parametrize(
    "raw",
    [
        {"kea": {"username": "user"}},
        {"cache": {"ttl_seconds": 31, "stale_after_seconds": 30}},
        {"subnets": [{"id": 1}, {"id": 1}]},
        {"web": {"default_locale": "fr"}},
        {"web": {"page_size_options": [25, 25]}},
        {"web": {"page_size_options": [5, None]}},
        {"web": {"hostname_regex": "("}},
        {"api": {"token": "too-short"}},
    ],
)
def test_rejects_invalid_settings(raw: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(raw)


def test_rejects_non_mapping_yaml(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("- invalid\n", encoding="utf-8")
    with pytest.raises(ValueError, match="root"):
        load_settings(config)
