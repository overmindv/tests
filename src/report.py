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
from urllib.parse import quote

import allure

_SECRET_KEYS = {"password", "token", "accesstoken", "refreshtoken", "authorization", "cookie", "setcookie", "secret"}
_secret_values: set[str] = set()


def redact(value: Any) -> Any:
    """Copy diagnostics while masking credentials, including reflected secrets."""
    def remember(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                normalized = str(key).lower().replace("_", "").replace("-", "")
                if normalized in _SECRET_KEYS and isinstance(child, str) and child:
                    _secret_values.update((child, quote(child, safe=""), json.dumps(child)[1:-1]))
                else:
                    remember(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                remember(child)

    def clean(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: "[REDACTED]" if str(key).lower().replace("_", "").replace("-", "") in _SECRET_KEYS
                    else clean(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [clean(child) for child in item]
        if isinstance(item, str):
            for secret in sorted(_secret_values, key=len, reverse=True):
                item = item.replace(secret, "[REDACTED]")
        return item

    remember(value)
    return clean(value)


# Переиспользуемые типы вложений.
TEXT = allure.attachment_type.TEXT
JSON = allure.attachment_type.JSON
HTML = allure.attachment_type.HTML


@contextmanager
def step(heading: str, *args: Any, **kwargs: Any) -> AbstractContextManager[None]:
    """Открыть Allure-шаг с заголовком. heading поддерживает str.format-подстановку.

    Первый параметр назван `heading` (а не `title`), чтобы kwarg-плейсхолдеры
    вроде `title=`/`status=` не конфликтовали с именем параметра.

    Пример:
        with report.step("Проверяем создание задачи {}:", task_id):
            ...
    """
    formatted = redact(heading.format(*args, **kwargs))
    with allure.step(formatted):
        yield


def attach_text(name: str, text: str) -> None:
    allure.attach(redact(text), name=name, attachment_type=TEXT)


def attach_json(name: str, obj: Any) -> None:
    payload = json.dumps(redact(obj), ensure_ascii=False, indent=2, default=str)
    allure.attach(payload, name=name, attachment_type=JSON)


def attach_html(name: str, html: str) -> None:
    allure.attach(redact(html), name=name, attachment_type=HTML)


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
