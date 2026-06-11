from datetime import date
from typing import Any


def format_selection_header(data: dict[str, Any]) -> str:
    parts = []
    if data.get("project_name"):
        parts.append(f"📁 Проект: {data['project_name']}")
    if data.get("issue_id"):
        parts.append(f"🎫 Задача: #{data['issue_id']} {data.get('issue_subject', '')}".strip())
    if data.get("hours"):
        parts.append(f"⏱️ Время: {format_hours(float(data['hours']))}")
    if data.get("spent_on"):
        parts.append(f"📅 Дата: {format_date(str(data['spent_on']))}")
    if data.get("activity_name"):
        parts.append(f"🧩 Деятельность: {data['activity_name']}")
    return "\n".join(parts)


def format_confirmation(data: dict[str, Any]) -> str:
    return (
        "🧾 Проверьте трудозатрату:\n"
        f"{format_selection_header(data)}\n"
        f"💬 Комментарий: {data.get('comment', '')}\n\n"
        "🚀 Отправить в Redmine?"
    )


def format_hours(hours: float) -> str:
    if 0 < hours < 1:
        return f"{round(hours * 60)} мин"
    if hours.is_integer():
        return f"{int(hours)} ч"
    return f"{str(hours).replace('.', ',')} ч"


def format_date(iso_date: str) -> str:
    parsed = date.fromisoformat(iso_date)
    relative_label = format_relative_date_label(parsed)
    if relative_label:
        return f"{parsed.strftime('%d.%m.%Y')} ({relative_label})"
    return parsed.strftime("%d.%m.%Y")


def format_relative_date_label(parsed: date) -> str:
    days_delta = (date.today() - parsed).days
    if days_delta == 0:
        return "сегодня"
    if days_delta == 1:
        return "вчера"
    if days_delta == 2:
        return "позавчера"
    if days_delta > 0:
        return f"{days_delta} {pluralize_days(days_delta)} назад"

    future_days = abs(days_delta)
    if future_days == 1:
        return "завтра"
    if future_days == 2:
        return "послезавтра"
    return f"через {future_days} {pluralize_days(future_days)}"


def pluralize_days(days: int) -> str:
    if 11 <= days % 100 <= 14:
        return "дней"
    if days % 10 == 1:
        return "день"
    if 2 <= days % 10 <= 4:
        return "дня"
    return "дней"
