"""Типизированный фасад api-gateway: методы сценариев поверх GraphQL-клиента.

Именно этот модуль использует тест-разработчик в сценариях. Методы
принимают/возвращают pydantic-модели и AuthContext (не сырые dict),
чтобы тест оставался читаемым: `task.id`, `submission.verdict`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from src import generate, report
from src.api.graphql_client import GraphQLClient

# ------------------------------- Модели ответов -------------------------------
_USER_FIELDS = "id email username roles isAdmin isSuperuser"


class TaskOption(BaseModel):
    id: str
    text: str
    position: int
    isCorrect: bool


class Task(BaseModel):
    id: str
    status: str
    taskVersionId: str
    versionNumber: int
    title: str
    taskType: str
    difficulty: str
    options: list[TaskOption] = Field(default_factory=list)


class Submission(BaseModel):
    id: str
    correct: bool
    verdict: str
    correctOptionIds: list[str] = Field(default_factory=list)
    taskUpdated: bool | None = None
    latestTaskVersionId: str | None = None
    latestVersionNumber: int | None = None


@dataclass
class AuthContext:
    """Контекст аутентифицированного пользователя (для подготовки данных)."""

    token: str
    user_id: str
    email: str
    username: str
    is_admin: bool = False
    is_superuser: bool = False
    password: str | None = None


# ------------------------------- GraphQL-строки -------------------------------
_Q = {
    "register": (
        "mutation Register($input: RegisterInput!) {"
        f" register(input: $input) {{ token expiresAt user {{ {_USER_FIELDS} }} }}"
        "}"
    ),
    "login": (
        "mutation Login($input: LoginInput!) {"
        f" login(input: $input) {{ token expiresAt user {{ {_USER_FIELDS} }} }}"
        "}"
    ),
    "set_admin": (
        "mutation SetUserAdminByUsername($username: String!, $admin: Boolean!) {"
        f" setUserAdminByUsername(username: $username, admin: $admin) {{ {_USER_FIELDS} }}"
        "}"
    ),
    "delete_user": "mutation DeleteUser($id: ID!) { deleteUser(id: $id) }",
    "create_task": (
        "mutation CreateITTask($input: ITTaskInput!) {"
        " createITTask(input: $input) {"
        " id status taskVersionId versionNumber title taskType difficulty"
        " options { id text position isCorrect }"
        " }"
        "}"
    ),
    "change_status": (
        "mutation ChangeITTaskStatus($id: ID!, $status: ITTaskStatus!) {"
        " changeITTaskStatus(id: $id, status: $status) { id status }"
        "}"
    ),
    "submit_answer": (
        "mutation SubmitITTaskAnswer($taskId: ID!, $input: ITSubmissionInput!) {"
        " submitITTaskAnswer(taskId: $taskId, input: $input) {"
        " id correct verdict correctOptionIds taskUpdated latestTaskVersionId latestVersionNumber"
        " }"
        "}"
    ),
    "my_submissions": (
        "query MyITSubmissions($taskId: ID, $pagination: PaginationInput) {"
        " myITSubmissions(taskId: $taskId, pagination: $pagination) {"
        " items { id correct verdict taskVersionNumber taskUpdated createdAt }"
        " limit offset"
        " }"
        "}"
    ),
}


def _token(ctx_or_token: AuthContext | str | None = None) -> str | None:
    """Извлечь токен из AuthContext либо использовать строку токена."""
    if isinstance(ctx_or_token, AuthContext):
        return ctx_or_token.token
    return ctx_or_token


class Gateway:
    """Единая точка входа в api-gateway для e2e-сценариев."""

    def __init__(self, client: GraphQLClient | None = None) -> None:
        self.gql = client or GraphQLClient()

    # ----------------------------------- Auth ---------------------------------
    def register(self, email: str, password: str, username: str) -> AuthContext:
        with report.step("Регистрируем пользователя {email}", email=email):
            data = self.gql.execute(
                "register",
                _Q["register"],
                {"input": {"email": email, "password": password, "username": username}},
            )
        return self._auth_from_payload(data["register"], password=password)

    def login(self, email: str, password: str) -> AuthContext:
        with report.step("Логинимся как {email}", email=email):
            data = self.gql.execute(
                "login",
                _Q["login"],
                {"input": {"email": email, "password": password}},
            )
        return self._auth_from_payload(data["login"], password=password)

    def set_admin_by_username(self, admin: AuthContext, username: str, admin_flag: bool = True) -> dict:
        with report.step("Назначаем роль admin пользователю {username}", username=username):
            return self.gql.execute(
                "set_admin",
                _Q["set_admin"],
                {"username": username, "admin": admin_flag},
                token=admin.token,
            )["setUserAdminByUsername"]

    def delete_user(self, ctx: AuthContext, user_id: str) -> bool:
        with report.step("Удаляем пользователя {user_id}", user_id=user_id):
            return self.gql.execute("delete_user", _Q["delete_user"], {"id": user_id}, token=ctx.token)["deleteUser"]

    def create_admin(self, email: str, password: str, username: str) -> AuthContext:
        """Зарегистрировать пользователя и сделать его администратором."""
        with report.step("Создаём администратора {username}", username=username):
            candidate = self.register(email, password, username)
            self.set_admin_by_username(candidate, username, admin_flag=True)
            return self.login(email, password)

    # ----------------------------------- Tasks --------------------------------
    def create_task(
        self,
        admin: AuthContext,
        title: str,
        statement: str,
        options: list[tuple[str, bool]],
        task_type: str = "single_choice",
        difficulty: str = "easy",
    ) -> Task:
        task_input: dict[str, Any] = {
            "title": title,
            "statement": statement,
            "taskType": task_type,
            "difficulty": difficulty,
            "options": [{"text": text, "isCorrect": is_correct} for text, is_correct in options],
        }
        with report.step("Создаём задачу '{title}'", title=title):
            data = self.gql.execute(
                "create_task",
                _Q["create_task"],
                {"input": task_input},
                token=admin.token,
            )
        return Task.model_validate(data["createITTask"])

    def change_task_status(self, admin: AuthContext, task_id: str, status: str = "published") -> dict:
        """Изменить статус задачи. Возвращает {'id': ..., 'status': ...}."""
        with report.step("Переводим задачу {task_id} в статус {status}", task_id=task_id, status=status):
            result = self.gql.execute(
                "change_status",
                _Q["change_status"],
                {"id": task_id, "status": status},
                token=admin.token,
            )
        return result["changeITTaskStatus"]

    def submit_answer(
        self,
        user: AuthContext,
        task_id: str,
        task_version_id: str,
        selected_option_ids: list[str],
        idempotency_key: str | None = None,
    ) -> Submission:
        with report.step("Отправляем ответ на задачу {task_id}", task_id=task_id):
            data = self.gql.execute(
                "submit_answer",
                _Q["submit_answer"],
                {
                    "taskId": task_id,
                    "input": {
                        "taskVersionId": task_version_id,
                        "idempotencyKey": idempotency_key or generate.uuid4(),
                        "selectedOptionIds": selected_option_ids,
                    },
                },
                token=user.token,
            )
        return Submission.model_validate(data["submitITTaskAnswer"])

    def my_submissions(self, user: AuthContext, task_id: str | None = None) -> list[dict]:
        with report.step("Получаем историю решений по задаче {task_id}", task_id=task_id or "—"):
            data = self.gql.execute(
                "my_submissions",
                _Q["my_submissions"],
                {"taskId": task_id, "pagination": {"limit": 50, "offset": 0}},
                token=user.token,
            )
        return data.get("myITSubmissions", {}).get("items", [])

    @staticmethod
    def _auth_from_payload(payload: dict, password: str | None) -> AuthContext:
        user = payload["user"]
        return AuthContext(
            token=payload["token"],
            user_id=user["id"],
            email=user["email"],
            username=user["username"],
            is_admin=user.get("isAdmin", False),
            is_superuser=user.get("isSuperuser", False),
            password=password,
        )
