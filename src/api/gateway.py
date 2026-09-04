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
from src.configuration import config

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


class ITExecutionTestResult(BaseModel):
    testId: str
    verdict: str
    stdout: str = ""
    stderr: str = ""
    durationMs: int = 0
    memoryBytes: int = 0


class ITCodeSubmission(BaseModel):
    id: str
    status: str
    taskId: str | None = None
    taskVersionId: str | None = None
    taskVersionNumber: int | None = None
    language: str | None = None
    sourceFileName: str | None = None
    verdict: str | None = None
    tests: list[ITExecutionTestResult] = Field(default_factory=list)
    createdAt: str | None = None
    updatedAt: str | None = None
    completedAt: str | None = None


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
    "start_collection": (
        "mutation StartTaskCollection($input: StartTaskCollectionInput!) {"
        " startTaskCollection(input: $input) {"
        " id status idempotencyKey requestedBy maxItemsPerSource"
        " sources { id kind sourceId url status }"
        " }"
        "}"
    ),
    "submit_code": (
        "mutation SubmitITTaskCode($taskId: ID!, $input: ITCodeSubmissionInput!) {"
        " submitITTaskCode(taskId: $taskId, input: $input) {"
        " id status taskId taskVersionId taskVersionNumber language sourceFileName"
        " verdict tests { testId verdict stdout stderr durationMs memoryBytes }"
        " createdAt updatedAt completedAt"
        " }"
        "}"
    ),
    "get_code_submission": (
        "query ItCodeSubmission($id: ID!) {"
        " itCodeSubmission(id: $id) {"
        " id status taskId taskVersionId taskVersionNumber language sourceFileName"
        " verdict tests { testId verdict stdout stderr durationMs memoryBytes }"
        " createdAt updatedAt completedAt"
        " }"
        "}"
    ),
    "admin_tasks": (
        "query AdminITTasks($filter: ITAdminTaskFilter, $pagination: PaginationInput) {"
        " adminITTasks(filter: $filter, pagination: $pagination) {"
        " items { id status taskType title difficulty taskVersionId versionNumber }"
        " limit offset"
        " }"
        "}"
    ),
    "admin_task": (
        "query AdminITTask($id: ID!) {"
        " adminITTask(id: $id) {"
        " id status taskType title statement difficulty"
        " taskVersionId versionNumber"
        " options { id text position isCorrect }"
        " examples { input output explanation }"
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
        """Зарегистрировать пользователя и сделать его администратором.

        Требует, чтобы вызывающий (actor) уже был админом/суперпользователем;
        для первого админа используйте `login_bootstrap_superuser()`.
        """
        with report.step("Создаём администратора {username}", username=username):
            candidate = self.register(email, password, username)
            self.set_admin_by_username(candidate, username, admin_flag=True)
            return self.login(email, password)

    def login_bootstrap_superuser(self) -> AuthContext:
        """Войти как bootstrap-суперпользователь (сеется users-сервисом при старте).

        Это единственный пользователь с правами, достаточными для admin-операций
        и для назначения роли admin другим пользователям.
        """
        return self.login(config.BOOTSTRAP_SUPERUSER_EMAIL, config.BOOTSTRAP_SUPERUSER_PASSWORD)

    # ----------------------------------- Tasks --------------------------------
    def create_task(
        self,
        admin: AuthContext,
        title: str,
        statement: str,
        options: list[tuple[str, bool]],
        task_type: str = "single_choice",
        difficulty: str = "easy",
        tags: list[str] | None = None,
        examples: list[dict] | None = None,
        constraints: list[str] | None = None,
    ) -> Task:
        task_input: dict[str, Any] = {
            "title": title,
            "statement": statement,
            "taskType": task_type,
            "difficulty": difficulty,
            "options": [{"text": text, "isCorrect": is_correct} for text, is_correct in options],
        }
        if tags is not None:
            task_input["tags"] = tags
        if examples is not None:
            task_input["examples"] = examples
        if constraints is not None:
            task_input["constraints"] = constraints
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

    # --------------------------- Collection (сбор задач) ----------------------
    def start_task_collection(
        self,
        admin: AuthContext,
        website_urls: list[str],
        idempotency_key: str | None = None,
    ) -> dict:
        """Запустить асинхронный сбор задач по прямым HTTPS-ссылкам (task-hunter).

        Возвращает созданную джобу (dict): {id, status, idempotencyKey, sources, ...}.
        """
        with report.step("Запускаем сбор задач по ссылкам {n}", n=len(website_urls)):
            data = self.gql.execute(
                "start_collection",
                _Q["start_collection"],
                {
                    "input": {
                        "idempotencyKey": idempotency_key or generate.uuid4(),
                        "websiteUrls": website_urls,
                    }
                },
                token=admin.token,
            )
        return data["startTaskCollection"]

    # --------------------------- Кодовые решения ------------------------------
    def submit_code(
        self,
        user: AuthContext,
        task: Task,
        source: str | bytes,
        filename: str = "solution.py",
        language: str = "python",
        idempotency_key: str | None = None,
    ) -> ITCodeSubmission:
        """Отправить файл решения-кода по задаче (уходит по Кафке в sandbox).

        Возвращает немедленно созданную посылку (status="queued", verdict=None).
        """
        source_bytes = source.encode("utf-8") if isinstance(source, str) else source
        variables: dict[str, Any] = {
            "taskId": task.id,
            "input": {
                "taskVersionId": task.taskVersionId,
                "idempotencyKey": idempotency_key or generate.uuid4(),
                "language": language,
                "file": None,
            },
        }
        file_map = {"0": ["variables.input.file"]}
        files = {"0": (filename, source_bytes, "text/x-python")}
        with report.step("Отправляем решение-код по задаче {task_id}", task_id=task.id):
            data = self.gql.execute_upload(
                "submit_code",
                _Q["submit_code"],
                variables,
                file_map,
                files,
                token=user.token,
            )
        return ITCodeSubmission.model_validate(data["submitITTaskCode"])

    def get_code_submission(self, user: AuthContext, submission_id: str) -> ITCodeSubmission:
        with report.step("Получаем статус кодовой посылки {submission_id}", submission_id=submission_id):
            data = self.gql.execute(
                "get_code_submission",
                _Q["get_code_submission"],
                {"id": submission_id},
                token=user.token,
            )
        return ITCodeSubmission.model_validate(data["itCodeSubmission"])

    def admin_it_tasks(self, admin: AuthContext, task_type: str | None = None) -> list[dict]:
        """Полные IT-задачи (включая собранные task-hunter'ом): id, варианты, примеры.

        Список отдаёт только сводки (`ITTaskSummary`), поэтому для каждой задачи
        докантожу полный объект через `adminITTask`, чтобы вернуть примеры.
        """
        task_filter = {"taskType": task_type} if task_type else {}
        with report.step("Получаем список задач (filter={task_type})", task_type=task_type or "—"):
            data = self.gql.execute(
                "admin_tasks",
                _Q["admin_tasks"],
                {"filter": task_filter, "pagination": {"limit": 100, "offset": 0}},
                token=admin.token,
            )
        summaries = data.get("adminITTasks", {}).get("items", [])
        full_tasks = []
        for summary in summaries:
            full = self.gql.execute(
                "admin_task",
                _Q["admin_task"],
                {"id": summary["id"]},
                token=admin.token,
            ).get("adminITTask", {})
            full_tasks.append(full)
        return full_tasks

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
