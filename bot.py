import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from dotenv import load_dotenv

from rdm_client import RedmineApiError, RedmineClient, RedmineConfigError

PROJECTS_PER_PAGE = 10
ISSUES_PER_PAGE = 10
COMMENT_LIMIT = 1024
PROJECTS_LOAD_TIMEOUT_SECONDS = 8
IDLE_PROJECT_BUTTON_TEXT = "Выбрать проект"


@dataclass(frozen=True)
class Settings:
    bot_token: str
    rdm_base_url: str
    rdm_api_key: str


class TimeEntryFlow(StatesGroup):
    choosing_project = State()
    choosing_issue = State()
    choosing_hours = State()
    choosing_date = State()
    choosing_activity = State()
    writing_comment = State()
    confirming = State()


def load_settings() -> Settings:
    load_dotenv()

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    rdm_base_url = os.getenv("RDM_BASE_URL", "").strip()
    rdm_api_key = os.getenv("RDM_API_KEY", "").strip()

    missing = [
        name
        for name, value in (
            ("BOT_TOKEN", bot_token),
            ("RDM_BASE_URL", rdm_base_url),
            ("RDM_API_KEY", rdm_api_key),
        )
        if not value
    ]
    if missing:
        raise RedmineConfigError(
            "Missing required environment variables: " + ", ".join(missing)
        )

    return Settings(
        bot_token=bot_token,
        rdm_base_url=rdm_base_url,
        rdm_api_key=rdm_api_key,
    )


def build_router(redmine: RedmineClient) -> Router:
    router = Router()

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        await message.answer(
            "Привет! Я бот для Redmine/RDM.\n"
            "Нажмите «Выбрать проект», чтобы занести трудозатраты.",
            reply_markup=build_idle_keyboard(),
        )

    @router.message(Command("cancel"))
    async def cancel_command(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer(
            "Действие отменено.",
            reply_markup=build_idle_keyboard(),
        )

    @router.message(Command("project"))
    async def project(message: Message, state: FSMContext) -> None:
        await start_project_selection(message, state, redmine)

    @router.message(F.text == IDLE_PROJECT_BUTTON_TEXT)
    async def project_button(message: Message, state: FSMContext) -> None:
        await start_project_selection(message, state, redmine)

    @router.callback_query(F.data == "cancel")
    async def cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await state.clear()
        await edit_or_answer(
            callback,
            "Действие отменено.",
        )
        if callback.message:
            await callback.message.answer(
                "Можно начать заново:",
                reply_markup=build_idle_keyboard(),
            )

    @router.callback_query(F.data.startswith("projects_page:"))
    async def projects_page(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        page = int(callback.data.split(":", 1)[1])
        data = await state.get_data()
        projects = data.get("projects", [])

        if not projects:
            try:
                projects = await load_projects(redmine)
            except (asyncio.TimeoutError, RedmineApiError) as error:
                logging.warning("Redmine API error: %s", error)
                await edit_or_answer(callback, get_safe_error_message(error))
                return
            await state.update_data(projects=projects)

        await edit_or_answer(
            callback,
            "Выберите проект:",
            reply_markup=build_projects_keyboard(projects, page=page),
        )

    @router.callback_query(F.data.startswith("project:"))
    async def choose_project(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        project_id = int(callback.data.split(":", 1)[1])
        data = await state.get_data()
        project = find_by_id(data.get("projects", []), project_id)

        if not project:
            try:
                project = await redmine.get_project(project_id)
            except RedmineApiError as error:
                logging.warning("Redmine API error: %s", error)
                await edit_or_answer(callback, error.safe_message)
                await state.clear()
                if callback.message:
                    await callback.message.answer(
                        "Можно начать заново:",
                        reply_markup=build_idle_keyboard(),
                    )
                return

        await state.set_state(TimeEntryFlow.choosing_issue)
        await state.update_data(
            project_id=project_id,
            project_name=project.get("name") or str(project_id),
        )
        await show_issues(callback, state, redmine, offset=0)

    @router.callback_query(F.data.startswith("issues_page:"))
    async def issues_page(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        offset = int(callback.data.split(":", 1)[1])
        await show_issues(callback, state, redmine, offset=offset)

    @router.callback_query(F.data == "back_to_projects")
    async def back_to_projects(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        projects = data.get("projects", [])
        if not projects:
            try:
                projects = await load_projects(redmine)
            except (asyncio.TimeoutError, RedmineApiError) as error:
                logging.warning("Redmine API error: %s", error)
                await edit_or_answer(callback, get_safe_error_message(error))
                return
            await state.update_data(projects=projects)
        await state.set_state(TimeEntryFlow.choosing_project)
        await edit_or_answer(
            callback,
            "Выберите проект:",
            reply_markup=build_projects_keyboard(projects, page=0),
        )

    @router.callback_query(F.data.startswith("issue:"))
    async def choose_issue(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        issue_id = int(callback.data.split(":", 1)[1])

        try:
            issue = await redmine.get_issue(issue_id)
        except RedmineApiError as error:
            logging.warning("Redmine API error: %s", error)
            await edit_or_answer(callback, error.safe_message)
            return

        await state.set_state(TimeEntryFlow.choosing_hours)
        await state.update_data(
            issue_id=issue_id,
            issue_subject=issue.get("subject") or f"Задача #{issue_id}",
        )
        await edit_or_answer(
            callback,
            format_selection_header(await state.get_data())
            + "\n\nВыберите затраченное время:",
            reply_markup=build_hours_keyboard(),
        )

    @router.callback_query(F.data.startswith("hours:"))
    async def choose_hours(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        hours = float(callback.data.split(":", 1)[1])
        await state.set_state(TimeEntryFlow.choosing_date)
        await state.update_data(hours=hours, spent_on=date.today().isoformat())
        await show_date_step(callback, state)

    @router.callback_query(F.data.startswith("date_shift:"))
    async def shift_date(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        days = int(callback.data.split(":", 1)[1])
        data = await state.get_data()
        current_date = date.fromisoformat(data.get("spent_on", date.today().isoformat()))
        await state.update_data(spent_on=(current_date + timedelta(days=days)).isoformat())
        await show_date_step(callback, state)

    @router.callback_query(F.data == "date_today")
    async def set_today(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await state.update_data(spent_on=date.today().isoformat())
        await show_date_step(callback, state)

    @router.callback_query(F.data == "date_confirm")
    async def confirm_date(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()

        try:
            activities = await redmine.get_time_entry_activities()
        except RedmineApiError as error:
            logging.warning("Redmine API error: %s", error)
            await edit_or_answer(callback, error.safe_message)
            return

        if not activities:
            await edit_or_answer(callback, "В Redmine не найдены виды деятельности.")
            return

        await state.set_state(TimeEntryFlow.choosing_activity)
        await state.update_data(activities=activities)
        await edit_or_answer(
            callback,
            format_selection_header(await state.get_data())
            + "\n\nВыберите деятельность:",
            reply_markup=build_activities_keyboard(activities),
        )

    @router.callback_query(F.data.startswith("activity:"))
    async def choose_activity(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        activity_id = int(callback.data.split(":", 1)[1])
        data = await state.get_data()
        activity = find_by_id(data.get("activities", []), activity_id)

        if not activity:
            await edit_or_answer(callback, "Деятельность не найдена. Нажмите /project заново.")
            await state.clear()
            return

        await state.set_state(TimeEntryFlow.writing_comment)
        await state.update_data(
            activity_id=activity_id,
            activity_name=activity.get("name") or str(activity_id),
        )
        await edit_or_answer(
            callback,
            format_selection_header(await state.get_data())
            + "\n\nВведите комментарий одним сообщением в Telegram.",
        )

    @router.message(TimeEntryFlow.writing_comment)
    async def write_comment(message: Message, state: FSMContext) -> None:
        comment = (message.text or "").strip()
        if not comment:
            await message.answer("Комментарий не должен быть пустым. Введите текст.")
            return
        if len(comment) > COMMENT_LIMIT:
            await message.answer(
                f"Комментарий слишком длинный. Максимум {COMMENT_LIMIT} символов."
            )
            return

        await state.set_state(TimeEntryFlow.confirming)
        await state.update_data(comment=comment)
        await message.answer(
            format_confirmation(await state.get_data()),
            reply_markup=build_confirmation_keyboard(),
        )

    @router.callback_query(F.data == "submit_time_entry")
    async def submit_time_entry(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()

        try:
            time_entry = await redmine.create_time_entry(
                issue_id=int(data["issue_id"]),
                hours=float(data["hours"]),
                spent_on=str(data["spent_on"]),
                activity_id=int(data["activity_id"]),
                comments=str(data["comment"]),
            )
        except (KeyError, ValueError) as error:
            logging.warning("Broken FSM data: %s", error)
            await edit_or_answer(
                callback,
                "Не хватает данных для отправки. Нажмите /project и заполните заново.",
            )
            await state.clear()
            return
        except RedmineApiError as error:
            logging.warning("Redmine API error: %s", error)
            await edit_or_answer(callback, error.safe_message)
            return

        await state.clear()
        entry_id = time_entry.get("id")
        suffix = f" ID: {entry_id}" if entry_id else ""
        await edit_or_answer(callback, f"Трудозатрата отправлена в Redmine.{suffix}")
        if callback.message:
            await callback.message.answer(
                "Можно занести следующую трудозатрату:",
                reply_markup=build_idle_keyboard(),
            )

    return router


async def start_project_selection(
    message: Message,
    state: FSMContext,
    redmine: RedmineClient,
) -> None:
    await state.clear()

    try:
        projects = await load_projects(redmine)
    except RedmineConfigError as error:
        logging.warning("Configuration error: %s", error)
        await safe_message_answer(
            message,
            "Не хватает настроек для подключения к Redmine. "
            "Проверьте BOT_TOKEN, RDM_BASE_URL и RDM_API_KEY в .env.",
            reply_markup=build_idle_keyboard(),
        )
        return
    except asyncio.TimeoutError as error:
        logging.warning("Redmine projects load timeout: %s", error)
        await safe_message_answer(
            message,
            "Redmine долго не отвечает при загрузке проектов. "
            "Проверьте VPN/сеть и попробуйте еще раз.",
            reply_markup=build_idle_keyboard(),
        )
        return
    except RedmineApiError as error:
        logging.warning("Redmine API error: %s", error)
        await safe_message_answer(
            message,
            error.safe_message,
            reply_markup=build_idle_keyboard(),
        )
        return

    if not projects:
        await safe_message_answer(
            message,
            "Проекты не найдены.",
            reply_markup=build_idle_keyboard(),
        )
        return

    await state.set_state(TimeEntryFlow.choosing_project)
    await state.update_data(projects=projects)
    keyboard_remove_message = await safe_message_answer(
        message,
        "Открываю выбор проекта...",
        reply_markup=ReplyKeyboardRemove(),
    )
    if keyboard_remove_message:
        await delete_message_safely(keyboard_remove_message)
    await safe_message_answer(
        message,
        "Выберите проект:",
        reply_markup=build_projects_keyboard(projects, page=0),
    )


async def delete_message_safely(message: Message) -> None:
    try:
        await asyncio.wait_for(message.delete(), timeout=5)
    except (asyncio.TimeoutError, TelegramBadRequest, TelegramNetworkError) as error:
        logging.warning("Could not delete Telegram message: %s", error)
        return


async def safe_message_answer(
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


async def load_projects(redmine: RedmineClient) -> list[dict[str, Any]]:
    return await asyncio.wait_for(
        redmine.get_projects(),
        timeout=PROJECTS_LOAD_TIMEOUT_SECONDS,
    )


def get_safe_error_message(error: BaseException) -> str:
    if isinstance(error, RedmineApiError):
        return error.safe_message
    if isinstance(error, asyncio.TimeoutError):
        return (
            "Redmine долго не отвечает при загрузке проектов. "
            "Проверьте VPN/сеть и попробуйте еще раз."
        )
    return "Произошла ошибка при обращении к Redmine."


async def show_issues(
    callback: CallbackQuery,
    state: FSMContext,
    redmine: RedmineClient,
    offset: int,
) -> None:
    data = await state.get_data()
    project_id = data.get("project_id")
    project_name = data.get("project_name", "проект")

    if not project_id:
        await edit_or_answer(callback, "Проект не выбран. Нажмите /project заново.")
        await state.clear()
        return

    try:
        issues_page = await redmine.get_issues(project_id=project_id, offset=offset)
    except RedmineApiError as error:
        logging.warning("Redmine API error: %s", error)
        await edit_or_answer(callback, error.safe_message)
        return

    issues = issues_page["issues"]
    if not issues:
        await edit_or_answer(
            callback,
            f"В проекте {project_name} задачи не найдены.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Назад к проектам", callback_data="back_to_projects")],
                    [InlineKeyboardButton(text="Отмена", callback_data="cancel")],
                ]
            ),
        )
        return

    await edit_or_answer(
        callback,
        f"Проект: {project_name}\nВыберите задачу:",
        reply_markup=build_issues_keyboard(
            issues=issues,
            offset=issues_page["offset"],
            limit=issues_page["limit"],
            total_count=issues_page["total_count"],
        ),
    )


async def show_date_step(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await edit_or_answer(
        callback,
        format_selection_header(data)
        + "\n\nДата по умолчанию - сегодня. При необходимости измените дату:",
        reply_markup=build_date_keyboard(),
    )


async def edit_or_answer(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if callback.message:
        try:
            await asyncio.wait_for(
                callback.message.edit_text(text, reply_markup=reply_markup),
                timeout=8,
            )
        except TelegramBadRequest as error:
            if "message is not modified" in str(error).lower():
                return
            raise
        except (asyncio.TimeoutError, TelegramNetworkError) as error:
            logging.warning("Could not edit Telegram message: %s", error)


def build_projects_keyboard(projects: list[dict[str, Any]], page: int) -> InlineKeyboardMarkup:
    total_pages = max(1, (len(projects) + PROJECTS_PER_PAGE - 1) // PROJECTS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * PROJECTS_PER_PAGE
    page_projects = projects[start : start + PROJECTS_PER_PAGE]

    rows = [
        [
            InlineKeyboardButton(
                text=shorten(project.get("name") or str(project.get("id")), 58),
                callback_data=f"project:{project.get('id')}",
            )
        ]
        for project in page_projects
        if project.get("id") is not None
    ]

    navigation = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(text="Назад", callback_data=f"projects_page:{page - 1}")
        )
    if page < total_pages - 1:
        navigation.append(
            InlineKeyboardButton(text="Дальше", callback_data=f"projects_page:{page + 1}")
        )
    if navigation:
        rows.append(navigation)

    rows.append([InlineKeyboardButton(text="Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_issues_keyboard(
    issues: list[dict[str, Any]],
    offset: int,
    limit: int,
    total_count: int,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=shorten(f"#{issue.get('id')} {issue.get('subject') or ''}", 58),
                callback_data=f"issue:{issue.get('id')}",
            )
        ]
        for issue in issues
        if issue.get("id") is not None
    ]

    navigation = []
    if offset > 0:
        previous_offset = max(0, offset - limit)
        navigation.append(
            InlineKeyboardButton(text="Назад", callback_data=f"issues_page:{previous_offset}")
        )
    if offset + limit < total_count:
        navigation.append(
            InlineKeyboardButton(text="Дальше", callback_data=f"issues_page:{offset + limit}")
        )
    if navigation:
        rows.append(navigation)

    rows.append([InlineKeyboardButton(text="Назад к проектам", callback_data="back_to_projects")])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_hours_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1 час", callback_data="hours:1"),
                InlineKeyboardButton(text="1,5 часа", callback_data="hours:1.5"),
            ],
            [
                InlineKeyboardButton(text="2 часа", callback_data="hours:2"),
                InlineKeyboardButton(text="2,5 часа", callback_data="hours:2.5"),
            ],
            [InlineKeyboardButton(text="3 часа", callback_data="hours:3")],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel")],
        ]
    )


def build_date_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="-1 день", callback_data="date_shift:-1"),
                InlineKeyboardButton(text="Сегодня", callback_data="date_today"),
                InlineKeyboardButton(text="+1 день", callback_data="date_shift:1"),
            ],
            [InlineKeyboardButton(text="Подтвердить дату", callback_data="date_confirm")],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel")],
        ]
    )


def build_activities_keyboard(activities: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=shorten(activity.get("name") or str(activity.get("id")), 58),
                callback_data=f"activity:{activity.get('id')}",
            )
        ]
        for activity in activities
        if activity.get("id") is not None
    ]
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отправить", callback_data="submit_time_entry")],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel")],
        ]
    )


def build_idle_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=IDLE_PROJECT_BUTTON_TEXT)]],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Нажмите, чтобы выбрать проект",
    )


def format_selection_header(data: dict[str, Any]) -> str:
    parts = []
    if data.get("project_name"):
        parts.append(f"Проект: {data['project_name']}")
    if data.get("issue_id"):
        parts.append(f"Задача: #{data['issue_id']} {data.get('issue_subject', '')}".strip())
    if data.get("hours"):
        parts.append(f"Часы: {format_hours(float(data['hours']))}")
    if data.get("spent_on"):
        parts.append(f"Дата: {format_date(str(data['spent_on']))}")
    if data.get("activity_name"):
        parts.append(f"Деятельность: {data['activity_name']}")
    return "\n".join(parts)


def format_confirmation(data: dict[str, Any]) -> str:
    return (
        "Проверьте трудозатрату:\n"
        f"{format_selection_header(data)}\n"
        f"Комментарий: {data.get('comment', '')}\n\n"
        "Отправить в Redmine?"
    )


def format_hours(hours: float) -> str:
    if hours.is_integer():
        return f"{int(hours)} ч"
    return f"{str(hours).replace('.', ',')} ч"


def format_date(iso_date: str) -> str:
    parsed = date.fromisoformat(iso_date)
    return parsed.strftime("%d.%m.%Y")


def find_by_id(items: list[dict[str, Any]], item_id: int) -> dict[str, Any] | None:
    return next((item for item in items if str(item.get("id")) == str(item_id)), None)


def shorten(text: str, max_length: int) -> str:
    text = " ".join(str(text).split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"


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
