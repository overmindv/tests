"""GraphQL-клиент к api-gateway.

Выполняет POST {BASE_URL}{GRAPHQL_PATH} с телом {query, variables},
проверяет envelope на errors и возвращает содержимое поля "data".
Опционально передаётся JWT в заголовке Authorization: Bearer.
"""
from __future__ import annotations

import json
from typing import Any

import requests

from src import check, report
from src.configuration import config
from src.http_error import HttpError

_PUBLIC_ERROR_CODES = frozenset({
    "ALREADY_EXISTS", "ATTACHMENTS_PENDING", "CANCELED", "DEADLINE_EXCEEDED", "FAILED_PRECONDITION",
    "GRAPHQL_VALIDATION_FAILED", "INTERNAL", "INVALID_ARGUMENT", "MERGE_CONFLICT", "NOT_FOUND",
    "PERMISSION_DENIED", "RESOURCE_EXHAUSTED", "REVIEW_REQUIRED", "REVISION_CONFLICT", "SERVICE_UNAVAILABLE",
    "UNAUTHENTICATED", "UNRESOLVED_REVIEW_THREADS",
})


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
        *,
        capture_body: bool = True,
    ) -> dict:
        """Выполнить GraphQL-операцию и вернуть поле `data` (dict).

        :param operation: имя операции (для шага/подписи).
        :param query: строка GraphQL (query/mutation).
        :param variables: переменные запроса.
        :param token: JWT для Authorization: Bearer (опционально).
        :param capture_body: сохранять тела запроса и ответа в отчете.
        :raises HttpError: при HTTP-статусе >= 400 или наличии errors в envelope.
        """
        with report.step("GraphQL: {operation}", operation=operation):
            report.redact({"token": token, "variables": variables})
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
            if not capture_body:
                return self._private_data(response.status_code, body)

            report.attach_json("graphql_request", payload)
            report.attach_json("graphql_response", body)

            if response.status_code >= 400:
                raise HttpError(
                    f"GraphQL HTTP {response.status_code}",
                    response=body,
                    status_code=response.status_code,
                )

            data = check.gql_success_response(body, message=f"Операция {operation}")
        return data or {}

    @staticmethod
    def _private_data(status_code: int, body: Any) -> dict:
        if status_code >= 400:
            raise HttpError("GraphQL HTTP error", status_code=status_code)
        if not isinstance(body, dict) or ("data" not in body and not body.get("errors")):
            raise HttpError("Invalid GraphQL response")
        if errors := body.get("errors"):
            public = []
            for error in errors if isinstance(errors, list) else ():
                if not isinstance(error, dict) or not isinstance(error.get("extensions"), dict):
                    continue
                code = error["extensions"].get("code")
                if isinstance(code, str) and code in _PUBLIC_ERROR_CODES:
                    public.append({"extensions": {"code": code}})
            raise HttpError("GraphQL operation rejected", response={"errors": public})
        data = body.get("data")
        if data is not None and not isinstance(data, dict):
            raise HttpError("Invalid GraphQL response")
        return data or {}

    def execute_upload(
        self,
        operation: str,
        query: str,
        variables: dict[str, Any],
        file_map: dict[str, list[str]],
        files: dict[str, tuple[str, bytes, str]],
        token: str | None = None,
    ) -> dict:
        """Выполнить GraphQL-операцию с загрузкой файла (multipart-контракт).

        Части запроса:
        - `operations` — JSON `{query, variables}` (поле файла = null);
        - `map` — JSON `{"0": ["variables.input.file"]}`;
        - часть `0` — сам файл с filename и Content-Type.

        :param operation: имя операции (для шага/подписи).
        :param query: строка GraphQL (mutation).
        :param variables: переменные запроса (поле-файл должно быть None).
        :param file_map: сопоставление частей multipart с путями в variables.
        :param files: {ключ_части: (filename, bytes, Content-Type)}.
        :param token: JWT для Authorization: Bearer (опционально).
        :raises HttpError: при HTTP-статусе >= 400 или errors в envelope.
        """
        with report.step("GraphQL upload: {operation}", operation=operation):
            report.redact({"token": token, "variables": variables})
            headers = {"Accept": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"

            form: dict[str, Any] = {
                "operations": (None, json.dumps({"query": query, "variables": variables})),
                "map": (None, json.dumps(file_map)),
            }
            for key, (filename, content, content_type) in files.items():
                form[key] = (filename, content, content_type)

            response = self.session.post(
                self.base_url + self.path,
                files=form,
                headers=headers,
                timeout=self.timeout,
            )

            body = self._safe_json(response)
            report.attach_json(
                "graphql_upload_request",
                {"query": query, "variables": variables, "map": file_map,
                 "files": {k: {"filename": v[0], "bytes": len(v[1]), "content_type": v[2]}
                           for k, v in files.items()}},
            )
            report.attach_json("graphql_response", body)

            if response.status_code >= 400:
                raise HttpError(
                    f"GraphQL upload HTTP {response.status_code}",
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
