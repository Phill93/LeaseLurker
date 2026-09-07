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
    monkeypatch.setenv("LEASELURKER_LOG_LEVEL", "debug")
    loaded = load_settings(config)
    assert str(loaded.kea.url) == "http://from-env:9000/"
    assert loaded.visible_subnet_ids == [7]
    assert loaded.log_level == "debug"


def test_missing_config_uses_safe_defaults(tmp_path: Path) -> None:
    loaded = load_settings(tmp_path / "missing.yaml")
    assert loaded.visible_subnet_ids == []
    assert loaded.web.default_locale == "de"


@pytest.mark.parametrize(
    "raw",
    [
        {"kea": {"username": "user"}},
        {"cache": {"ttl_seconds": 31, "stale_after_seconds": 30}},
        {"subnets": [{"id": 1}, {"id": 1}]},
        {"web": {"default_locale": "fr"}},
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
