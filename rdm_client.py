import asyncio
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp


class RedmineConfigError(Exception):
    """Raised when required Redmine configuration is missing or invalid."""


class RedmineApiError(Exception):
    """Raised when Redmine API request fails."""

    def __init__(self, message: str, safe_message: str | None = None) -> None:
        super().__init__(message)
        self.safe_message = safe_message or message


class RedmineClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: int = 15,
    ) -> None:
        self.base_url = base_url.strip()
        self.api_root_url = _build_api_root_url(self.base_url)
        self.projects_url = _build_api_url(self.api_root_url, "projects.json")
        self.api_key = api_key
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._session: aiohttp.ClientSession | None = None

        if not self.base_url.strip() or not self.api_key.strip():
            raise RedmineConfigError("Redmine base URL and API key are required")

    async def __aenter__(self) -> "RedmineClient":
        self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        if self._session:
            await self._session.close()

    async def get_projects(self) -> list[dict[str, Any]]:
        projects: list[dict[str, Any]] = []
        offset = 0
        limit = 100

        while True:
            data = await self._get_json(
                "projects.json",
                params={"offset": offset, "limit": limit},
            )
            page_projects = data.get("projects")

            if page_projects is None:
                return projects
            if not isinstance(page_projects, list):
                raise RedmineApiError(
                    "Unexpected Redmine response: projects is not a list"
                )

            projects.extend(
                project for project in page_projects if isinstance(project, dict)
            )

            total_count = data.get("total_count")
            current_limit = data.get("limit", limit)
            current_offset = data.get("offset", offset)

            if not all(
                isinstance(value, int)
                for value in (total_count, current_limit, current_offset)
            ):
                return projects
            if current_offset + current_limit >= total_count:
                return projects

            offset = current_offset + current_limit

    async def get_current_user(self) -> dict[str, Any]:
        data = await self._get_json("users/current.json")
        user = data.get("user")

        if not isinstance(user, dict):
            raise RedmineApiError("Unexpected Redmine response: user is not an object")

        return user

    async def get_project(self, project_id: int | str) -> dict[str, Any]:
        data = await self._get_json(f"projects/{project_id}.json")
        project = data.get("project")

        if not isinstance(project, dict):
            raise RedmineApiError("Unexpected Redmine response: project is not an object")

        return project

    async def get_issues(
        self,
        project_id: int | str,
        offset: int = 0,
        limit: int = 10,
        assigned_to_id: int | str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, int | str] = {
            "project_id": project_id,
            "status_id": "*",
            "offset": offset,
            "limit": limit,
            "sort": "updated_on:desc",
        }
        if assigned_to_id is not None:
            params["assigned_to_id"] = assigned_to_id

        data = await self._get_json(
            "issues.json",
            params=params,
        )
        issues = data.get("issues")

        if issues is None:
            issues = []
        if not isinstance(issues, list):
            raise RedmineApiError("Unexpected Redmine response: issues is not a list")

        return {
            "issues": [issue for issue in issues if isinstance(issue, dict)],
            "total_count": _as_int(data.get("total_count"), len(issues)),
            "offset": _as_int(data.get("offset"), offset),
            "limit": _as_int(data.get("limit"), limit),
        }

    async def get_issue(self, issue_id: int) -> dict[str, Any]:
        data = await self._get_json(f"issues/{issue_id}.json")
        issue = data.get("issue")

        if not isinstance(issue, dict):
            raise RedmineApiError("Unexpected Redmine response: issue is not an object")

        return issue

    async def get_time_entry_activities(self) -> list[dict[str, Any]]:
        data = await self._get_json("enumerations/time_entry_activities.json")
        activities = data.get("time_entry_activities")

        if activities is None:
            return []
        if not isinstance(activities, list):
            raise RedmineApiError(
                "Unexpected Redmine response: time_entry_activities is not a list"
            )

        return [activity for activity in activities if isinstance(activity, dict)]

    async def create_time_entry(
        self,
        issue_id: int,
        hours: float,
        spent_on: str,
        activity_id: int,
        comments: str,
    ) -> dict[str, Any]:
        data = await self._post_json(
            "time_entries.json",
            payload={
                "time_entry": {
                    "issue_id": issue_id,
                    "hours": hours,
                    "spent_on": spent_on,
                    "activity_id": activity_id,
                    "comments": comments,
                }
            },
        )
        time_entry = data.get("time_entry")

        if not isinstance(time_entry, dict):
            return {}

        return time_entry

    async def _get_json(
        self,
        path: str,
        params: dict[str, int | str] | None = None,
    ) -> dict[str, Any]:
        if not self._session:
            raise RedmineApiError("Redmine client session is not initialized")

        url = _resolve_api_url(self.api_root_url, path)
        headers = {
            "X-Redmine-API-Key": self.api_key,
            "Accept": "application/json",
        }

        try:
            async with self._session.get(
                url,
                headers=headers,
                params=params,
            ) as response:
                if response.status >= 400:
                    raise RedmineApiError(
                        f"Redmine returned HTTP {response.status}",
                        _build_status_message(response.status),
                    )

                try:
                    data = await response.json()
                except aiohttp.ContentTypeError as error:
                    raise RedmineApiError(
                        "Redmine returned non-JSON response",
                        "Redmine ответил не JSON-данными. Проверьте, что REST API "
                        "включен в Redmine и адрес RDM_BASE_URL указан без пути "
                        "к проекту.",
                    ) from error
        except asyncio.TimeoutError as error:
            raise RedmineApiError(
                "Redmine request timed out",
                "Redmine слишком долго не отвечает. Попробуйте еще раз позже "
                "или проверьте доступность сети/VPN.",
            ) from error
        except aiohttp.ClientError as error:
            raise RedmineApiError(
                "Failed to connect to Redmine",
                "Не удалось подключиться к Redmine. Проверьте адрес сервера, "
                "доступность сети/VPN и SSL-сертификат.",
            ) from error

        if not isinstance(data, dict):
            raise RedmineApiError("Unexpected Redmine response: root is not an object")

        return data

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._session:
            raise RedmineApiError("Redmine client session is not initialized")

        url = _resolve_api_url(self.api_root_url, path)
        headers = {
            "X-Redmine-API-Key": self.api_key,
            "Accept": "application/json",
        }

        try:
            async with self._session.post(url, headers=headers, json=payload) as response:
                if response.status >= 400:
                    safe_message = await _build_response_error_message(response)
                    raise RedmineApiError(
                        f"Redmine returned HTTP {response.status}",
                        safe_message,
                    )

                if response.status == 204:
                    return {}

                try:
                    data = await response.json()
                except aiohttp.ContentTypeError as error:
                    raise RedmineApiError(
                        "Redmine returned non-JSON response",
                        "Redmine принял запрос, но ответил не JSON-данными.",
                    ) from error
        except asyncio.TimeoutError as error:
            raise RedmineApiError(
                "Redmine request timed out",
                "Redmine слишком долго не отвечает. Попробуйте еще раз позже "
                "или проверьте доступность сети/VPN.",
            ) from error
        except aiohttp.ClientError as error:
            raise RedmineApiError(
                "Failed to connect to Redmine",
                "Не удалось подключиться к Redmine. Проверьте адрес сервера, "
                "доступность сети/VPN и SSL-сертификат.",
            ) from error

        if not isinstance(data, dict):
            raise RedmineApiError("Unexpected Redmine response: root is not an object")

        return data


def _build_status_message(status: int) -> str:
    if status == 401:
        return (
            "Redmine вернул HTTP 401. Обычно это значит, что RDM_API_KEY неверный "
            "или REST API выключен в настройках Redmine."
        )
    if status == 403:
        return (
            "Redmine вернул HTTP 403. Ключ принят, но у пользователя нет прав "
            "на просмотр списка проектов."
        )
    if status == 404:
        return (
            "Redmine вернул HTTP 404 для /projects.json. Проверьте RDM_BASE_URL: "
            "нужно указать только базовый адрес, например https://rdm.youzum.com."
        )
    if status >= 500:
        return (
            f"Redmine вернул HTTP {status}. Это похоже на ошибку сервера Redmine "
            "или прокси."
        )

    return f"Redmine вернул HTTP {status}."


async def _build_response_error_message(response: aiohttp.ClientResponse) -> str:
    message = _build_status_message(response.status)

    try:
        data = await response.json()
    except (aiohttp.ContentTypeError, ValueError):
        return message

    errors = data.get("errors") if isinstance(data, dict) else None
    if isinstance(errors, list) and errors:
        clean_errors = [str(error) for error in errors[:5]]
        return message + "\nОшибки Redmine: " + "; ".join(clean_errors)

    return message


def _build_api_root_url(configured_url: str) -> str:
    parsed = urlsplit(configured_url.strip())
    path = parsed.path.rstrip("/")

    if path.endswith("/projects.json"):
        root_path = path.removesuffix("/projects.json")
    elif path.endswith("/projects"):
        root_path = path.removesuffix("/projects")
    elif "/projects/" in path:
        root_path = path.split("/projects/", 1)[0]
    else:
        root_path = path

    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            root_path.rstrip("/"),
            "",
            "",
        )
    )


def _build_api_url(api_root_url: str, path: str) -> str:
    return f"{api_root_url.rstrip('/')}/{path.lstrip('/')}"


def _resolve_api_url(api_root_url: str, path: str) -> str:
    parsed = urlsplit(path)
    if parsed.scheme and parsed.netloc:
        return path

    return _build_api_url(api_root_url, path)


def _as_int(value: Any, fallback: int) -> int:
    return value if isinstance(value, int) else fallback
