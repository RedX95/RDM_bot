import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from constants import COMMENT_LIMIT, IDLE_PROJECT_BUTTON_TEXT
from constants import PROJECTS_LOAD_TIMEOUT_SECONDS
from formatters import format_confirmation, format_selection_header
from keyboards import build_activities_keyboard, build_confirmation_keyboard
from keyboards import build_date_keyboard, build_empty_project_issues_keyboard
from keyboards import build_hours_keyboard, build_idle_keyboard, build_issues_keyboard
from keyboards import build_projects_keyboard
from parsers import parse_hours_input, parse_issue_id
from rdm_client import RedmineApiError, RedmineClient, RedmineConfigError
from states import TimeEntryFlow
from telegram_helpers import answer_safely, delete_message_safely, edit_or_answer


def build_router(redmine: RedmineClient) -> Router:
    router = Router()

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        await message.answer(
            "Привет! Я бот для Redmine/RDM.\n"
            "Нажмите «Выбрать проект» или отправьте номер задачи, например 7875.",
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

    @router.message(StateFilter(None), F.text.regexp(r"^#?\d+$"))
    async def issue_number_shortcut(message: Message, state: FSMContext) -> None:
        issue_id = parse_issue_id(message.text or "")
        if issue_id is not None:
            await start_issue_selection_by_number(message, state, redmine, issue_id)

    @router.callback_query(F.data == "cancel")
    async def cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await state.clear()
        await edit_callback(callback, "Действие отменено.")
        if callback.message:
            await callback.message.answer(
                "Можно начать заново:",
                reply_markup=build_idle_keyboard(),
            )

    @router.callback_query(F.data.startswith("projects_page:"))
    async def projects_page(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        page = int(callback.data.split(":", 1)[1])
        projects = await get_projects_from_state_or_api(callback, state, redmine)
        if not projects:
            return

        await edit_callback(
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
            project = await get_project_by_id(callback, state, redmine, project_id)
            if not project:
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
        projects = await get_projects_from_state_or_api(callback, state, redmine)
        if not projects:
            return

        await state.set_state(TimeEntryFlow.choosing_project)
        await edit_callback(
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
            await edit_callback(callback, error.safe_message)
            return

        await set_issue_data(state, issue)
        await edit_callback(
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

    @router.callback_query(F.data == "hours_custom")
    async def ask_custom_hours(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await state.set_state(TimeEntryFlow.entering_hours)
        await edit_callback(
            callback,
            format_selection_header(await state.get_data())
            + "\n\nВведите время сообщением. Примеры: 45 мин, 1,25, 1:30, 2ч 30м.",
        )

    @router.message(TimeEntryFlow.entering_hours)
    async def enter_custom_hours(message: Message, state: FSMContext) -> None:
        hours = parse_hours_input(message.text or "")
        if hours is None:
            await message.answer(
                "Не понял время. Напишите, например: 45 мин, 1,25, 1:30 или 2ч 30м."
            )
            return

        await state.set_state(TimeEntryFlow.choosing_date)
        await state.update_data(hours=hours, spent_on=date.today().isoformat())
        await message.answer(
            format_selection_header(await state.get_data())
            + "\n\nДата по умолчанию - сегодня. При необходимости измените дату:",
            reply_markup=build_date_keyboard(),
        )

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
            await edit_callback(callback, error.safe_message)
            return

        if not activities:
            await edit_callback(callback, "В Redmine не найдены виды деятельности.")
            return

        await state.set_state(TimeEntryFlow.choosing_activity)
        await state.update_data(activities=activities)
        await edit_callback(
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
            await edit_callback(callback, "Деятельность не найдена. Нажмите /project заново.")
            await state.clear()
            return

        await state.set_state(TimeEntryFlow.writing_comment)
        await state.update_data(
            activity_id=activity_id,
            activity_name=activity.get("name") or str(activity_id),
        )
        await edit_callback(
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
            await edit_callback(
                callback,
                "Не хватает данных для отправки. Нажмите /project и заполните заново.",
            )
            await state.clear()
            return
        except RedmineApiError as error:
            logging.warning("Redmine API error: %s", error)
            await edit_callback(callback, error.safe_message)
            return

        await state.clear()
        entry_id = time_entry.get("id")
        suffix = f" ID: {entry_id}" if entry_id else ""
        await edit_callback(callback, f"Трудозатрата отправлена в Redmine.{suffix}")
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
        await answer_safely(
            message,
            "Не хватает настроек для подключения к Redmine. "
            "Проверьте BOT_TOKEN, RDM_BASE_URL и RDM_API_KEY в .env.",
            reply_markup=build_idle_keyboard(),
        )
        return
    except asyncio.TimeoutError as error:
        logging.warning("Redmine projects load timeout: %s", error)
        await answer_safely(
            message,
            "Redmine долго не отвечает при загрузке проектов. "
            "Проверьте VPN/сеть и попробуйте еще раз.",
            reply_markup=build_idle_keyboard(),
        )
        return
    except RedmineApiError as error:
        logging.warning("Redmine API error: %s", error)
        await answer_safely(message, error.safe_message, reply_markup=build_idle_keyboard())
        return

    if not projects:
        await answer_safely(
            message,
            "Проекты не найдены.",
            reply_markup=build_idle_keyboard(),
        )
        return

    await state.set_state(TimeEntryFlow.choosing_project)
    await state.update_data(projects=projects)
    await hide_idle_keyboard(message, "Открываю выбор проекта...")
    await answer_safely(
        message,
        "Выберите проект:",
        reply_markup=build_projects_keyboard(projects, page=0),
    )


async def start_issue_selection_by_number(
    message: Message,
    state: FSMContext,
    redmine: RedmineClient,
    issue_id: int,
) -> None:
    await state.clear()

    try:
        issue = await redmine.get_issue(issue_id)
    except RedmineApiError as error:
        logging.warning("Redmine API error: %s", error)
        await answer_safely(message, error.safe_message, reply_markup=build_idle_keyboard())
        return

    await set_issue_data(state, issue)
    await hide_idle_keyboard(message, "Открываю задачу...")
    await answer_safely(
        message,
        format_selection_header(await state.get_data())
        + "\n\nВыберите затраченное время:",
        reply_markup=build_hours_keyboard(),
    )


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
        await edit_callback(callback, "Проект не выбран. Нажмите /project заново.")
        await state.clear()
        return

    try:
        issues_page = await redmine.get_issues(project_id=project_id, offset=offset)
    except RedmineApiError as error:
        logging.warning("Redmine API error: %s", error)
        await edit_callback(callback, error.safe_message)
        return

    issues = issues_page["issues"]
    if not issues:
        await edit_callback(
            callback,
            f"В проекте {project_name} задачи не найдены.",
            reply_markup=build_empty_project_issues_keyboard(),
        )
        return

    await edit_callback(
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
    await edit_callback(
        callback,
        format_selection_header(await state.get_data())
        + "\n\nДата по умолчанию - сегодня. При необходимости измените дату:",
        reply_markup=build_date_keyboard(),
    )


async def get_projects_from_state_or_api(
    callback: CallbackQuery,
    state: FSMContext,
    redmine: RedmineClient,
) -> list[dict[str, Any]]:
    data = await state.get_data()
    projects = data.get("projects", [])
    if projects:
        return projects

    try:
        projects = await load_projects(redmine)
    except (asyncio.TimeoutError, RedmineApiError) as error:
        logging.warning("Redmine API error: %s", error)
        await edit_callback(callback, get_safe_error_message(error))
        return []

    await state.update_data(projects=projects)
    return projects


async def get_project_by_id(
    callback: CallbackQuery,
    state: FSMContext,
    redmine: RedmineClient,
    project_id: int,
) -> dict[str, Any] | None:
    try:
        return await redmine.get_project(project_id)
    except RedmineApiError as error:
        logging.warning("Redmine API error: %s", error)
        await edit_callback(callback, error.safe_message)
        await state.clear()
        if callback.message:
            await callback.message.answer(
                "Можно начать заново:",
                reply_markup=build_idle_keyboard(),
            )
        return None


async def set_issue_data(state: FSMContext, issue: dict[str, Any]) -> None:
    issue_id = int(issue["id"])
    project = issue.get("project") if isinstance(issue.get("project"), dict) else {}

    await state.set_state(TimeEntryFlow.choosing_hours)
    await state.update_data(
        project_id=project.get("id"),
        project_name=project.get("name"),
        issue_id=issue_id,
        issue_subject=issue.get("subject") or f"Задача #{issue_id}",
    )


async def hide_idle_keyboard(message: Message, text: str) -> None:
    keyboard_remove_message = await answer_safely(
        message,
        text,
        reply_markup=ReplyKeyboardRemove(),
    )
    if keyboard_remove_message:
        await delete_message_safely(keyboard_remove_message)


async def edit_callback(
    callback: CallbackQuery,
    text: str,
    reply_markup=None,
) -> None:
    if callback.message:
        await edit_or_answer(callback.message, text, reply_markup)


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


def find_by_id(items: list[dict[str, Any]], item_id: int) -> dict[str, Any] | None:
    return next((item for item in items if str(item.get("id")) == str(item_id)), None)
