# AGENTS.md

Руководство для ИИ-агента и для разработчика-тестировщика.

## Назначение репозитория

**overmindv/tests** — интеграционные (e2e) тесты системы overmindv. Тесты проверяют
полный путь работоспособности через **api-gateway** (GraphQL `http://localhost:8081/graphql`):
регистрация/вход пользователей, создание и модерация задач, решение с верным/неверным
ответом, история (прогресс) пользователя.

## Принцип

Тест-разработчик пишет **только сценарии**: объявляет фикстуры и описывает шаги через
`report.step(...)` + `asserts.*`. Вся инфраструктура (HTTP-клиент с авто-шагами, конфиг,
подъём стека, отчёты Allure, CI) — готовая и не переписывается в тестах.

## Быстрый старт

```bash
# 1. Поднять стек (docker-compose из репозитория ../infra; только api-gateway:8081 наружу)
make up

# 2. Установить Python-зависимости (один раз)
make setup

# 3. Прогнать тесты
make test

# Отчёты Allure
make allure
```

Отдельные таргеты: `make down` (остановить стек), `make clean` (остановить и удалить БД),
`make lint` / `make lint-check`, `make ci` (полный прогон как в CI).

Переменные окружения — в `.env` (см. `.env.example`): `BASE_URL`, `GRAPHQL_PATH`, таймауты,
`GENERATE_UNIQUE_DATA`. `.env` не коммитится.

## Структура репозитория

```
├── pyproject.toml / requirements.txt   # зависимости и настройки pytest/ruff
├── conftest.py                         # глобальные allure-хуки (не трогать в тестах)
├── Makefile                            # up/down/test/allure/ci (стек делегируется в ../infra)
├── .github/workflows/e2e.yml           # переиспользуемый e2e-CI (вызывается из сервисов)
├── src/                                # ЯДРО (пишется/меняется редко)
│   ├── configuration.py                # Config из env
│   ├── helper/env.py                   # get / get_bool / get_int
│   ├── report.py                       # report.step(...), attach_*
│   ├── check.py                        # ok_response / gql_success_response
│   ├── asserts.py                      # equal / not_equal / wait / ...
│   ├── http_error.py  mark.py  generate.py
│   └── api/
│       ├── http_client.py              # REST-клиент
│       ├── graphql_client.py           # POST /graphql + envelope
│       └── gateway.py                  # фасад: register/login/setAdmin/create_task/...
└── tests/                              # СЮДА пишет тест-разработчик
    ├── conftest.py                     # фикстуры: api, admin, regular_user
    ├── test_auth.py
    └── test_task_flow.py               # эталонный сценарий
```

## Как написать тест: эталон `tests/test_task_flow.py`

```python
import allure, pytest
from src import asserts, report

pytestmark = pytest.mark.e2e and pytest.mark.tasks   # маркировка

@allure.title("Задача: создание, публикация, решение, история")
def test_task_solve_wrong_then_right(api, admin, regular_user):
    """Задача -> решение с неверным/верным ответом -> прогресс пользователя."""
    with report.step("1. Администратор создаёт задачу"):
        task = api.create_task(admin, title="2+2?", statement="Выберите вариант",
                               options=[("4", True), ("5", False)])
        correct = next(o for o in task.options if o.isCorrect)
        wrong = next(o for o in task.options if not o.isCorrect)

    with report.step("2. Публикуем задачу"):
        published = api.change_task_status(admin, task.id, "published")
        asserts.equal(published["status"], "published", "Задача должна стать published")

    with report.step("3. Неверный ответ"):
        r = api.submit_answer(regular_user, task.id, task.taskVersionId, [wrong.id])
        asserts.equal(r.verdict, "wrong_answer", "Неверный ответ -> wrong_answer")

    with report.step("4. Прогресс содержит оба решения"):
        asserts.equal(len(api.my_submissions(regular_user, task.id)), 2, "2 решения в истории")
```

Правила:
1. Докстринга функции автоматически попадает в отчёт Allure как описание.
2. Каждый смысловой шаг — `with report.step("..."):`.
3. Проверки — `asserts.*` (каждый assert = шаг-проверка в отчёте). Голой `assert` избегайте.
4. Данные генерируются уникальными (`generate.unique_email()`), фикстуры сами очищают
   пользователей в teardown — никаких общих данных между тестами.
5. Маркеры регистрируются в `pyproject.toml`: `e2e`, `auth`, `tasks`, `progress`, `skip_ci`.
6. `pytest.ini`-настройки и маркеры — в `[tool.pytest.ini_options]` (pyproject.toml).
7. Называть тесты и файлы надо осмысленно, чтобы можно было понять, что они проверяют, а не абстрактно.

## Запуск в CI (кросс-репозиторно)

`tests/.github/workflows/e2e.yml` — **переиспользуемый** воркфлоу. Он запускается
**при пуше/PR в любой сервис** (users, tasks, api-gateway): их CI вызывает его через
`uses: overmindv/tests/.github/workflows/e2e.yml@main` с `target_repo: <имя>`.

Что делает воркфлоу:
1. Чекаутит весь воркспейс: `tests`, `infra` и все сервисы (users/tasks/api-gateway/
   entities/task-hunter/frontend) так, чтобы docker-compose из `infra` нашёл их в
   соседних каталогах (`../users`, ...).
2. **Изменённый сервис** чекаутится по коммиту пуша (`github.sha`), остальные — со своей `main`.
3. Поднимает стек (`docker compose up --build -d --wait`), прогоняет
   `pytest -m "e2e and not skip_ci" -n 2`, выкладывает `allure-results` артефактом и гасит стек.

Чтобы подключить новый сервис к e2e, добавьте в его `.github/workflows/*.yml`:

```yaml
  e2e:
    permissions:
      contents: read
    uses: overmindv/tests/.github/workflows/e2e.yml@main
    with:
      target_repo: <имя-репозитория>
```

Полезно: `workflow_dispatch` (Actions → Run workflow) даёт ручной полный прогон,
например, после правки самих тестов. Локально эквивалент — `make ci`.

## Примечания

- Стек (compose, конфиги сервисов) живёт в `../infra` — здесь он не дублируется.
- Если изменился API-шлюз/схема GraphQL — обновите `src/api/gateway.py` (строки `_Q`
  и методы) и добавьте сценарии в `tests/`.
- Полезные первоисточники для эндпоинтов: `api-gateway/api/graphql/schema.graphqls`,
  `infra/docker-compose.yml` (порты), `api-gateway/tests/integration/*_test.go` (примеры).
