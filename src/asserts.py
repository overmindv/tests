"""Assert-хелперы с авто-шагами Allure: asserts.equal, not_equal, ...

Каждый assert автоматически становится шагом-проверкой вида
`Check: (equal) <message>` в отчёте Allure — тест читается как сценарий
без ручного вызова allure-шагов.
"""
from __future__ import annotations

import inspect
import time
from typing import Any, Callable

import allure

from src import report


def _step(title: str) -> Callable:
    """Декоратор: оборачивает вызов в allure-шаг, форматируя title по аргументам.

    assert-функции принимают `message` чаще всего позиционно
    (`asserts.equal(a, b, "сообщение")`), поэтому связываем аргументы вызова
    с именами параметров функции, чтобы плейсхолдеры вида {message}
    подставлялись корректно (лишние kwargs `format` игнорирует).
    """

    def decorate(func: Callable) -> Callable:
        param_names = list(inspect.signature(func).parameters)

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = dict(zip(param_names, args))
            bound.update(kwargs)
            formatted = title.format(**bound)
            with report.step(formatted):
                return func(*args, **kwargs)

        return wrapper

    return decorate


def __fail(message: str, actual: Any = None, expected: Any = None) -> None:
    detail = message
    if actual is not None or expected is not None:
        detail += f"\nactual: {actual!r}\nexpected: {expected!r}"
    raise AssertionError(detail)


@_step("Check: (equal) {message}")
def equal(actual: Any, expected: Any, message: str) -> None:
    """actual == expected, иначе фейл с подробностями."""
    if not actual == expected:
        __fail(message, actual=actual, expected=expected)


@_step("Check: (not_equal) {message}")
def not_equal(actual: Any, expected: Any, message: str) -> None:
    if not actual != expected:
        __fail(message, actual=actual, expected=expected)


@_step("Check: (in) {message}")
def is_in(item: Any, container: Any, message: str) -> None:
    if item not in container:
        __fail(message, actual=item, expected=container)


@_step("Check: (not_in) {message}")
def is_not_in(item: Any, container: Any, message: str) -> None:
    if item in container:
        __fail(message, actual=item, expected=container)


@_step("Check: (is_empty) {message}")
def is_empty(value: Any, message: str, allow_none: bool = False) -> None:
    if allow_none and value is None:
        return
    if value:
        __fail(f"{message} (ожидали пустое, получили непустое)", actual=value)


@_step("Check: (is_not_empty) {message}")
def is_not_empty(value: Any, message: str) -> None:
    if not value:
        __fail(f"{message} (ожидали непустое, получили пустое)", actual=value)


@_step("Check: (is_true) {message}")
def is_true(value: Any, message: str) -> None:
    if not value:
        __fail(message, actual=value, expected=True)


@_step("Check: (is_false) {message}")
def is_false(value: Any, message: str) -> None:
    if value:
        __fail(message, actual=value, expected=False)


@_step("Check: (greater_than) {message}")
def greater_than(actual: Any, expected: Any, message: str) -> None:
    if not actual > expected:
        __fail(message, actual=actual, expected=f"> {expected}")


@_step("Check: (contains) {message}")
def contains(text: str, fragment: str, message: str) -> None:
    if fragment not in text:
        __fail(message, actual=fragment, expected=text)


@_step("Check: (wait) {message}")
def wait(
    condition: Callable[[], Any],
    timeout: float = 20.0,
    interval: float = 0.5,
    message: str = "Не дождались выполнения условия",
) -> Any:
    """Поллинг условия до наступления таймаута.

    :param condition: функция-предикат; truthy-результат считается успехом.
    :returns: последнее truthy-значение (обычно True или значение).
    :raises AssertionError: если условие так и не выполнилось.
    """
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = condition()
        if last:
            return last
        time.sleep(interval)
    __fail(f"{message}. Таймаут {timeout} сек. Последнее значение: {last!r}")
