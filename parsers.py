import re


def parse_issue_id(text: str) -> int | None:
    cleaned = text.strip().lstrip("#")
    if not cleaned.isdigit():
        return None

    return int(cleaned)


def parse_hours_input(text: str) -> float | None:
    cleaned = text.strip().lower().replace(",", ".").replace("ё", "е")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return None

    time_match = re.fullmatch(r"(\d{1,2})\s*:\s*([0-5]?\d)", cleaned)
    if time_match:
        hours = int(time_match.group(1)) + int(time_match.group(2)) / 60
        return normalize_hours(hours)

    hours_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:ч|час|часа|часов|h)", cleaned)
    minutes_match = re.search(
        r"(\d+)\s*(?:м|мин|минута|минуты|минут|m)",
        cleaned,
    )
    if hours_match or minutes_match:
        hours = float(hours_match.group(1)) if hours_match else 0
        minutes = int(minutes_match.group(1)) if minutes_match else 0
        return normalize_hours(hours + minutes / 60)

    number_match = re.fullmatch(r"\d+(?:\.\d+)?", cleaned)
    if number_match:
        value = float(cleaned)
        hours = value / 60 if value >= 10 else value
        return normalize_hours(hours)

    return None


def normalize_hours(hours: float) -> float | None:
    if hours <= 0 or hours > 24:
        return None

    return round(hours, 2)
