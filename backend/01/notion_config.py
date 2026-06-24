from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from env_loader import load_project_env
from notion_constants import (
    DEFAULT_NOTION_VERSION,
    DEFAULT_OPENAI_MODEL,
    NOTION_DATABASE_ID_ENV,
    NOTION_DATABASE_URL_ENV,
    NOTION_TOKEN_ENV,
    NOTION_VERSION_ENV,
    OPENAI_API_KEY_ENV,
    OPENAI_MODEL_ENV,
)


@dataclass(frozen=True)
class RuntimeConfig:
    openai_api_key: str | None
    openai_model: str
    notion_token: str | None
    notion_database_id: str | None
    notion_database_url: str | None
    notion_version: str


def _extract_database_id(value: str | None) -> str | None:
    if not value:
        return None

    candidate = value.strip()
    if not candidate:
        return None

    parsed = urlparse(candidate)
    if parsed.scheme and parsed.netloc:
        candidate = parsed.path.rsplit("/", 1)[-1]

    candidate = candidate.split("?", 1)[0].split("#", 1)[0]
    tail = candidate.rsplit("-", 1)[-1].replace("-", "")
    if re.fullmatch(r"[0-9a-fA-F]{32}", tail):
        return tail.lower()
    match = re.search(r"(?<![0-9a-fA-F])[0-9a-fA-F]{32}(?![0-9a-fA-F])", candidate)
    return match.group(0).lower() if match else None


def load_runtime_config() -> RuntimeConfig:
    load_project_env()
    notion_database_id = os.getenv(NOTION_DATABASE_ID_ENV)
    notion_database_url = os.getenv(NOTION_DATABASE_URL_ENV)

    return RuntimeConfig(
        openai_api_key=os.getenv(OPENAI_API_KEY_ENV),
        openai_model=os.getenv(OPENAI_MODEL_ENV, DEFAULT_OPENAI_MODEL),
        notion_token=os.getenv(NOTION_TOKEN_ENV),
        notion_database_id=notion_database_id or _extract_database_id(notion_database_url),
        notion_database_url=notion_database_url,
        notion_version=os.getenv(NOTION_VERSION_ENV, DEFAULT_NOTION_VERSION),
    )
