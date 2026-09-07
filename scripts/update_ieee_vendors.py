#!/usr/bin/env python3
"""Create the deterministic offline vendor database from IEEE public CSVs."""

from __future__ import annotations

import csv
import io
import json
import urllib.request
from pathlib import Path

SOURCES = {
    6: "https://standards-oui.ieee.org/oui/oui.csv",
    7: "https://standards-oui.ieee.org/oui28/mam.csv",
    9: "https://standards-oui.ieee.org/oui36/oui36.csv",
}
TARGET = Path(__file__).parents[1] / "src/lease_lurker/data/ieee-vendors.json"


def download(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "LeaseLurker/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return response.read().decode("utf-8-sig")


def build_database() -> dict[str, dict[str, str]]:
    database: dict[str, dict[str, str]] = {}
    for length, url in SOURCES.items():
        rows = csv.DictReader(io.StringIO(download(url)))
        records = {
            row["Assignment"].strip().upper(): row["Organization Name"].strip()
            for row in rows
            if row.get("Assignment") and row.get("Organization Name")
        }
        database[str(length)] = dict(sorted(records.items()))
    return database


def main() -> None:
    rendered = json.dumps(
        build_database(), ensure_ascii=False, indent=2, sort_keys=True
    )
    TARGET.write_text(f"{rendered}\n", encoding="utf-8")
    print(f"Updated {TARGET}")


if __name__ == "__main__":
    main()
