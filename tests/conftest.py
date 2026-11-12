"""MeshScout test suite configuration and handle cleanup fixtures."""

import gc
import pytest

from meshscout.web.app import _local_telemetry_cache, _local_tower_registry


@pytest.fixture(autouse=True)
def cleanup_sqlite_handles():
    """Ensure thread-local SQLite registries and caches are cleanly closed after each test."""
    yield
    reg = getattr(_local_tower_registry, "registry", None)
    if reg is not None:
        try:
            reg.close()
        except Exception:
            pass
        _local_tower_registry.registry = None
        _local_tower_registry.path = None

    cache = getattr(_local_telemetry_cache, "cache", None)
    if cache is not None:
        try:
            cache.close()
        except Exception:
            pass
        _local_telemetry_cache.cache = None
        _local_telemetry_cache.path = None

    gc.collect()
