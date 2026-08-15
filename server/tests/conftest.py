from __future__ import annotations

from pathlib import Path

import pytest

from shadow_travel.config import Settings


@pytest.fixture
def settings_factory(tmp_path: Path):
    def factory(**overrides: object) -> Settings:
        defaults: dict[str, object] = {
            "environment": "test",
            "root_path": "",
            "public_origin": "http://testserver",
            "database_url": f"sqlite:///{tmp_path / 'travel-test.db'}",
            "cookie_secure": False,
        }
        defaults.update(overrides)
        return Settings(**defaults)

    return factory
