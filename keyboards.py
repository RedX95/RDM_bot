from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton
from aiogram.types import ReplyKeyboardMarkup

from constants import FAVORITES_SETUP_BUTTON_TEXT, TRACKING_BUTTON_TEXT
from constants import LOGIN_BUTTON_TEXT, RECENT_ISSUES_BUTTON_TEXT, ISSUES_PER_PAGE
from constants import PROJECTS_PER_PAGE


def build_projects_keyboard(
    projects: list[dict[str, Any]],
    page: int,
    favorite_projects: list[dict[str, Any]] | None = None,
) -> InlineKeyboardMarkup:
    total_pages = max(1, (len(projects) + PROJECTS_PER_PAGE - 1) // PROJECTS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * PROJECTS_PER_PAGE
    page_projects = projects[start : start + PROJECTS_PER_PAGE]

    rows = []
    favorite_project_ids = {
        str(project.get("id"))
        for project in favorite_projects or []
        if project.get("id") is not None
    }
    favorite_buttons = []
    for project in favorite_projects or []:
        if project.get("id") is None:
            continue
        favorite_buttons.append(
            InlineKeyboardButton(
                text=shorten(f"⭐ {project.get('name') or project.get('id')}", 24),
                callback_data=f"project:{project.get('id')}",
            )
        )
    rows.extend(button_rows(favorite_buttons, columns=3))

    project_buttons = []
    for project in page_projects:
        if project.get("id") is None:
            continue
        if str(project.get("id")) in favorite_project_ids:
            continue

        project_buttons.append(
            InlineKeyboardButton(
                text=shorten(f"📁 {project.get('name') or project.get('id')}", 24),
                callback_data=f"project:{project.get('id')}",
            )
        )
    rows.extend(button_rows(project_buttons, columns=3))

    navigation = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"projects_page:{page - 1}")
        )
    if page < total_pages - 1:
        navigation.append(
            InlineKeyboardButton(text="➡️ Дальше", callback_data=f"projects_page:{page + 1}")
        )
    if navigation:
        rows.append(navigation)

    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_favorites_setup_keyboard(
    projects: list[dict[str, Any]],
    favorite_project_ids: set[int],
    page: int,
) -> InlineKeyboardMarkup:
    total_pages = max(1, (len(projects) + PROJECTS_PER_PAGE - 1) // PROJECTS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * PROJECTS_PER_PAGE
    page_projects = projects[start : start + PROJECTS_PER_PAGE]

    rows = []
    project_buttons = []
    for project in page_projects:
        project_id = project.get("id")
        if project_id is None:
            continue

        project_id_int = int(project_id)
        marker = "⭐" if project_id_int in favorite_project_ids else "☆"
        project_buttons.append(
            InlineKeyboardButton(
                text=shorten(f"{marker} {project.get('name') or project_id}", 24),
                callback_data=f"favorites_toggle:{project_id}:{page}",
            )
        )
    rows.extend(button_rows(project_buttons, columns=3))

    navigation = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"favorites_page:{page - 1}")
        )
    if page < total_pages - 1:
        navigation.append(
            InlineKeyboardButton(text="➡️ Дальше", callback_data=f"favorites_page:{page + 1}")
        )
    if navigation:
        rows.append(navigation)

    rows.append([InlineKeyboardButton(text="✅ Готово", callback_data="favorites_done")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_issues_keyboard(
    issues: list[dict[str, Any]],
    offset: int,
    limit: int,
    total_count: int,
    project_id: int | str | None = None,
    is_favorite_project: bool = False,
    show_all_issues: bool = False,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=shorten(f"🎫 #{issue.get('id')} {issue.get('subject') or ''}", 58),
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
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"issues_page:{previous_offset}")
        )
    if offset + limit < total_count:
        navigation.append(
            InlineKeyboardButton(text="➡️ Дальше", callback_data=f"issues_page:{offset + limit}")
        )
    if navigation:
        rows.append(navigation)

    if show_all_issues:
        rows.append([InlineKeyboardButton(text="👤 Мои задачи", callback_data="issues_scope:mine")])
    else:
        rows.append([InlineKeyboardButton(text="🌐 Все задачи", callback_data="issues_scope:all")])

    rows.append([InlineKeyboardButton(text="📂 К проектам", callback_data="back_to_projects")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_hours_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⏱️ 30 мин", callback_data="hours:0.5"),
                InlineKeyboardButton(text="🕐 1 час", callback_data="hours:1"),
            ],
            [
                InlineKeyboardButton(text="🕜 1,5 часа", callback_data="hours:1.5"),
                InlineKeyboardButton(text="🕑 2 часа", callback_data="hours:2"),
            ],
            [
                InlineKeyboardButton(text="🕝 2,5 часа", callback_data="hours:2.5"),
                InlineKeyboardButton(text="🕒 3 часа", callback_data="hours:3"),
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
        ]
    )


def build_date_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⬅️ -1 день", callback_data="date_shift:-1"),
                InlineKeyboardButton(text="📍 Сегодня", callback_data="date_today"),
                InlineKeyboardButton(text="+1 день ➡️", callback_data="date_shift:1"),
            ],
            [InlineKeyboardButton(text="✅ Подтвердить дату", callback_data="date_confirm")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
        ]
    )


def build_activities_keyboard(activities: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=shorten(f"🧩 {activity.get('name') or activity.get('id')}", 58),
                callback_data=f"activity:{activity.get('id')}",
            )
        ]
        for activity in activities
        if activity.get("id") is not None
    ]
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Отправить", callback_data="submit_time_entry")],
            [InlineKeyboardButton(text="📅 Изменить дату", callback_data="date_change")],
            [InlineKeyboardButton(text="🧩 Изменить деятельность", callback_data="activity_change")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
        ]
    )


def build_time_entry_done_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔁 Повторить трекинг времени", callback_data="tracking_start")],
        ]
    )


def build_tracking_start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Tracking", callback_data="tracking_start")],
        ]
    )


def build_idle_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=TRACKING_BUTTON_TEXT)],
            [KeyboardButton(text=RECENT_ISSUES_BUTTON_TEXT)],
            [KeyboardButton(text=FAVORITES_SETUP_BUTTON_TEXT)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Tracking, последние задачи или номер",
    )


def build_login_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=LOGIN_BUTTON_TEXT)]],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Войдите в Redmine",
    )


def build_empty_project_issues_keyboard(show_all_issues: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if show_all_issues:
        rows.append([InlineKeyboardButton(text="👤 Мои задачи", callback_data="issues_scope:mine")])
    else:
        rows.append([InlineKeyboardButton(text="🌐 Все задачи", callback_data="issues_scope:all")])

    rows.append([InlineKeyboardButton(text="📂 К проектам", callback_data="back_to_projects")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_favorite_projects_keyboard(projects: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    buttons = []
    for project in projects:
        if project.get("id") is None:
            continue
        buttons.append(
            InlineKeyboardButton(
                text=shorten(f"⭐ {project.get('name') or project.get('id')}", 24),
                callback_data=f"favorite_project:{project.get('id')}",
            )
        )

    rows = button_rows(buttons, columns=3)
    rows.append([InlineKeyboardButton(text="📂 Все проекты", callback_data="back_to_projects")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_recent_issues_keyboard(issues: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows = []
    for issue in issues:
        issue_id = issue.get("id")
        if issue_id is None:
            continue

        project_name = issue.get("project_name")
        subject = issue.get("subject") or ""
        label = f"🎫 #{issue_id} {subject}"
        if project_name:
            label += f" · {project_name}"

        rows.append(
            [
                InlineKeyboardButton(
                    text=shorten(label, 58),
                    callback_data=f"recent_issue:{issue_id}",
                )
            ]
        )

    rows.append([InlineKeyboardButton(text="📂 Выбрать проект", callback_data="back_to_projects")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def shorten(text: str, max_length: int) -> str:
    text = " ".join(str(text).split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"


def button_rows(
    buttons: list[InlineKeyboardButton],
    columns: int,
) -> list[list[InlineKeyboardButton]]:
    return [buttons[index : index + columns] for index in range(0, len(buttons), columns)]
