import asyncio

from aiogram import Bot

from config import load_settings
from constants import BOT_PROFILE_DESCRIPTION, BOT_PROFILE_SHORT_DESCRIPTION


async def main() -> None:
    settings = load_settings()
    bot = Bot(token=settings.bot_token)

    try:
        await bot.set_my_short_description(
            short_description=BOT_PROFILE_SHORT_DESCRIPTION,
        )
        await bot.set_my_description(
            description=BOT_PROFILE_DESCRIPTION,
        )
    finally:
        await bot.session.close()

    print("Описание профиля Telegram-бота обновлено.")


if __name__ == "__main__":
    asyncio.run(main())
