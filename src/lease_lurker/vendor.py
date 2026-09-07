"""Offline IEEE MAC assignment lookup."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any


class VendorLookup:
    """Longest-prefix matcher over bundled IEEE registry data."""

    def __init__(self, records: dict[int, dict[str, str]] | None = None) -> None:
        self._records = records if records is not None else self._load_records()

    @staticmethod
    def _load_records() -> dict[int, dict[str, str]]:
        resource = files("lease_lurker.data").joinpath("ieee-vendors.json")
        raw: Any = json.loads(resource.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("IEEE vendor database must be an object")
        return {
            int(length): {str(prefix): str(name) for prefix, name in values.items()}
            for length, values in raw.items()
            if isinstance(values, dict)
        }

    def lookup(self, mac_address: str) -> str | None:
        compact = mac_address.replace(":", "").replace("-", "").replace(".", "").upper()
        for length in sorted(self._records, reverse=True):
            if vendor := self._records[length].get(compact[:length]):
                return vendor
        return None
