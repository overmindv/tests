"""Проверка HTTP/GraphQL-ответов: ok_response, gql_success_response."""
from __future__ import annotations

from typing import Any

import requests

from src.http_error import HttpError


def ok_response(
    response: requests.Response,
    message: str = "Запрос должен быть успешным",
    expected_code: int | None = None,
) -> dict | list | None:
    """Проверить HTTP-ответ и вернуть распарсенный JSON.

    :param response: сырой ответ requests.
    :param message: сообщение об ошибке.
    :param expected_code: если задан — требует именно этот статус.
    :raises HttpError: при несоответствии статуса.
    """
    if expected_code is not None and response.status_code != expected_code:
        raise HttpError(
            f"{message}. Ожидали HTTP {expected_code}, получили {response.status_code}",
            response=_safe_body(response),
            status_code=response.status_code,
        )
    if response.status_code >= 400:
        raise HttpError(
            f"{message}. Получили HTTP {response.status_code}",
            response=_safe_body(response),
            status_code=response.status_code,
        )
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text


def gql_success_response(data: dict, message: str = "GraphQL-запрос должен быть успешным") -> dict:
    """Проверить распарсенный GraphQL-ответ на отсутствие errors.

    :param data: распарсенный JSON-ответ GraphQL ({data, errors, ...}).
    :returns: содержимое поля "data".
    :raises HttpError: если в ответе есть errors.
    """
    errors = data.get("errors")
    if errors:
        raise HttpError(
            f"{message}. GraphQL вернул ошибки: {errors}",
            response=data,
        )
    return data.get("data", {})


def _safe_body(response: requests.Response) -> str:
    try:
        return response.text[:4000]
    except Exception:  # noqa: BLE001 - защита от непредвиденных ошибок чтения
        return "<не удалось прочитать тело ответа>"
