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
    # python-dotenv 없이도 단순한 KEY=VALUE 형식의 .env를 읽기 위한 최소 파서.
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
    # 01 폴더부터 상위 폴더까지 올라가며 가장 가까운 .env를 한 번만 로드한다.
    start_dir = Path(__file__).resolve().parent
    for directory in (start_dir, *start_dir.parents):
        env_path = directory / ".env"
        if not env_path.is_file():
            continue

        values = _parse_env_file(env_path)
        for key, value in values.items():
            os.environ.setdefault(key, value)
            # 팀원이 소문자 키로 작성해도 실제 환경변수명으로 인식되게 보정한다.
            alias = _ALIASES.get(key.lower())
            if alias:
                os.environ.setdefault(alias, value)
        return env_path

    return None
