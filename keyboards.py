from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton
from aiogram.types import ReplyKeyboardMarkup

from constants import IDLE_PROJECT_BUTTON_TEXT, ISSUES_PER_PAGE, PROJECTS_PER_PAGE


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
                InlineKeyboardButton(text="30 минут", callback_data="hours:0.5"),
                InlineKeyboardButton(text="1 час", callback_data="hours:1"),
            ],
            [
                InlineKeyboardButton(text="1,5 часа", callback_data="hours:1.5"),
                InlineKeyboardButton(text="2 часа", callback_data="hours:2"),
            ],
            [
                InlineKeyboardButton(text="2,5 часа", callback_data="hours:2.5"),
                InlineKeyboardButton(text="3 часа", callback_data="hours:3"),
            ],
            [InlineKeyboardButton(text="Другое время", callback_data="hours_custom")],
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


def build_empty_project_issues_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад к проектам", callback_data="back_to_projects")],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel")],
        ]
    )


def shorten(text: str, max_length: int) -> str:
    text = " ".join(str(text).split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"
