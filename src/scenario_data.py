from __future__ import annotations

import secrets
from collections.abc import Callable
from contextlib import ExitStack
from typing import Any
from uuid import UUID

from src import generate, report
from src.api.gateway import AuthContext, Gateway, Task


class ScenarioData:
    def __init__(self, api: Gateway, cleanup: ExitStack) -> None:
        self._api = api
        self._cleanup = cleanup

    def user(self) -> AuthContext:
        suffix = generate.uuid4()[:20]
        email = f"e2e-{suffix}@example.test"
        username = f"e2e_{suffix}"
        actor = self._api.register(email, f"Aa9!{secrets.token_urlsafe(18)}", username)
        if actor.is_superuser or actor.is_admin or actor.email != email or actor.username != username:
            raise RuntimeError("Registration did not return the new test account")
        self._keep("user", actor.user_id, actor, self._api.delete_user)
        return actor

    def topic(self, admin: AuthContext, title: str) -> str:
        topic = self._api.create_topic(admin, f"{title} {generate.uuid4()}")
        return self._keep("topic", topic["id"], admin, self._api.delete_topic)

    def task(self, admin: AuthContext, **fields: Any) -> Task:
        task = self._api.create_task(admin, **fields)
        self._keep("task", task.id, admin, self._api.delete_task)
        return task

    def _keep(
        self,
        kind: str,
        resource_id: str,
        actor: AuthContext,
        delete: Callable[[AuthContext, str], bool],
    ) -> str:
        parsed = UUID(resource_id)
        if not parsed.int:
            raise ValueError(f"Empty {kind} ID in creation response")
        key = str(parsed)
        self._cleanup.callback(self._delete, kind, key, actor, delete)
        return key

    @staticmethod
    def _delete(kind: str, resource_id: str, actor: AuthContext, delete: Callable[[AuthContext, str], bool]) -> None:
        with report.step("Удаляем тестовый ресурс {kind} {id}", kind=kind, id=resource_id):
            if delete(actor, resource_id) is not True:
                raise RuntimeError(f"Could not remove test {kind} {resource_id}")
