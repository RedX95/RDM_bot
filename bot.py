import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramNetworkError
from aiogram.fsm.storage.memory import MemoryStorage

from config import load_settings
from handlers import build_router
from user_store import UserStore


TELEGRAM_RECONNECT_DELAY_SECONDS = 10


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = load_settings()
    bot = Bot(token=settings.bot_token)
    dispatcher = Dispatcher(storage=MemoryStorage())

    user_store = UserStore()

    dispatcher.include_router(
        build_router(
            rdm_base_url=settings.rdm_base_url,
            user_store=user_store,
        )
    )

    while True:
        try:
            await dispatcher.start_polling(bot)
            break
        except TelegramNetworkError as error:
            logging.warning(
                "Telegram API недоступен: %s. Повторная попытка через %s сек.",
                error,
                TELEGRAM_RECONNECT_DELAY_SECONDS,
            )
            await asyncio.sleep(TELEGRAM_RECONNECT_DELAY_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
