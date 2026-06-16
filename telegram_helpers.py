import asyncio
import logging

from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup
from aiogram.types import ReplyKeyboardRemove


async def delete_message_safely(message: Message) -> None:
    try:
        await asyncio.wait_for(message.delete(), timeout=5)
    except (asyncio.TimeoutError, TelegramBadRequest, TelegramNetworkError) as error:
        logging.warning("Could not delete Telegram message: %s", error)


async def delete_message_by_id_safely(message: Message, message_id: int) -> None:
    try:
        await asyncio.wait_for(
            message.bot.delete_message(
                chat_id=message.chat.id,
                message_id=message_id,
            ),
            timeout=5,
        )
    except (asyncio.TimeoutError, TelegramBadRequest, TelegramNetworkError) as error:
        logging.warning("Could not delete Telegram message by id: %s", error)


async def answer_safely(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove | None = None,
    parse_mode: str | None = None,
) -> Message | None:
    try:
        return await asyncio.wait_for(
            message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode),
            timeout=8,
        )
    except (asyncio.TimeoutError, TelegramNetworkError) as error:
        logging.warning("Could not send Telegram message: %s", error)
        return None


async def answer_callback_safely(
    callback: CallbackQuery,
    text: str | None = None,
    show_alert: bool | None = None,
) -> None:
    try:
        await asyncio.wait_for(
            callback.answer(text=text, show_alert=show_alert),
            timeout=5,
        )
    except TelegramBadRequest as error:
        if "query is too old" in str(error).lower() or "query id is invalid" in str(error).lower():
            logging.info("Skipped expired Telegram callback answer: %s", error)
            return
        logging.warning("Could not answer Telegram callback: %s", error)
    except (asyncio.TimeoutError, TelegramNetworkError) as error:
        logging.warning("Could not answer Telegram callback: %s", error)


async def replace_message_safely(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove | None = None,
    parse_mode: str | None = None,
) -> Message | None:
    if not isinstance(reply_markup, (ReplyKeyboardMarkup, ReplyKeyboardRemove)):
        try:
            return await asyncio.wait_for(
                message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode),
                timeout=8,
            )
        except TelegramBadRequest as error:
            if "message is not modified" in str(error).lower():
                return message
            logging.warning("Could not edit Telegram message: %s", error)
        except (asyncio.TimeoutError, TelegramNetworkError) as error:
            logging.warning("Could not edit Telegram message: %s", error)

    new_message = await answer_safely(message, text, reply_markup, parse_mode=parse_mode)
    if new_message:
        await delete_message_safely(message)
    return new_message


async def edit_message_by_id_safely(
    message: Message,
    message_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
) -> Message | None:
    try:
        return await asyncio.wait_for(
            message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            ),
            timeout=8,
        )
    except TelegramBadRequest as error:
        if "message is not modified" in str(error).lower():
            return None
        logging.warning("Could not edit Telegram message by id: %s", error)
        return None
    except (asyncio.TimeoutError, TelegramNetworkError) as error:
        logging.warning("Could not edit Telegram message by id: %s", error)
        return None
