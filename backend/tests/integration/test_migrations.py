from alembic import command
from alembic.config import Config


def test_models_match_migrations(alembic_cfg: Config) -> None:
    """Fails when a model changed but nobody generated a migration for it.

    Fix: `alembic revision --autogenerate -m "describe the change"`, then review the file.
    """
    command.check(alembic_cfg)


def test_migrations_downgrade_and_upgrade_cleanly(alembic_cfg: Config) -> None:
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
