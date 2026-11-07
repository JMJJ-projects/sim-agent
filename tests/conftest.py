"""Shared pytest configuration."""

from functools import lru_cache

import pytest

from simagent.runners.docker import docker_status


@lru_cache(maxsize=1)
def _docker_ready() -> tuple[bool, str]:
    daemon, image, detail = docker_status()
    return daemon and image, detail


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip ``@pytest.mark.docker`` tests when Docker or the sandbox image is missing (R-SBX-9)."""
    docker_items = [item for item in items if "docker" in item.keywords]
    if not docker_items:
        return
    ready, detail = _docker_ready()
    if ready:
        return
    skip = pytest.mark.skip(reason=f"Docker sandbox not available: {detail}")
    for item in docker_items:
        item.add_marker(skip)
