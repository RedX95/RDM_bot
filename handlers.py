import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date, timedelta
from html import escape
from typing import Any, AsyncIterator

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from constants import COMMENT_LIMIT, DEFAULT_ACTIVITY_NAME, FAVORITE_PROJECTS_BUTTON_TEXT
from constants import FAVORITES_SETUP_BUTTON_TEXT
from constants import IDLE_PROJECT_BUTTON_TEXT, LOGIN_BUTTON_TEXT, TRACKING_BUTTON_TEXT
from constants import FAVORITE_PROJECTS_LIMIT, FAVORITE_PROJECTS_SETUP_LIMIT
from constants import PROJECTS_LOAD_TIMEOUT_SECONDS
from constants import RECENT_ISSUES_BUTTON_TEXT, RECENT_ISSUES_LIMIT
from constants import START_TEXT_LOGGED_IN, START_TEXT_LOGGED_OUT
from formatters import format_confirmation, format_selection_header
from keyboards import build_activities_keyboard, build_confirmation_keyboard
from keyboards import build_date_keyboard, build_empty_project_issues_keyboard
from keyboards import build_favorite_projects_keyboard
from keyboards import build_favorites_setup_keyboard
from keyboards import build_hours_keyboard, build_idle_keyboard, build_issues_keyboard
from keyboards import build_login_keyboard
from keyboards import build_projects_keyboard, build_recent_issues_keyboard
from keyboards import build_time_entry_done_keyboard
from keyboards import build_tracking_start_keyboard
from parsers import parse_hours_comment_input, parse_issue_id
from rdm_client import RedmineApiError, RedmineClient, RedmineConfigError
from states import RegistrationFlow, TimeEntryFlow
from telegram_helpers import answer_callback_safely, answer_safely
from telegram_helpers import delete_message_by_id_safely
from telegram_helpers import delete_message_safely, edit_message_by_id_safely
from telegram_helpers import replace_message_safely
from user_store import UserStore


def build_router(rdm_base_url: str, user_store: UserStore) -> Router:
    router = Router()

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        if is_logged_in(message, user_store):
            text = START_TEXT_LOGGED_IN
        else:
            text = START_TEXT_LOGGED_OUT

        await message.answer(text, reply_markup=keyboard_for_message(message, user_store))

    @router.message(Command("login"))
    @router.message(F.text == LOGIN_BUTTON_TEXT)
    @router.message(F.text == "Войти")
    async def login(message: Message, state: FSMContext) -> None:
        await delete_prompt_from_state(message, state)
        await state.clear()
        await state.set_state(RegistrationFlow.entering_api_key)
        if message.text in {LOGIN_BUTTON_TEXT, "Войти"}:
            await delete_message_safely(message)
        prompt_message = await answer_safely(
            message,
            "🔑 Отправьте ваш Redmine API key одним сообщением.\n"
            "Я проверю ключ и привяжу его только к вашему Telegram ID.\n\n"
            "↩️ Отмена: /cancel",
            reply_markup=ReplyKeyboardRemove(),
        )
        if prompt_message:
            await state.update_data(prompt_message_id=prompt_message.message_id)

    @router.message(RegistrationFlow.entering_api_key)
    async def save_api_key(message: Message, state: FSMContext) -> None:
        api_key = (message.text or "").strip()
        if not api_key:
            await message.answer("🔎 API key не должен быть пустым. Отправьте ключ или /cancel.")
            return

        if message.from_user is None:
            await message.answer("⚠️ Не удалось определить Telegram-пользователя.")
            return

        await delete_message_safely(message)
        await delete_prompt_from_state(message, state)

        try:
            async with RedmineClient(rdm_base_url, api_key) as redmine:
                user = await redmine.get_current_user()
        except (RedmineConfigError, RedmineApiError) as error:
            logging.warning("Redmine login error: %s", error)
            safe_message = getattr(error, "safe_message", str(error))
            await answer_safely(
                message,
                "🚪 Не удалось войти с этим API key.\n"
                f"{safe_message}\n\n"
                "Проверьте ключ и отправьте его еще раз или нажмите /cancel.",
            )
            return

        user_store.save_api_key(message.from_user.id, api_key)
        await state.clear()
        async with RedmineClient(rdm_base_url, api_key) as redmine:
            await start_favorites_setup(
                message=message,
                state=state,
                redmine=redmine,
                user_store=user_store,
                telegram_user_id=message.from_user.id,
                intro_text=(
                    f"✅ Вход выполнен: {format_redmine_user(user)}.\n\n"
                    "⭐ Отметьте проекты, которые должны быть избранными. "
                    "Их можно будет выбирать быстрее при трекинге времени."
                ),
            )

    @router.message(Command("logout"))
    async def logout(message: Message, state: FSMContext) -> None:
        await state.clear()
        if message.from_user:
            user_store.delete_api_key(message.from_user.id)
        await message.answer(
            "🚪 Вы вышли из Redmine-аккаунта.",
            reply_markup=build_login_keyboard(),
        )

    @router.message(Command("me"))
    async def me(message: Message, state: FSMContext) -> None:
        async with redmine_from_message(message, state, rdm_base_url, user_store) as redmine:
            if redmine is None:
                return

            try:
                user = await redmine.get_current_user()
            except RedmineApiError as error:
                logging.warning("Redmine API error: %s", error)
                await answer_safely(message, f"⚠️ {error.safe_message}", reply_markup=build_idle_keyboard())
                return

        await message.answer(
            f"👤 Вы вошли как: {format_redmine_user(user)}.",
            reply_markup=build_idle_keyboard(),
        )

    @router.message(Command("cancel"))
    async def cancel_command(message: Message, state: FSMContext) -> None:
        await delete_prompt_from_state(message, state)
        await state.clear()
        if is_logged_in(message, user_store):
            await answer_safely(
                message,
                "↩️ Отменил. Возвращаю в главное меню.",
                reply_markup=build_idle_keyboard(),
            )
            return

        await message.answer("↩️ Отменил. Можно войти заново.", reply_markup=build_login_keyboard())

    @router.message(Command("project"))
    async def project(message: Message, state: FSMContext) -> None:
        async with redmine_from_message(message, state, rdm_base_url, user_store) as redmine:
            if redmine is not None:
                await start_project_selection(message, state, redmine, user_store)

    @router.message(F.text == IDLE_PROJECT_BUTTON_TEXT)
    @router.message(F.text == TRACKING_BUTTON_TEXT)
    @router.message(F.text == "Выбрать проект")
    async def project_button(message: Message, state: FSMContext) -> None:
        await delete_message_safely(message)
        async with redmine_from_message(message, state, rdm_base_url, user_store) as redmine:
            if redmine is not None:
                await start_project_selection(message, state, redmine, user_store)

    @router.callback_query(F.data == "tracking_start")
    async def tracking_start(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        if await start_repeat_time_entry_from_callback(callback, state):
            return

        async with redmine_from_callback(callback, state, rdm_base_url, user_store) as redmine:
            if redmine is not None:
                await start_project_selection_from_callback(callback, state, redmine, user_store)

    @router.message(Command("favorites"))
    @router.message(F.text == FAVORITE_PROJECTS_BUTTON_TEXT)
    async def favorite_projects_button(message: Message, state: FSMContext) -> None:
        if message.text == FAVORITE_PROJECTS_BUTTON_TEXT:
            await delete_message_safely(message)
        await show_favorite_projects(message, state, user_store)

    @router.message(Command("setup_favorites"))
    @router.message(F.text == FAVORITES_SETUP_BUTTON_TEXT)
    async def favorites_setup_button(message: Message, state: FSMContext) -> None:
        if message.text == FAVORITES_SETUP_BUTTON_TEXT:
            await delete_message_safely(message)
        async with redmine_from_message(message, state, rdm_base_url, user_store) as redmine:
            if redmine is not None and message.from_user is not None:
                await start_favorites_setup(
                    message=message,
                    state=state,
                    redmine=redmine,
                    user_store=user_store,
                    telegram_user_id=message.from_user.id,
                    intro_text=(
                        "⚙️ Настройка избранного\n\n"
                        "Нажмите на проект, чтобы переключить его статус: "
                        "⭐ избранный, ☆ обычный."
                    ),
                )

    @router.message(Command("recent"))
    @router.message(F.text == RECENT_ISSUES_BUTTON_TEXT)
    async def recent_issues_button(message: Message, state: FSMContext) -> None:
        if message.text == RECENT_ISSUES_BUTTON_TEXT:
            await delete_message_safely(message)
        await show_recent_issues(message, state, user_store)

    @router.message(StateFilter(None), F.text.regexp(r"^#?\d+$"))
    async def issue_number_shortcut(message: Message, state: FSMContext) -> None:
        issue_id = parse_issue_id(message.text or "")
        if issue_id is None:
            return

        async with redmine_from_message(message, state, rdm_base_url, user_store) as redmine:
            if redmine is not None:
                await start_issue_selection_by_number(message, state, redmine, issue_id, user_store)

    @router.callback_query(F.data == "cancel")
    async def cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback, "Отменено")
        await state.clear()
        if user_store.get_api_key(callback.from_user.id) and callback.message:
            await edit_callback(
                callback,
                "↩️ Отменил. Выберите следующий раздел:",
                reply_markup=build_tracking_start_keyboard(),
            )
            return

        await edit_callback(
            callback,
            "↩️ Отменил. Для начала войдите в Redmine.",
            reply_markup=build_login_keyboard(),
        )

    @router.callback_query(F.data.startswith("favorites_page:"))
    async def favorites_setup_page(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        page = int(callback.data.split(":", 1)[1])
        await show_favorites_setup_page(callback, state, user_store, page)

    @router.callback_query(F.data.startswith("favorites_toggle:"))
    async def favorites_setup_toggle(callback: CallbackQuery, state: FSMContext) -> None:
        parts = callback.data.split(":")
        project_id = int(parts[1])
        page = int(parts[2])
        data = await state.get_data()
        project = find_by_id(data.get("projects", []), project_id)
        if not project:
            await answer_callback_safely(callback, "Проект не найден", show_alert=True)
            return

        if user_store.is_favorite_project(callback.from_user.id, project_id):
            user_store.delete_favorite_project(callback.from_user.id, project_id)
            await answer_callback_safely(callback, "Убрано из избранного")
        else:
            user_store.save_favorite_project(
                callback.from_user.id,
                project_id,
                str(project.get("name") or project_id),
            )
            await answer_callback_safely(callback, "Добавлено в избранное")

        await show_favorites_setup_page(callback, state, user_store, page)

    @router.callback_query(F.data == "favorites_done")
    async def favorites_setup_done(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback, "Готово")
        await state.clear()
        await edit_callback(
            callback,
            "✅ Избранные проекты сохранены.\n\n"
            "Теперь можно выбрать раздел и начать трекинг времени.",
            reply_markup=build_tracking_start_keyboard(),
        )

    @router.callback_query(F.data.startswith("projects_page:"))
    async def projects_page(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        async with redmine_from_callback(callback, state, rdm_base_url, user_store) as redmine:
            if redmine is None:
                return

            page = int(callback.data.split(":", 1)[1])
            projects = await get_projects_from_state_or_api(callback, state, redmine)
            if not projects:
                return

        await edit_callback(
            callback,
            "📂 Выберите проект:",
            reply_markup=build_projects_keyboard(
                projects,
                page=page,
                favorite_projects=get_favorite_projects_for_user(callback, user_store),
            ),
        )

    @router.callback_query(F.data.startswith("project:"))
    async def choose_project(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        async with redmine_from_callback(callback, state, rdm_base_url, user_store) as redmine:
            if redmine is None:
                return

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
                issues_scope="mine",
            )
            await show_issues(callback, state, redmine, user_store, offset=0)

    @router.callback_query(F.data.startswith("issues_page:"))
    async def issues_page(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        async with redmine_from_callback(callback, state, rdm_base_url, user_store) as redmine:
            if redmine is not None:
                offset = int(callback.data.split(":", 1)[1])
                await show_issues(callback, state, redmine, user_store, offset=offset)

    @router.callback_query(F.data.startswith("issues_scope:"))
    async def issues_scope(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        scope = callback.data.split(":", 1)[1]
        if scope not in {"mine", "all"}:
            return

        await state.update_data(issues_scope=scope)
        async with redmine_from_callback(callback, state, rdm_base_url, user_store) as redmine:
            if redmine is not None:
                await show_issues(callback, state, redmine, user_store, offset=0)

    @router.callback_query(F.data == "back_to_projects")
    async def back_to_projects(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        async with redmine_from_callback(callback, state, rdm_base_url, user_store) as redmine:
            if redmine is None:
                return

            projects = await get_projects_from_state_or_api(callback, state, redmine)
            if not projects:
                return

        await state.set_state(TimeEntryFlow.choosing_project)
        await edit_callback(
            callback,
            "📂 Выберите проект:",
            reply_markup=build_projects_keyboard(
                projects,
                page=0,
                favorite_projects=get_favorite_projects_for_user(callback, user_store),
            ),
        )

    @router.callback_query(F.data.startswith("favorite_project:"))
    async def choose_favorite_project(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        async with redmine_from_callback(callback, state, rdm_base_url, user_store) as redmine:
            if redmine is None:
                return

            project_id = int(callback.data.split(":", 1)[1])
            project = user_store.get_favorite_project(callback.from_user.id, project_id)
            if not project:
                await edit_callback(
                    callback,
                    "⭐ Проект уже не найден в избранном. Откройте список заново.",
                    reply_markup=build_tracking_start_keyboard(),
                )
                return

            await state.set_state(TimeEntryFlow.choosing_issue)
            await state.update_data(
                project_id=project_id,
                project_name=project.get("name") or str(project_id),
                issues_scope="mine",
            )
            await show_issues(callback, state, redmine, user_store, offset=0)

    @router.callback_query(F.data.startswith("recent_issue:"))
    async def choose_recent_issue(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        async with redmine_from_callback(callback, state, rdm_base_url, user_store) as redmine:
            if redmine is None:
                return

            issue_id = int(callback.data.split(":", 1)[1])
            await start_issue_selection_from_callback(callback, state, redmine, issue_id, user_store)

    @router.callback_query(F.data.startswith("favorite_add:"))
    async def add_project_to_favorites(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback, "Добавлено в избранное")
        data = await state.get_data()
        project_id = int(callback.data.split(":", 1)[1])
        project_name = str(data.get("project_name") or project_id)
        user_store.save_favorite_project(callback.from_user.id, project_id, project_name)

        async with redmine_from_callback(callback, state, rdm_base_url, user_store) as redmine:
            if redmine is not None:
                await show_issues(
                    callback,
                    state,
                    redmine,
                    user_store,
                    offset=int(data.get("issues_offset", 0)),
                )

    @router.callback_query(F.data.startswith("favorite_remove:"))
    async def remove_project_from_favorites(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback, "Убрано из избранного")
        data = await state.get_data()
        project_id = int(callback.data.split(":", 1)[1])
        user_store.delete_favorite_project(callback.from_user.id, project_id)

        async with redmine_from_callback(callback, state, rdm_base_url, user_store) as redmine:
            if redmine is not None:
                await show_issues(
                    callback,
                    state,
                    redmine,
                    user_store,
                    offset=int(data.get("issues_offset", 0)),
                )

    @router.callback_query(F.data.startswith("issue:"))
    async def choose_issue(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        async with redmine_from_callback(callback, state, rdm_base_url, user_store) as redmine:
            if redmine is None:
                return

            issue_id = int(callback.data.split(":", 1)[1])
            await start_issue_selection_from_callback(callback, state, redmine, issue_id, user_store)

    @router.callback_query(F.data == "issue_number_prompt")
    async def ask_issue_number(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        await state.set_state(TimeEntryFlow.entering_issue_number)
        prompt_message = await edit_callback(
            callback,
            format_selection_header(await state.get_data())
            + "\n\n⌨️ Отправьте номер задачи сообщением, например 7875 или #7875.",
        )
        if prompt_message:
            await state.update_data(prompt_message_id=prompt_message.message_id)

    @router.message(TimeEntryFlow.choosing_issue, F.text.regexp(r"^#?\d+$"))
    async def issue_number_from_issue_choice(message: Message, state: FSMContext) -> None:
        await open_issue_by_message(message, state, rdm_base_url, user_store)

    @router.message(TimeEntryFlow.entering_issue_number)
    async def issue_number_from_prompt(message: Message, state: FSMContext) -> None:
        if parse_issue_id(message.text or "") is None:
            await message.answer("🎫 Не понял номер задачи. Отправьте, например: 7875 или #7875.")
            return

        await open_issue_by_message(message, state, rdm_base_url, user_store)

    @router.callback_query(F.data.startswith("hours:"))
    async def choose_hours(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        hours = float(callback.data.split(":", 1)[1])
        await state.update_data(hours=hours, spent_on=date.today().isoformat())
        async with redmine_from_callback(callback, state, rdm_base_url, user_store) as redmine:
            if redmine is not None:
                await ask_comment_after_hours_from_callback(callback, state, redmine)

    @router.callback_query(F.data == "hours_custom")
    async def ask_custom_hours(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        await state.set_state(TimeEntryFlow.entering_hours)
        prompt_message = await edit_callback(
            callback,
            format_selection_header(await state.get_data())
            + "\n\n✍️ Введите время сообщением.\n"
            "Примеры: 45 мин, 1,25, 1:30, 2ч 30м.\n"
            "Можно сразу с комментарием: 1,5 - созвон с клиентом.",
        )
        if prompt_message:
            await state.update_data(prompt_message_id=prompt_message.message_id)

    @router.message(TimeEntryFlow.choosing_hours)
    @router.message(TimeEntryFlow.entering_hours)
    async def enter_custom_hours(message: Message, state: FSMContext) -> None:
        hours, quick_comment, used_comment_delimiter = parse_hours_comment_input(message.text or "")
        if hours is None:
            if used_comment_delimiter:
                await message.answer(
                    "🤔 Не понял формат. Напишите так: 1,5 - комментарий. "
                    "Слева от тире должно быть время, справа - комментарий."
                )
            else:
                await message.answer(
                    "🤔 Не понял время. Напишите, например: 45 мин, 1,25, 1:30 или 2ч 30м."
                )
            return

        await delete_message_safely(message)
        await state.update_data(hours=hours, spent_on=date.today().isoformat())
        async with redmine_from_message(message, state, rdm_base_url, user_store) as redmine:
            if redmine is None:
                return
            if quick_comment:
                await state.update_data(comment=quick_comment)
                await confirm_after_hours_comment_from_message(message, state, redmine)
            else:
                await ask_comment_after_hours_from_message(message, state, redmine)

    @router.callback_query(F.data.startswith("date_shift:"))
    async def shift_date(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        days = int(callback.data.split(":", 1)[1])
        data = await state.get_data()
        current_date = date.fromisoformat(data.get("spent_on", date.today().isoformat()))
        await state.update_data(spent_on=(current_date + timedelta(days=days)).isoformat())
        await show_date_step(callback, state)

    @router.callback_query(F.data == "date_today")
    async def set_today(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        await state.update_data(spent_on=date.today().isoformat())
        await show_date_step(callback, state)

    @router.callback_query(F.data == "date_confirm")
    async def confirm_date(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        await state.set_state(TimeEntryFlow.confirming)
        await edit_callback(
            callback,
            format_confirmation(await state.get_data()),
            reply_markup=build_confirmation_keyboard(),
        )

    @router.callback_query(F.data == "date_change")
    async def change_date_from_confirmation(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        data = await state.get_data()
        if not data.get("spent_on"):
            await state.update_data(spent_on=date.today().isoformat())

        await state.set_state(TimeEntryFlow.choosing_date)
        await show_date_step(callback, state)

    @router.callback_query(F.data == "activity_change")
    async def change_activity_from_confirmation(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        data = await state.get_data()
        activities = data.get("activities", [])
        if not activities:
            async with redmine_from_callback(callback, state, rdm_base_url, user_store) as redmine:
                if redmine is None:
                    return
                try:
                    activities = await redmine.get_time_entry_activities()
                except RedmineApiError as error:
                    logging.warning("Redmine API error: %s", error)
                    await edit_callback(callback, error.safe_message)
                    return
                await state.update_data(activities=activities)

        await state.update_data(return_to_confirmation_after_activity=True)
        await state.set_state(TimeEntryFlow.choosing_activity)
        await edit_callback(
            callback,
            format_selection_header(data)
            + "\n\n🧩 Выберите новую деятельность:",
            reply_markup=build_activities_keyboard(activities),
        )

    @router.callback_query(F.data.startswith("activity:"))
    async def choose_activity(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        activity_id = int(callback.data.split(":", 1)[1])
        data = await state.get_data()
        activity = find_by_id(data.get("activities", []), activity_id)

        if not activity:
            await edit_callback(callback, "⚠️ Деятельность не найдена. Нажмите /project заново.")
            await state.clear()
            return

        await state.set_state(TimeEntryFlow.writing_comment)
        await state.update_data(
            activity_id=activity_id,
            activity_name=activity.get("name") or str(activity_id),
        )
        if data.get("return_to_confirmation_after_activity") and data.get("comment"):
            await state.update_data(return_to_confirmation_after_activity=False)
            await state.set_state(TimeEntryFlow.confirming)
            await edit_callback(
                callback,
                format_confirmation(await state.get_data()),
                reply_markup=build_confirmation_keyboard(),
            )
            return

        await ask_comment_from_callback(callback, state)

    @router.message(TimeEntryFlow.writing_comment)
    async def write_comment(message: Message, state: FSMContext) -> None:
        comment = (message.text or "").strip()
        if not comment:
            await message.answer("💬 Комментарий не должен быть пустым. Введите текст.")
            return
        if len(comment) > COMMENT_LIMIT:
            await message.answer(
                f"✂️ Комментарий слишком длинный. Максимум {COMMENT_LIMIT} символов."
            )
            return

        await delete_message_safely(message)
        data = await state.get_data()
        if not data.get("spent_on"):
            await state.update_data(spent_on=date.today().isoformat())

        await state.update_data(comment=comment)
        await state.set_state(TimeEntryFlow.confirming)
        await edit_prompt_from_message(
            message,
            state,
            format_confirmation(await state.get_data()),
            reply_markup=build_confirmation_keyboard(),
        )

    @router.callback_query(F.data == "submit_time_entry")
    async def submit_time_entry(callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        async with redmine_from_callback(callback, state, rdm_base_url, user_store) as redmine:
            if redmine is None:
                return

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
                    "⚠️ Не хватает данных для отправки. Нажмите /project и заполните заново.",
                )
                await state.clear()
                return
            except RedmineApiError as error:
                logging.warning("Redmine API error: %s", error)
                await edit_callback(callback, error.safe_message)
                return

        remember_recent_issue(callback.from_user.id, data, user_store)
        repeat_time_entry = {
            "project_id": data.get("project_id"),
            "project_name": data.get("project_name"),
            "issue_id": data.get("issue_id"),
            "issue_subject": data.get("issue_subject"),
        }
        await state.clear()
        await state.update_data(repeat_time_entry=repeat_time_entry)
        entry_id = time_entry.get("id")
        suffix = f" ID: {entry_id}" if entry_id else ""
        await edit_callback(
            callback,
            f"✅ Трудозатрата отправлена в Redmine.{suffix}\n\n"
            "📌 Можно сразу занести следующую трудозатрату:",
            reply_markup=build_time_entry_done_keyboard(),
        )

    return router


@asynccontextmanager
async def redmine_from_message(
    message: Message,
    state: FSMContext,
    rdm_base_url: str,
    user_store: UserStore,
) -> AsyncIterator[RedmineClient | None]:
    if message.from_user is None:
        await answer_safely(message, "⚠️ Не удалось определить Telegram-пользователя.")
        yield None
        return

    api_key = user_store.get_api_key(message.from_user.id)
    if not api_key:
        await state.clear()
        await answer_safely(
            message,
            "🔐 Сначала войдите в Redmine: нажмите «Войти» или отправьте /login.",
            reply_markup=build_login_keyboard(),
        )
        yield None
        return

    async with RedmineClient(rdm_base_url, api_key) as redmine:
        yield redmine


@asynccontextmanager
async def redmine_from_callback(
    callback: CallbackQuery,
    state: FSMContext,
    rdm_base_url: str,
    user_store: UserStore,
) -> AsyncIterator[RedmineClient | None]:
    if callback.from_user is None:
        await edit_callback(callback, "⚠️ Не удалось определить Telegram-пользователя.")
        yield None
        return

    api_key = user_store.get_api_key(callback.from_user.id)
    if not api_key:
        await state.clear()
        await edit_callback(
            callback,
            "🔐 Сначала войдите в Redmine: /login.",
            reply_markup=build_login_keyboard(),
        )
        yield None
        return

    async with RedmineClient(rdm_base_url, api_key) as redmine:
        yield redmine


async def show_favorite_projects(
    message: Message,
    state: FSMContext,
    user_store: UserStore,
) -> None:
    if message.from_user is None:
        await answer_safely(message, "⚠️ Не удалось определить Telegram-пользователя.")
        return

    if not user_store.get_api_key(message.from_user.id):
        await state.clear()
        await answer_safely(
            message,
            "🔐 Сначала войдите в Redmine: нажмите «Войти» или отправьте /login.",
            reply_markup=build_login_keyboard(),
        )
        return

    projects = user_store.get_favorite_projects(
        message.from_user.id,
        FAVORITE_PROJECTS_LIMIT,
    )
    if not projects:
        await state.clear()
        await answer_safely(
            message,
            "⭐ Избранных проектов пока нет.\n\n"
            "Откройте «⚙️ Настроить избранное» и отметьте нужные проекты.",
            reply_markup=build_idle_keyboard(),
        )
        return

    await state.clear()
    await state.set_state(TimeEntryFlow.choosing_project)
    await state.update_data(favorite_projects=projects)
    await answer_safely(
        message,
        "⭐ Ваши избранные проекты:",
        reply_markup=build_favorite_projects_keyboard(projects),
    )


async def start_favorites_setup(
    message: Message,
    state: FSMContext,
    redmine: RedmineClient,
    user_store: UserStore,
    telegram_user_id: int,
    intro_text: str,
) -> None:
    try:
        projects = await load_projects(redmine)
    except (RedmineConfigError, asyncio.TimeoutError, RedmineApiError) as error:
        logging.warning("Could not start favorites setup: %s", error)
        await answer_safely(
            message,
            intro_text
            + "\n\n⚠️ Не удалось загрузить проекты для настройки избранного. "
            "Можно настроить их позже из списка проектов.",
            reply_markup=build_idle_keyboard(),
        )
        return

    if not projects:
        await answer_safely(
            message,
            intro_text
            + "\n\n📭 Проекты не найдены. Главное меню уже доступно.",
            reply_markup=build_idle_keyboard(),
        )
        return

    await state.clear()
    await state.set_state(TimeEntryFlow.choosing_project)
    await state.update_data(projects=projects, favorites_setup=True)
    favorite_ids = get_favorite_project_ids(user_store, telegram_user_id)
    await answer_safely(
        message,
        intro_text,
        reply_markup=build_favorites_setup_keyboard(projects, favorite_ids, page=0),
    )


async def show_favorites_setup_page(
    callback: CallbackQuery,
    state: FSMContext,
    user_store: UserStore,
    page: int,
) -> None:
    data = await state.get_data()
    projects = data.get("projects", [])
    if not projects:
        await edit_callback(
            callback,
            "⚠️ Список проектов не найден. Откройте /project и попробуйте еще раз.",
            reply_markup=build_idle_keyboard(),
        )
        return

    favorite_ids = get_favorite_project_ids(user_store, callback.from_user.id)
    await edit_callback(
        callback,
        "⭐ Отметьте избранные проекты.\n\n"
        "⭐ — проект уже в избранном, ☆ — можно добавить.",
        reply_markup=build_favorites_setup_keyboard(projects, favorite_ids, page),
    )


async def show_recent_issues(
    message: Message,
    state: FSMContext,
    user_store: UserStore,
) -> None:
    if message.from_user is None:
        await answer_safely(message, "⚠️ Не удалось определить Telegram-пользователя.")
        return

    if not user_store.get_api_key(message.from_user.id):
        await state.clear()
        await answer_safely(
            message,
            "🔐 Сначала войдите в Redmine: нажмите «Войти» или отправьте /login.",
            reply_markup=build_login_keyboard(),
        )
        return

    issues = user_store.get_recent_issues(message.from_user.id, RECENT_ISSUES_LIMIT)
    if not issues:
        await state.clear()
        await answer_safely(
            message,
            "🎫 Последних задач пока нет.\n\n"
            "Когда вы отправите трудозатрату, задача появится здесь для быстрого повтора.",
            reply_markup=build_idle_keyboard(),
        )
        return

    await state.clear()
    await state.set_state(TimeEntryFlow.choosing_issue)
    await state.update_data(recent_issues=issues)
    await answer_safely(
        message,
        "🎫 Последние задачи:",
        reply_markup=build_recent_issues_keyboard(issues),
    )


async def start_issue_selection_from_callback(
    callback: CallbackQuery,
    state: FSMContext,
    redmine: RedmineClient,
    issue_id: int,
    user_store: UserStore,
) -> None:
    try:
        issue = await redmine.get_issue(issue_id)
    except RedmineApiError as error:
        logging.warning("Redmine API error: %s", error)
        await edit_callback(callback, error.safe_message)
        return

    await set_issue_data(state, issue)
    remember_redmine_issue(callback.from_user.id, issue, user_store)
    prompt_message = await edit_callback(
        callback,
        format_hours_step_text(await state.get_data()),
        reply_markup=build_hours_keyboard(),
        parse_mode="HTML",
    )
    if prompt_message:
        await state.update_data(prompt_message_id=prompt_message.message_id)


async def open_issue_by_message(
    message: Message,
    state: FSMContext,
    rdm_base_url: str,
    user_store: UserStore,
) -> None:
    issue_id = parse_issue_id(message.text or "")
    if issue_id is None:
        await message.answer("🎫 Не понял номер задачи. Отправьте, например: 7875 или #7875.")
        return

    data = await state.get_data()
    reusable_message_id = data.get("prompt_message_id") or data.get("issue_list_message_id")
    if reusable_message_id:
        await state.update_data(prompt_message_id=reusable_message_id)

    async with redmine_from_message(message, state, rdm_base_url, user_store) as redmine:
        if redmine is not None:
            await start_issue_selection_by_number(message, state, redmine, issue_id, user_store)


async def ask_comment_after_hours_from_callback(
    callback: CallbackQuery,
    state: FSMContext,
    redmine: RedmineClient,
) -> None:
    try:
        activities = await redmine.get_time_entry_activities()
    except RedmineApiError as error:
        logging.warning("Redmine API error: %s", error)
        await edit_callback(callback, error.safe_message)
        return

    if not activities:
        await edit_callback(callback, "В Redmine не найдены виды деятельности.")
        return

    await state.update_data(activities=activities)
    default_activity = find_activity_by_name(activities, DEFAULT_ACTIVITY_NAME)
    if default_activity:
        await state.update_data(
            activity_id=int(default_activity["id"]),
            activity_name=default_activity.get("name") or DEFAULT_ACTIVITY_NAME,
        )
        await ask_comment_from_callback(callback, state)
        return

    await state.set_state(TimeEntryFlow.choosing_activity)
    await edit_callback(
        callback,
        format_selection_header(await state.get_data())
        + f"\n\n🧩 Деятельность {DEFAULT_ACTIVITY_NAME} не найдена. Выберите деятельность:",
        reply_markup=build_activities_keyboard(activities),
    )


async def ask_comment_after_hours_from_message(
    message: Message,
    state: FSMContext,
    redmine: RedmineClient,
) -> None:
    try:
        activities = await redmine.get_time_entry_activities()
    except RedmineApiError as error:
        logging.warning("Redmine API error: %s", error)
        await edit_prompt_from_message(message, state, error.safe_message)
        return

    if not activities:
        await edit_prompt_from_message(message, state, "В Redmine не найдены виды деятельности.")
        return

    await state.update_data(activities=activities)
    default_activity = find_activity_by_name(activities, DEFAULT_ACTIVITY_NAME)
    if default_activity:
        await state.update_data(
            activity_id=int(default_activity["id"]),
            activity_name=default_activity.get("name") or DEFAULT_ACTIVITY_NAME,
        )
        await ask_comment_from_message(message, state)
        return

    await state.set_state(TimeEntryFlow.choosing_activity)
    await edit_prompt_from_message(
        message,
        state,
        format_selection_header(await state.get_data())
        + f"\n\n🧩 Деятельность {DEFAULT_ACTIVITY_NAME} не найдена. Выберите деятельность:",
        reply_markup=build_activities_keyboard(activities),
    )


async def confirm_after_hours_comment_from_message(
    message: Message,
    state: FSMContext,
    redmine: RedmineClient,
) -> None:
    try:
        activities = await redmine.get_time_entry_activities()
    except RedmineApiError as error:
        logging.warning("Redmine API error: %s", error)
        await edit_prompt_from_message(message, state, error.safe_message)
        return

    if not activities:
        await edit_prompt_from_message(message, state, "В Redmine не найдены виды деятельности.")
        return

    await state.update_data(activities=activities)
    default_activity = find_activity_by_name(activities, DEFAULT_ACTIVITY_NAME)
    if default_activity:
        await state.update_data(
            activity_id=int(default_activity["id"]),
            activity_name=default_activity.get("name") or DEFAULT_ACTIVITY_NAME,
        )
        await state.set_state(TimeEntryFlow.confirming)
        await edit_prompt_from_message(
            message,
            state,
            format_confirmation(await state.get_data()),
            reply_markup=build_confirmation_keyboard(),
        )
        return

    await state.update_data(return_to_confirmation_after_activity=True)
    await state.set_state(TimeEntryFlow.choosing_activity)
    await edit_prompt_from_message(
        message,
        state,
        format_selection_header(await state.get_data())
        + f"\n\n🧩 Деятельность {DEFAULT_ACTIVITY_NAME} не найдена. Выберите деятельность:",
        reply_markup=build_activities_keyboard(activities),
    )


async def ask_comment_from_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(TimeEntryFlow.writing_comment)
    prompt_message = await edit_callback(
        callback,
        format_selection_header(await state.get_data())
        + "\n\n💬 Добавьте комментарий одним сообщением в Telegram.",
    )
    if prompt_message:
        await state.update_data(prompt_message_id=prompt_message.message_id)


async def ask_comment_from_message(message: Message, state: FSMContext) -> None:
    await state.set_state(TimeEntryFlow.writing_comment)
    await edit_prompt_from_message(
        message,
        state,
        format_selection_header(await state.get_data())
        + "\n\n💬 Добавьте комментарий одним сообщением в Telegram.",
    )


def format_hours_step_text(data: dict[str, Any]) -> str:
    header = escape(format_selection_header(data))
    return (
        header
        + "\n\n⏱️ Сколько времени списываем?\n"
        "Можно написать время: 45 мин, 1,25, 1:30.\n"
        "(1,5h) — попрошу комментарий\n"
        '(1,5h - комментарий) — вид уже с комментарием <i><b>|через &quot;-&quot;|</b></i>'
    )


async def start_repeat_time_entry_from_callback(
    callback: CallbackQuery,
    state: FSMContext,
) -> bool:
    data = await state.get_data()
    repeat_time_entry = data.get("repeat_time_entry")
    if not isinstance(repeat_time_entry, dict) or not repeat_time_entry.get("issue_id"):
        return False

    await state.clear()
    await state.set_state(TimeEntryFlow.choosing_hours)
    await state.update_data(
        project_id=repeat_time_entry.get("project_id"),
        project_name=repeat_time_entry.get("project_name"),
        issue_id=repeat_time_entry.get("issue_id"),
        issue_subject=repeat_time_entry.get("issue_subject"),
    )
    prompt_message = await edit_callback(
        callback,
        format_hours_step_text(await state.get_data()),
        reply_markup=build_hours_keyboard(),
        parse_mode="HTML",
    )
    if prompt_message:
        await state.update_data(prompt_message_id=prompt_message.message_id)
    return True


async def start_project_selection(
    message: Message,
    state: FSMContext,
    redmine: RedmineClient,
    user_store: UserStore,
) -> None:
    await state.clear()

    try:
        projects = await load_projects(redmine)
    except RedmineConfigError as error:
        logging.warning("Configuration error: %s", error)
        await answer_safely(
            message,
            "⚙️ Не хватает настроек для подключения к Redmine. Проверьте RDM_BASE_URL в .env.",
            reply_markup=build_idle_keyboard(),
        )
        return
    except asyncio.TimeoutError as error:
        logging.warning("Redmine projects load timeout: %s", error)
        await answer_safely(
            message,
            "⏳ Redmine долго не отвечает при загрузке проектов. "
            "Проверьте VPN/сеть и попробуйте еще раз.",
            reply_markup=build_idle_keyboard(),
        )
        return
    except RedmineApiError as error:
        logging.warning("Redmine API error: %s", error)
        await answer_safely(message, f"⚠️ {error.safe_message}", reply_markup=build_idle_keyboard())
        return

    if not projects:
        await answer_safely(message, "📭 Проекты не найдены.", reply_markup=build_idle_keyboard())
        return

    await state.set_state(TimeEntryFlow.choosing_project)
    await state.update_data(projects=projects)
    await answer_safely(
        message,
        "📂 Выберите проект:\n\n"
        "⭐ Избранные проекты показаны сверху, ниже — общий список.",
        reply_markup=build_projects_keyboard(
            projects,
            page=0,
            favorite_projects=get_favorite_projects_for_message(message, user_store),
        ),
    )


async def start_project_selection_from_callback(
    callback: CallbackQuery,
    state: FSMContext,
    redmine: RedmineClient,
    user_store: UserStore,
) -> None:
    await state.clear()

    try:
        projects = await load_projects(redmine)
    except RedmineConfigError as error:
        logging.warning("Configuration error: %s", error)
        await edit_callback(
            callback,
            "⚙️ Не хватает настроек для подключения к Redmine. Проверьте RDM_BASE_URL в .env.",
        )
        return
    except asyncio.TimeoutError as error:
        logging.warning("Redmine projects load timeout: %s", error)
        await edit_callback(
            callback,
            "⏳ Redmine долго не отвечает при загрузке проектов. Проверьте VPN/сеть и попробуйте еще раз.",
        )
        return
    except RedmineApiError as error:
        logging.warning("Redmine API error: %s", error)
        await edit_callback(callback, f"⚠️ {error.safe_message}")
        return

    if not projects:
        await edit_callback(callback, "📭 Проекты не найдены.")
        return

    await state.set_state(TimeEntryFlow.choosing_project)
    await state.update_data(projects=projects)
    await edit_callback(
        callback,
        "📂 Выберите проект:\n\n"
        "⭐ Избранные проекты показаны сверху, ниже — общий список.",
        reply_markup=build_projects_keyboard(
            projects,
            page=0,
            favorite_projects=get_favorite_projects_for_user(callback, user_store),
        ),
    )


async def start_issue_selection_by_number(
    message: Message,
    state: FSMContext,
    redmine: RedmineClient,
    issue_id: int,
    user_store: UserStore,
) -> None:
    previous_data = await state.get_data()
    reusable_message_id = previous_data.get("prompt_message_id") or previous_data.get("issue_list_message_id")
    await state.clear()

    try:
        issue = await redmine.get_issue(issue_id)
    except RedmineApiError as error:
        logging.warning("Redmine API error: %s", error)
        await answer_safely(message, f"⚠️ {error.safe_message}", reply_markup=build_idle_keyboard())
        return

    await set_issue_data(state, issue)
    if reusable_message_id:
        await state.update_data(prompt_message_id=reusable_message_id)
    if message.from_user:
        remember_redmine_issue(message.from_user.id, issue, user_store)
    await delete_message_safely(message)
    prompt_message = await edit_prompt_from_message(
        message,
        state,
        format_hours_step_text(await state.get_data()),
        reply_markup=build_hours_keyboard(),
        parse_mode="HTML",
    )


async def show_issues(
    callback: CallbackQuery,
    state: FSMContext,
    redmine: RedmineClient,
    user_store: UserStore,
    offset: int,
) -> None:
    data = await state.get_data()
    project_id = data.get("project_id")
    project_name = data.get("project_name", "проект")
    issues_scope = str(data.get("issues_scope") or "mine")
    show_all_issues = issues_scope == "all"

    if not project_id:
        await edit_callback(callback, "⚠️ Проект не выбран. Нажмите /project заново.")
        await state.clear()
        return

    try:
        issues_page = await redmine.get_issues(
            project_id=project_id,
            offset=offset,
            assigned_to_id=None if show_all_issues else "me",
        )
    except RedmineApiError as error:
        logging.warning("Redmine API error: %s", error)
        await edit_callback(callback, error.safe_message)
        return

    await state.update_data(issues_offset=offset)
    is_favorite_project = user_store.is_favorite_project(
        callback.from_user.id,
        int(project_id),
    )
    recent_issue = get_latest_recent_issue_for_project(
        callback.from_user.id,
        as_optional_int(project_id),
        user_store,
    )
    issues = move_recent_issue_to_top(
        issues_page["issues"],
        recent_issue,
        include_missing=show_all_issues,
    )
    if not issues:
        scope_text = "всех задач" if show_all_issues else "личных задач"
        issue_list_message = await edit_callback(
            callback,
            f"📭 В проекте {project_name} {scope_text} не найдено.",
            reply_markup=build_empty_project_issues_keyboard(show_all_issues),
        )
        if issue_list_message:
            await state.update_data(issue_list_message_id=issue_list_message.message_id)
        return

    scope_title = "все задачи проекта" if show_all_issues else "ваши личные задачи"
    issue_list_message = await edit_callback(
        callback,
        f"📁 Проект: {project_name}\n🎫 Сейчас показаны {scope_title}.\n"
        "Выберите задачу или отправьте номер задачи сообщением:",
        reply_markup=build_issues_keyboard(
            issues=issues,
            offset=issues_page["offset"],
            limit=issues_page["limit"],
            total_count=issues_page["total_count"],
            project_id=project_id,
            is_favorite_project=is_favorite_project,
            show_all_issues=show_all_issues,
        ),
    )
    if issue_list_message:
        await state.update_data(issue_list_message_id=issue_list_message.message_id)


async def show_date_step(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("spent_on"):
        await state.update_data(spent_on=date.today().isoformat())

    await edit_callback(
        callback,
        format_selection_header(await state.get_data())
        + "\n\n📅 Дата по умолчанию - сегодня. При необходимости измените ее:",
        reply_markup=build_date_keyboard(),
    )


async def show_date_step_from_message(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("spent_on"):
        await state.update_data(spent_on=date.today().isoformat())

    await edit_prompt_from_message(
        message,
        state,
        format_selection_header(await state.get_data())
        + "\n\n📅 Последний шаг — дата трудозатраты. По умолчанию стоит сегодня:",
        reply_markup=build_date_keyboard(),
    )


async def edit_prompt_from_message(
    message: Message,
    state: FSMContext,
    text: str,
    reply_markup=None,
    parse_mode: str | None = None,
) -> Message | None:
    data = await state.get_data()
    prompt_message_id = data.get("prompt_message_id")
    prompt_message = None
    if prompt_message_id:
        try:
            prompt_message = await edit_message_by_id_safely(
                message,
                int(prompt_message_id),
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        except (TypeError, ValueError):
            logging.warning("Invalid prompt message id in FSM data: %s", prompt_message_id)

    if prompt_message is None:
        prompt_message = await answer_safely(
            message,
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )

    if prompt_message:
        await state.update_data(prompt_message_id=prompt_message.message_id)
    return prompt_message


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
    parse_mode: str | None = None,
) -> Message | None:
    if callback.message:
        return await replace_message_safely(
            callback.message,
            text,
            reply_markup,
            parse_mode=parse_mode,
        )
    return None


async def delete_prompt_from_state(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    prompt_message_id = data.get("prompt_message_id")
    if not prompt_message_id:
        return

    try:
        await delete_message_by_id_safely(message, int(prompt_message_id))
    except (TypeError, ValueError):
        logging.warning("Invalid prompt message id in FSM data: %s", prompt_message_id)
    finally:
        await state.update_data(prompt_message_id=None)


async def delete_issue_list_from_state(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    issue_list_message_id = data.get("issue_list_message_id")
    if not issue_list_message_id:
        return

    try:
        await delete_message_by_id_safely(message, int(issue_list_message_id))
    except (TypeError, ValueError):
        logging.warning("Invalid issue list message id in FSM data: %s", issue_list_message_id)
    finally:
        await state.update_data(issue_list_message_id=None)


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


def find_activity_by_name(
    activities: list[dict[str, Any]],
    name: str,
) -> dict[str, Any] | None:
    expected_name = name.strip().casefold()
    return next(
        (
            activity
            for activity in activities
            if activity.get("id") is not None
            and str(activity.get("name") or "").strip().casefold() == expected_name
        ),
        None,
    )


def get_favorite_project_ids(user_store: UserStore, telegram_user_id: int) -> set[int]:
    return {
        int(project["id"])
        for project in user_store.get_favorite_projects(
            telegram_user_id,
            FAVORITE_PROJECTS_SETUP_LIMIT,
        )
        if project.get("id") is not None
    }


def get_favorite_projects_for_message(
    message: Message,
    user_store: UserStore,
) -> list[dict[str, object]]:
    if not message.from_user:
        return []
    return user_store.get_favorite_projects(
        message.from_user.id,
        FAVORITE_PROJECTS_LIMIT,
    )


def get_favorite_projects_for_user(
    callback: CallbackQuery,
    user_store: UserStore,
) -> list[dict[str, object]]:
    return user_store.get_favorite_projects(
        callback.from_user.id,
        FAVORITE_PROJECTS_LIMIT,
    )


def remember_redmine_issue(
    telegram_user_id: int,
    issue: dict[str, Any],
    user_store: UserStore,
) -> None:
    try:
        issue_id = int(issue["id"])
    except (KeyError, TypeError, ValueError) as error:
        logging.warning("Could not remember touched issue: %s", error)
        return

    project = issue.get("project") if isinstance(issue.get("project"), dict) else {}
    user_store.save_recent_issue(
        telegram_user_id=telegram_user_id,
        issue_id=issue_id,
        issue_subject=str(issue.get("subject") or f"Задача #{issue_id}"),
        project_id=as_optional_int(project.get("id")),
        project_name=str(project.get("name")) if project.get("name") else None,
        limit=RECENT_ISSUES_LIMIT,
    )


def get_latest_recent_issue_for_project(
    telegram_user_id: int,
    project_id: int | None,
    user_store: UserStore,
) -> dict[str, object] | None:
    if project_id is None:
        return None

    for issue in user_store.get_recent_issues(telegram_user_id, RECENT_ISSUES_LIMIT):
        if as_optional_int(issue.get("project_id")) == project_id:
            return issue
    return None


def move_recent_issue_to_top(
    issues: list[dict[str, Any]],
    recent_issue: dict[str, object] | None,
    include_missing: bool = True,
) -> list[dict[str, Any]]:
    if not recent_issue or recent_issue.get("id") is None:
        return issues

    recent_issue_id = str(recent_issue["id"])
    existing_issue = next(
        (issue for issue in issues if str(issue.get("id")) == recent_issue_id),
        None,
    )
    if existing_issue:
        top_issue = existing_issue
    elif include_missing:
        top_issue = dict(recent_issue)
    else:
        return issues

    return [
        top_issue,
        *[issue for issue in issues if str(issue.get("id")) != recent_issue_id],
    ]


def remember_recent_issue(
    telegram_user_id: int,
    data: dict[str, Any],
    user_store: UserStore,
) -> None:
    try:
        issue_id = int(data["issue_id"])
    except (KeyError, TypeError, ValueError) as error:
        logging.warning("Could not remember recent issue: %s", error)
        return

    issue_subject = str(data.get("issue_subject") or f"Задача #{issue_id}")
    project_id = as_optional_int(data.get("project_id"))
    project_name_value = data.get("project_name")
    project_name = str(project_name_value) if project_name_value else None

    user_store.save_recent_issue(
        telegram_user_id=telegram_user_id,
        issue_id=issue_id,
        issue_subject=issue_subject,
        project_id=project_id,
        project_name=project_name,
        limit=RECENT_ISSUES_LIMIT,
    )


def as_optional_int(value: Any) -> int | None:
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def format_redmine_user(user: dict[str, Any]) -> str:
    login = user.get("login")
    firstname = user.get("firstname")
    lastname = user.get("lastname")
    full_name = " ".join(str(part) for part in (firstname, lastname) if part)

    if full_name and login:
        return f"{full_name} ({login})"
    return str(full_name or login or user.get("id") or "Redmine user")


def is_logged_in(message: Message, user_store: UserStore) -> bool:
    return bool(message.from_user and user_store.get_api_key(message.from_user.id))


def keyboard_for_message(message: Message, user_store: UserStore):
    if is_logged_in(message, user_store):
        return build_idle_keyboard()
    return build_login_keyboard()


def keyboard_for_callback(callback: CallbackQuery, user_store: UserStore):
    if user_store.get_api_key(callback.from_user.id):
        return build_idle_keyboard()
    return build_login_keyboard()


