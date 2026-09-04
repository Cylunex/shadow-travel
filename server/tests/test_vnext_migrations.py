from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_vnext_upgrade_downgrade_preserves_legacy_tables(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migration.sqlite'}"
    monkeypatch.setenv("TRAVEL_DATABASE_URL", url)
    monkeypatch.setenv("TRAVEL_ENVIRONMENT", "development")
    config = Config("alembic.ini")
    command.upgrade(config, "20260904_0006")
    command.upgrade(config, "head")
    engine = create_engine(url)
    tables = inspect(engine).get_table_names()
    assert "travel_runs" in tables and "travel_stop_outcomes" in tables
    assert {
        "travel_agent_resource_grants",
        "travel_agent_reviews",
        "travel_agent_review_revisions",
    } <= set(tables)
    assert next(
        c for c in inspect(engine).get_columns("travel_places") if c["name"] == "longitude"
    )["nullable"]
    engine.dispose()
    command.downgrade(config, "20260904_0006")
    command.upgrade(config, "head")
