from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from backend.db import make_engine


def test_migrations_round_trip(tmp_path, monkeypatch):
    from backend.config import get_settings

    url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("ATTENDANCE_DATABASE_URL", url)
    get_settings.cache_clear()
    config = Config(str(Path("alembic.ini").resolve()))
    try:
        command.upgrade(config, "head")
        command.check(config)
        engine = make_engine(url)
        assert "face_templates" in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM people")).scalar() == 0
        engine.dispose()
        command.downgrade(config, "base")
        command.upgrade(config, "head")
    finally:
        get_settings.cache_clear()
