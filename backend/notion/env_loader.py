from __future__ import annotations

import os
from pathlib import Path


_ALIASES = {
    "openai_api_key": "OPENAI_API_KEY",
    "notion_token": "NOTION_TOKEN",
    "notion_database_id": "NOTION_DATABASE_ID",
    "notion_database_url": "NOTION_DATABASE_URL",
    "notion_version": "NOTION_VERSION",
    "openai_model": "OPENAI_MODEL",
}


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        values[key] = value
    return values


def load_project_env() -> Path | None:
    start_dir = Path(__file__).resolve().parent
    for directory in (start_dir, *start_dir.parents):
        env_path = directory / ".env"
        if not env_path.is_file():
            continue

        values = _parse_env_file(env_path)
        for key, value in values.items():
            os.environ.setdefault(key, value)
            alias = _ALIASES.get(key.lower())
            if alias:
                os.environ.setdefault(alias, value)
        return env_path

    return None
