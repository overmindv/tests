"""Корневой conftest: глобальные pytest-хуки и интеграция с Allure.

Сюда НЕ добавляем сценарии. Здесь только «инфраструктура отчёта»:
- направляем allure-results в каталог,
- автоматически превращаем docstring теста в описание в отчёте Allure,
- по завершении сессии пишем environment.properties (BASE_URL и т.п.).
"""
from __future__ import annotations

import os
from pathlib import Path

import allure
import pytest

from src.configuration import config

ALLURE_RESULTS_DIR = Path(os.getenv("ALLURE_RESULTS_DIR", "allure-results"))


@pytest.hookimpl(tryfirst=True)
def pytest_configure(cfg: pytest.Config) -> None:
    """Задать каталог для allure-report базово (если не задан флагом)."""
    if not getattr(cfg.option, "allure_report_dir", None):
        cfg.option.allure_report_dir = str(ALLURE_RESULTS_DIR)
    if not ALLURE_RESULTS_DIR.exists():
        ALLURE_RESULTS_DIR.mkdir(parents=True, exist_ok=True)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    """Докстринга теста становится описанием Allure-кейса."""
    doc = getattr(item.function, "__doc__", None)
    if doc:
        allure.dynamic.description("".join(doc))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:  # noqa: ARG001
    """Записать environment.properties в allure-results."""
    ALLURE_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    env_file = ALLURE_RESULTS_DIR / "environment.properties"
    with env_file.open("w") as f:
        f.write(f"BASE_URL={config.BASE_URL}\n")
        f.write("Environment=overmindv-e2e\n")
