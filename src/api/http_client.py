"""Базовый REST HTTP-клиент на requests.

Каждый успешный запрос проходит через `check.ok_response` и пишет
Allure-шаг. Используется для REST-вызовов (например, health-check
api-gateway) и как основа для более специфичных клиентов.
"""
from __future__ import annotations

from typing import Any

import requests

from src import check, report
from src.configuration import config


class BaseClient:
    """Тонкая обёртка над requests.Session.

    :param base_url: базовый URL (http://host:port).
    :param default_headers: заголовки, добавляемые к каждому запросу.
    :param timeout: read-timeout в секундах.
    """

    def __init__(
        self,
        base_url: str,
        default_headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_headers = default_headers or {}
        self.timeout = timeout or config.API_READ_TIMEOUT
        self.session = requests.Session()

    def request(
        self,
        method: str,
        url: str,
        *,
        json: Any = None,
        params: dict | None = None,
        headers: dict | None = None,
        expected_code: int | None = None,
        **kwargs: Any,
    ) -> dict | list | None:
        full_url = self.base_url + url if url.startswith("/") else self.base_url + "/" + url
        with report.step("{method} {url}", method=method.upper(), url=full_url):
            merged_headers = {**self.default_headers, **(headers or {})}
            response = self.session.request(
                method,
                full_url,
                json=json,
                params=params,
                headers=merged_headers,
                timeout=self.timeout,
                **kwargs,
            )
            report.attach_json("request_body", json)
            report.attach_json("response_body", self._safe_json(response))
            return check.ok_response(response, expected_code=expected_code)

    def get(self, url: str, **kwargs: Any) -> dict | list | None:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> dict | list | None:
        return self.request("POST", url, **kwargs)

    @staticmethod
    def _safe_json(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return response.text
