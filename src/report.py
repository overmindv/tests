"""Отчёты/шаги Allure: report.step, report.attach_*.

Главная идея boucle, которую переносим сюда: каждый значимый шаг теста
оборачивается в `with report.step("..."):`, а каждый assert — в
`asserts.*`, который автоматически создаёт шаг-проверку. Так отчёт
читается как пошаговый сценарий без ручного вызова allure-шагов везде.
"""
from __future__ import annotations

import json
from contextlib import AbstractContextManager, contextmanager
from typing import Any

import allure

# Переиспользуемые типы вложений.
TEXT = allure.attachment_type.TEXT
JSON = allure.attachment_type.JSON
HTML = allure.attachment_type.HTML


@contextmanager
def step(title: str, *args: Any, **kwargs: Any) -> AbstractContextManager[None]:
    """Открыть Allure-шаг с заголовком. title поддерживает str.format-подстановку.

    Пример:
        with report.step("Проверяем создание задачи {}:", task_id):
            ...
    """
    with allure.step(title, *args, **kwargs):
        yield


def attach_text(name: str, text: str) -> None:
    allure.attach(text, name=name, attachment_type=TEXT)


def attach_json(name: str, obj: Any) -> None:
    payload = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    allure.attach(payload, name=name, attachment_type=JSON)


def attach_html(name: str, html: str) -> None:
    allure.attach(html, name=name, attachment_type=HTML)


@contextmanager
def soft_check() -> AbstractContextManager[list[str]]:
    """Контекст мягких проверок: AssertionError внутри не роняет тест сразу.

    Ошибки накапливаются в список, который отдаётся наружу через `as`.
    Если внутри контекста были падения — они НЕ кидаются автоматически
    (чтобы не было скрытых исключений), ответственность на авторе теста.

    Пример:
        with report.soft_check() as errors:
            asserts.equal(a, b, "первая проверка")
            asserts.equal(c, d, "вторая проверка")
        assert not errors, errors
    """
    errors: list[str] = []

    try:
        yield errors
    except AssertionError as exc:  # прямая защита от необработанного assert внутри
        errors.append(str(exc))
