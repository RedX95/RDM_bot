import asyncio
import logging

from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.types import InlineKeyboardMarkup, Message, ReplyKeyboardMarkup
from aiogram.types import ReplyKeyboardRemove


async def delete_message_safely(message: Message) -> None:
    try:
        await asyncio.wait_for(message.delete(), timeout=5)
    except (asyncio.TimeoutError, TelegramBadRequest, TelegramNetworkError) as error:
        logging.warning("Could not delete Telegram message: %s", error)


async def edit_or_answer(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    try:
        await asyncio.wait_for(
            message.edit_text(text, reply_markup=reply_markup),
            timeout=8,
        )
    except TelegramBadRequest as error:
        if "message is not modified" in str(error).lower():
            return
        raise
    except (asyncio.TimeoutError, TelegramNetworkError) as error:
        logging.warning("Could not edit Telegram message: %s", error)


async def answer_safely(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove | None = None,
) -> Message | None:
    try:
        return await asyncio.wait_for(
            message.answer(text, reply_markup=reply_markup),
            timeout=8,
        )
    except (asyncio.TimeoutError, TelegramNetworkError) as error:
        logging.warning("Could not send Telegram message: %s", error)
        return None
