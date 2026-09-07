"""Executable entry point."""

from __future__ import annotations

import logging

import uvicorn

from lease_lurker.settings import load_settings
from lease_lurker.web import create_app


def run() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    uvicorn.run(create_app(settings), host="0.0.0.0", port=8080)


if __name__ == "__main__":
    run()
