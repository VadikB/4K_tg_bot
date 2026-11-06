import asyncio
import logging

from aiogram import Bot

from app.bot import build_dispatcher
from app.config import Settings


async def run() -> None:
    settings = Settings()
    settings.validate_runtime()
    logging.basicConfig(level=settings.log_level)
    bot = Bot(token=settings.telegram_bot_token)
    try:
        await build_dispatcher().start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run())

