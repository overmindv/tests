"""Чтение переменных окружения (и .env для локального запуска)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Загружаем .env из корня репозитория (если есть) — для локального запуска.
_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_ROOT / ".env")


def get(key: str, default: str | None = None) -> str | None:
    """Значение env как строка, либо default при отсутствии."""
    return os.getenv(key, default)


def get_bool(key: str, default: bool = False) -> bool:
    """Значение env как bool ('true'/'1'/'yes' -> True)."""
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"true", "1", "yes", "on"}


def get_int(key: str, default: int = 0) -> int:
    """Значение env как int, либо default при отсутствии/ошибке."""
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
