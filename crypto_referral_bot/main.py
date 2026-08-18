import asyncio
import logging
import logging.handlers
from pathlib import Path

from aiogram import Bot, Dispatcher

import config
from database import init_db
from handlers import router


def setup_logging():
    config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.handlers.RotatingFileHandler(
                config.LOG_PATH, maxBytes=5_000_000, backupCount=3
            ),
            logging.StreamHandler(),
        ],
    )


async def on_startup():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    await init_db()


async def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    if not config.BOT_TOKEN:
        logger.error("BOT_TOKEN not set in .env")
        return

    await on_startup()

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    logger.info("Bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
