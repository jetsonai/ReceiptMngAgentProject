from __future__ import annotations

import os

import httpx

from notion_config import load_runtime_config
from env_loader import load_project_env


def _status_prefix(ok: bool) -> str:
    return "OK" if ok else "FAIL"


def check_openai(api_key: str) -> tuple[bool, str]:
    try:
        response = httpx.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=20,
        )
        if response.status_code == 200:
            return True, "OpenAI API key가 유효합니다."
        if response.status_code == 401:
            return False, f"OpenAI API key 인증 실패(401): {response.text.strip()}"
        return False, f"OpenAI API 확인 실패({response.status_code}): {response.text.strip()}"
    except Exception as exc:
        return False, f"OpenAI API 요청 오류: {exc}"


def check_notion(token: str) -> tuple[bool, str]:
    try:
        response = httpx.get(
            "https://api.notion.com/v1/users/me",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": os.getenv("NOTION_VERSION", "2022-06-28"),
            },
            timeout=20,
        )
        if response.status_code == 200:
            return True, "Notion token이 유효합니다."
        if response.status_code == 401:
            return False, f"Notion token 인증 실패(401): {response.text.strip()}"
        return False, f"Notion API 확인 실패({response.status_code}): {response.text.strip()}"
    except Exception as exc:
        return False, f"Notion API 요청 오류: {exc}"


def main() -> int:
    env_path = load_project_env()
    print(f".env loaded: {env_path if env_path else 'not found'}")

    openai_key = os.getenv("OPENAI_API_KEY")
    notion_token = os.getenv("NOTION_TOKEN")
    config = load_runtime_config()

    all_ok = True

    if openai_key:
        ok, message = check_openai(openai_key)
        print(f"[{_status_prefix(ok)}] {message}")
        all_ok &= ok
    else:
        print("[FAIL] OPENAI_API_KEY가 없습니다.")
        all_ok = False

    if notion_token:
        ok, message = check_notion(notion_token)
        print(f"[{_status_prefix(ok)}] {message}")
        all_ok &= ok
    else:
        print("[FAIL] NOTION_TOKEN이 없습니다.")
        all_ok = False

    if config.notion_database_id:
        print("[OK] NOTION_DATABASE_URL/ID에서 database_id를 확인했습니다.")
    else:
        print("[FAIL] NOTION_DATABASE_URL 또는 NOTION_DATABASE_ID로 database_id를 만들 수 없습니다.")
        all_ok = False

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
