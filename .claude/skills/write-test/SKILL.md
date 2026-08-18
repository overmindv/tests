---
name: write-test
description: Используй, когда разработчик-тестировщик описывает словами сценарий (или даёт Jira-ссылку/ключ, или просит «напиши тест на …», «добавь e2e-покрытие для …»). Превращает словесное описание сценария в готовый pytest-код e2e-теста на базе фасада api-gateway (src/api/gateway.py), фикстур (api/admin/regular_user) и ядра (report.step, asserts.*, generate). Скилл для репозитория overmindv/tests.
disable-model-invocation: false
---

# Написание E2E-тестов в overmindv/tests

Репо: **overmindv/tests**. Тесты ходят через **api-gateway** (GraphQL `http://localhost:8081/graphql`).
Разработчик пишет сценарий словами — ты пишешь pytest-тест по нему, не трогая инфраструктуру.

## Когда использовать

- Пользователь **словами или Jira-описанием** описывает сценарий теста и просит написать код.
- Просьба вида «напиши e2e под …», «добавь тест на …», «проверь, что …», «напиши тест …», «сделай тест …».
- Добавление проверок/расширение существующих e2e-тестов.

## Полный workflow

### 1. Понять сценарий

Если дана Jira-ссылка (jit.o3.ru/.../`XXX-123`) — при желании подтяни контекст через Jira MCP
и зафиксируй суть сценария. Если сценарий описан словами — разбей его на **шаги** и
**ожидаемые проверки**. Уточни у пользователя, что неоднозначно (роли, статусы, данные).

### 2. Сопоставить шаги с фикстурами и методами фасада

Всё, что нужно сделать в тесте, доступно через фикстуры и `api` (объект `Gateway`):

| Нужно | Чем пользоваться |
|---|---|
| Посторонний пользователь | фикстура `regular_user` (ctx: `.token`, `.user_id`, `.email`, `.username`, `.password`) |
| Администратор | фикстура `admin` (register → setAdmin → login) |
| Создать задачу (admin) | `api.create_task(admin, title=..., statement=..., options=[("текст", is_correct), ...], task_type=..., difficulty=...)` → `Task` |
| Опубликовать/архивировать | `api.change_task_status(admin, task.id, "published")` → `{"id","status"}` |
| Отправить решение | `api.submit_answer(regular_user, task.id, task.taskVersionId, [option_id], idempotency_key=None)` → `Submission` |
| История решений (прогресс) | `api.my_submissions(regular_user, task_id)` → `list[dict]` |
| Сгенерировать данные | `generate.unique_email()`, `generate.uuid4()` |
| Прямые GraphQL/REST | `api.gql.execute(operation, query, variables, token=...)` (редко нужно) |

Ключевые поля моделей:

- `Task`: `.id`, `.status` (`draft`/`published`/`archived`), `.taskVersionId`, `.versionNumber`,
  `.options` (list of `{id, text, position, isCorrect}`).
- `Submission`: `.verdict` (`accepted`/`wrong_answer`), `.correct` (bool), `.correctOptionIds`,
  `.taskUpdated`, `.latestTaskVersionId`.
- `AuthContext`: `.token`, `.user_id`, `.email`, `.username`, `.password`, `.is_admin`.

### 3. Написать тест по шаблону

Файл: `tests/<feature>/test_<feature>.py` (или `tests/test_<feature>.py` для простого кейса).

```python
"""Описание тестируемого функционала на русском (попадает в Allure как описание)."""

import allure
import pytest

from src import asserts, generate, report

pytestmark = pytest.mark.e2e and pytest.mark.tasks  # маркер под тему: auth/tasks/progress/...


@allure.title("Краткий заголовок кейса")
def test_<action_when_then>(api, admin, regular_user):
    """Сценарий на русском.

    Шаги:
    1. ...
    2. ...
    3. ...
    """
    with report.step("1. Предусловие / действие"):
        # подготовка и действие
        task = api.create_task(
            admin,
            title="Чему равно 2+2?",
            statement="Выберите ответ.",
            options=[("4", True), ("5", False)],
        )

    with report.step("2. Действие"):
        result = api.submit_answer(regular_user, task.id, task.taskVersionId, [сorrect_option_id])
        asserts.equal(result.verdict, "accepted", "Верный ответ -> accepted")
```

Проверки — только через `asserts.*` (каждый assert = шаг Allure): `equal`, `not_equal`,
`is_true`, `is_false`, `is_empty`, `is_not_empty`, `is_in`, `is_not_in`, `greater_than`,
`contains`, `wait(condition, timeout, interval, message)`.

### 4. Проверить и запустить

```bash
make setup    # один раз (venv + зависимости)
make up       # поднять стек (если не поднят)
make test     # прогнать все e2e
```

Точечно: `pytest tests/test_task_flow.py -k "<имя>"`.

## Правила

- **Все docstrings и сообщения об ошибках — на русском.**
- **Докстринга теста = описание сценария** (автоматически попадает в Allure). Обновляй её при изменении шагов.
- **Каждый смысловой шаг — `with report.step("..."):`.**
- **Проверки — только `asserts.*`**, не голый `assert` (голый `assert` ломает шаговый отчёт).
- **Данные уникальные**: `generate.unique_email()`/`generate.uuid4()` — никаких общих/фиксированных данных между тестами (фикстуры сами чистят пользователей в teardown).
- **Именование** — осмысленное: `test_user_can_solve_task_wrong_then_right`, файл `test_task_flow.py`; маркеры строго из списка (`e2e`, `auth`, `tasks`, `progress`, `skip_ci`).
- **Никаких `time.sleep()`** — для ожиданий используй `asserts.wait(...)`.
- Если нужен новый метод фасада — добавляй в `src/api/gateway.py` (строки `_Q` + метод), не дублируй GraphQL в тесте.
- Если сценарию нужна **модерация кандидата** (одобрение из task-hunter) — см. `approveTaskCandidate` в схеме api-gateway (`api-gateway/api/graphql/schema.graphqls`); метод фасада добавь при необходимости.

## Референс

Готовый пример паттерна — `tests/test_task_flow.py` и `tests/test_auth.py`.
Источник эндпоинтов: `api-gateway/api/graphql/schema.graphqls`, `infra/docker-compose.yml` (порты).
