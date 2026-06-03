from datetime import date
from typing import Any


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
    if 0 < hours < 1:
        return f"{round(hours * 60)} мин"
    if hours.is_integer():
        return f"{int(hours)} ч"
    return f"{str(hours).replace('.', ',')} ч"


def format_date(iso_date: str) -> str:
    parsed = date.fromisoformat(iso_date)
    return parsed.strftime("%d.%m.%Y")
