from __future__ import annotations

from importlib.metadata import version

from lease_lurker import __version__
from lease_lurker.web import create_app


def test_runtime_version_comes_from_package_metadata(settings) -> None:
    assert __version__ == version("lease-lurker")
    assert create_app(settings).version == __version__
