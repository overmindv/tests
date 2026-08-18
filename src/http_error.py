"""Ошибка HTTP/GraphQL-взаимодействия. Наследует AssertionError,
чтобы тест падал как проваленная проверка, а не как исключение.
"""
from __future__ import annotations

from typing import Any


class HttpError(AssertionError):
    """Неуспешный ответ/поведение API.

    :param message: человекочитаемое описание.
    :param response: сырой ответ (опционально).
    :param status_code: HTTP-статус, если известен.
    """

    def __init__(
        self,
        message: str,
        response: Any | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message
        self.response = response
        self.status_code = status_code
        super().__init__(self._render())

    def _render(self) -> str:
        parts = [self.message]
        if self.status_code is not None:
            parts.append(f"status_code: {self.status_code}")
        if self.response is not None:
            parts.append(f"response: {self.response}")
        return "\n".join(parts)
