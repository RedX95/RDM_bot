import asyncio
import os

from dotenv import load_dotenv

from rdm_client import RedmineApiError, RedmineClient, RedmineConfigError


async def main() -> None:
    load_dotenv()

    base_url = os.getenv("RDM_BASE_URL", "").strip()
    api_key = os.getenv("RDM_API_KEY", "").strip()

    if not base_url or not api_key:
        raise RedmineConfigError("Заполните RDM_BASE_URL и RDM_API_KEY в .env")

    async with RedmineClient(base_url=base_url, api_key=api_key) as redmine:
        print(f"Проверяю Redmine API: {redmine.projects_url}")

        try:
            projects = await redmine.get_projects()
        except RedmineApiError as error:
            print("Ошибка:")
            print(error.safe_message)
            return

    print(f"OK. Получено проектов: {len(projects)}")
    for index, project in enumerate(projects[:10], start=1):
        name = project.get("name") or "Без названия"
        identifier = project.get("identifier")
        suffix = f" ({identifier})" if identifier else ""
        print(f"{index}. {name}{suffix}")

    if len(projects) > 10:
        print(f"...и еще {len(projects) - 10}")


if __name__ == "__main__":
    asyncio.run(main())
