from pathlib import Path

from alembic import command
from alembic.config import Config

from app.observability.storage import History


def migrate(history: History) -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    with history.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
