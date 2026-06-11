import os
from dataclasses import dataclass

from dotenv import load_dotenv

from rdm_client import RedmineConfigError


@dataclass(frozen=True)
class Settings:
    bot_token: str
    rdm_base_url: str


def load_settings() -> Settings:
    load_dotenv()

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    rdm_base_url = os.getenv("RDM_BASE_URL", "").strip()

    missing = [
        name
        for name, value in (
            ("BOT_TOKEN", bot_token),
            ("RDM_BASE_URL", rdm_base_url),
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
    )
