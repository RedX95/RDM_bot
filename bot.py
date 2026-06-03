import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import load_settings
from handlers import build_router
from rdm_client import RedmineClient


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = load_settings()
    bot = Bot(token=settings.bot_token)
    dispatcher = Dispatcher(storage=MemoryStorage())

    async with RedmineClient(
        base_url=settings.rdm_base_url,
        api_key=settings.rdm_api_key,
    ) as redmine:
        dispatcher.include_router(build_router(redmine))
        await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
