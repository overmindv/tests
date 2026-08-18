"""GraphQL-клиент к api-gateway.

Выполняет POST {BASE_URL}{GRAPHQL_PATH} с телом {query, variables},
проверяет envelope на errors и возвращает содержимое поля "data".
Опционально передаётся JWT в заголовке Authorization: Bearer.
"""
from __future__ import annotations

from typing import Any

import requests

from src import check, report
from src.configuration import config


class GraphQLClient:
    def __init__(
        self,
        base_url: str | None = None,
        path: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.base_url = (base_url or config.BASE_URL).rstrip("/")
        self.path = path or config.GRAPHQL_PATH
        self.timeout = timeout or config.API_READ_TIMEOUT
        self.session = requests.Session()

    def execute(
        self,
        operation: str,
        query: str,
        variables: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> dict:
        """Выполнить GraphQL-операцию и вернуть поле `data` (dict).

        :param operation: имя операции (для шага/подписи).
        :param query: строка GraphQL (query/mutation).
        :param variables: переменные запроса.
        :param token: JWT для Authorization: Bearer (опционально).
        :raises HttpError: при HTTP-статусе >= 400 или наличии errors в envelope.
        """
        with report.step("GraphQL: {operation}", operation=operation):
            headers = {"Content-Type": "application/json", "Accept": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"

            payload: dict[str, Any] = {"query": query}
            if variables:
                payload["variables"] = variables

            response = self.session.post(
                self.base_url + self.path,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )

            body = self._safe_json(response)
            report.attach_json("graphql_request", payload)
            report.attach_json("graphql_response", body)

            if response.status_code >= 400:
                from src.http_error import HttpError

                raise HttpError(
                    f"GraphQL HTTP {response.status_code}",
                    response=body,
                    status_code=response.status_code,
                )

            data = check.gql_success_response(body, message=f"Операция {operation}")
        return data or {}

    @staticmethod
    def _safe_json(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text}
