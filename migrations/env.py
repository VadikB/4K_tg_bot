import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import Settings
from app.models import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
database_url_override = config.attributes.get("database_url_override")
config.set_main_option("sqlalchemy.url", database_url_override or Settings().database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(config.get_section(config.config_ini_section) or {})
    async with connectable.connect() as connection:
        def run(sync_connection: object) -> None:
            context.configure(connection=sync_connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()

        await connection.run_sync(run)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())

