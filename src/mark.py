"""Пользовательские марки pytest: mark.link, mark.skip, mark.non_blocker.

Маркеры `link` и `non_blocker` зарегистрированы в pyproject.toml
(секция [tool.pytest.ini_options.markers]), т.к. включён --strict-markers.
"""
from __future__ import annotations

from typing import Callable

import pytest


def link(url: str, issue: str = "issue") -> Callable:
    """Декоратор: привязывает тест к внешней ссылке (Jira/task).

    Пример:
        @mark.link("https://jit.o3.ru/browse/OVM-123")
        def test_something(): ...
    """
    return pytest.mark.link(url)


def skip(url: str, reason: str = "") -> Callable:
    """Декоратор: пропуск теста, пока не закрыта задача по ссылке."""
    return pytest.mark.skip(reason=f"{reason} (ссылка: {url})")


def non_blocker(func: Callable | None = None) -> Callable:
    """Декоратор: мягкая пометка теста (не блокирует релиз).

    Использование: @mark.non_blocker  или  @mark.non_blocker()
    """

    def deco(f: Callable) -> Callable:
        pytest.mark.non_blocker(f)
        return f

    if func is not None:
        return deco(func)
    return deco
