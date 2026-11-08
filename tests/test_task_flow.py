"""Эталонный e2e-сценарий: полный путь «задача -> решение -> прогресс».

Сценарий:
    1. Администратор создаёт задачу и публикует её.
    2. Пользователь решает задачу с неверным ответом.
    3. Пользователь решает задачу с верным ответом.
    4. История решений пользователя содержит оба результата.

Это пример того, как тест-разработчик пишет сценарий: объявляет
фикстуры (api, admin, regular_user) и описывает шаги через
`report.step` + `asserts.*`. Никакой HTTP-инфраструктуры здесь нет.
"""
import allure
import pytest

from src import asserts, report

pytestmark = [pytest.mark.e2e, pytest.mark.tasks]


@allure.title("Задача: создание, публикация, решение с верным и неверным ответом, история")
def test_task_solve_wrong_then_right(api, admin, regular_user):
    """Полный путь работоспособности: задача -> решение -> прогресс пользователя."""
    with report.step("1. Администратор создаёт задачу с двумя вариантами ответа"):
        task = api.create_task(
            admin,
            title="Чему равно 2 + 2?",
            statement="Выберите единственный верный вариант.",
            options=[("4", True), ("5", False)],
            task_type="single_choice",
            difficulty="easy",
        )
        correct_option = next(o for o in task.options if o.isCorrect)
        wrong_option = next(o for o in task.options if not o.isCorrect)
        asserts.equal(task.status, "draft", "Новая задача создаётся в статусе draft")

    with report.step("2. Администратор публикует задачу"):
        published = api.change_task_status(admin, task.id, "published")
        asserts.equal(published["status"], "published", "Задача должна стать published")

    with report.step("3. Пользователь отправляет неверный ответ"):
        wrong = api.submit_answer(regular_user, task.id, task.taskVersionId, [wrong_option.id])
        asserts.equal(wrong.verdict, "wrong_answer", "Неверный ответ -> verdict wrong_answer")
        asserts.is_false(wrong.correct, "correct=false для неверного ответа")

    with report.step("4. Пользователь отправляет верный ответ"):
        right = api.submit_answer(regular_user, task.id, task.taskVersionId, [correct_option.id])
        asserts.equal(right.verdict, "accepted", "Верный ответ -> verdict accepted")
        asserts.is_true(right.correct, "correct=true для верного ответа")

    with report.step("5. Прогресс пользователя содержит оба решения"):
        history = api.my_submissions(regular_user, task.id)
        asserts.equal(len(history), 2, "В истории пользователя должно быть 2 решения")
        verdicts = {s["verdict"] for s in history}
        asserts.equal(verdicts, {"accepted", "wrong_answer"}, "В истории оба исхода")

    with report.step("6. Данные изолированы: у каждого решения свой результат"):
        for submission in history:
            assert submission["verdict"] in {"accepted", "wrong_answer"}


@allure.title("Сбор по ссылке -> принятие -> решение кодом через sandbox (Кафка)")
def test_task_collect_publish_solve_by_code_via_sandbox(api, admin, regular_user):
    """Полный цикл платформы: сбор по ссылке, принятие задачи, решение Python-файлом.

    Шаги:
    1. Администратор запускает сбор задач по ссылке (создаётся джоба сбора).
    2. Задача принимается и публикуется (в детерминированном ядре - напрямую,
       аналог approveTaskCandidate из собранного кандидата).
    3. Пользователь отправляет файл решения на Python (print(input())).
    4. Файл уходит по Кафке в sandbox: посылка имеет status=queued без вердикта.
    5. Результат возвращается в tasks, сверяется с ответами - для задачи-«эхо»
       вердикт = accepted.
    """
    with report.step("1. Сбор задачи по ссылке (аннотированно, внешний источник)"):
        # Приход реального кандидата из Codeforces/LeetCode/CodeRun недетерминирован
        # и зависит от внешней сети, поэтому здесь проверяем детерминированное
        # создание джобы сбора, не блокируясь на приход кандидата.
        job = api.start_task_collection(
            admin,
            website_urls=["https://codeforces.com/problemset/problem/4/A"],
        )
        asserts.equal(job["status"], "queued", "Джоба сбора создаётся в статусе queued")
        asserts.is_not_empty(job["id"], "Джобе присвоен id")
        asserts.is_not_empty(job["idempotencyKey"], "У джобы есть idempotencyKey")

    with report.step("2. Принятие задачи: создание и публикация программной задачи"):
        # В проде задача приходит из approveTaskCandidate (собранный кандидат).
        # В детерминированном ядре создаём программную задачу напрямую и публикуем её.
        task = api.create_task(
            admin,
            title="Эхо",
            statement="Выведите входную строку без изменений.",
            options=[],
            task_type="programming",
            difficulty="easy",
            tags=["stdin", "echo"],
            constraints=["1 <= длина строки <= 100"],
            examples=[{"input": "hello", "output": "hello", "explanation": "эхо"}],
        )
        asserts.equal(task.status, "draft", "Новая задача создаётся в статусе draft")
        published = api.change_task_status(admin, task.id, "published")
        asserts.equal(published["status"], "published", "Задача опубликована")

    with report.step("3. Пользователь отправляет решение-код (Python-файл)"):
        sub = api.submit_code(regular_user, task, 'print(input())', filename="solve.py")
        asserts.equal(sub.status, "queued", "Посылка сразу имеет status=queued (файл в пути по Кафке)")
        asserts.equal(sub.verdict, None, "Вердикт ещё не вынесен, пока решение исполняется")

    with report.step("4. Ожидаем возврата результата из sandbox (Кафка -> tasks)"):
        submission_id = sub.id
        code = asserts.wait(
            lambda: _completed_or_none(api, regular_user, submission_id),
            timeout=120.0,
            interval=2.0,
            message="Кодовая посылка должна завершиться (status=completed)",
        )
        asserts.equal(code.status, "completed", "Посылка завершилась: результат вернулся в tasks")

    with report.step("5. Сверка с ответами и итог"):
        asserts.equal(code.verdict, "accepted", "Корректное решение-«эхо» -> verdict accepted")
        asserts.is_not_empty(code.tests, "Есть исполненные тесты по посылке")


def _completed_or_none(api, user, submission_id):
    """Вернуть кодовую посылку, когда она завершилась, иначе None (для asserts.wait)."""
    submission = api.get_code_submission(user, submission_id)
    return submission if submission.status == "completed" else None


@allure.title("Реальное исполнение Python: корректный DP принят, неверный код отклонён")
def test_programming_solution_is_executed_and_wrong_code_rejected(api, admin, regular_user):
    """Изолированный программный сценарий без заранее загруженных задач и внешней сети.

    Автор создаёт и публикует задачу; настоящий gojudge исполняет два Python-файла.
    Примеры — публичный контракт задачи. Верный DP принят, print(0) отклонён.
    Сбор по ссылке проверяется отдельным сценарием только до создания джобы;
    этот тест не заявляет coverage внешнего парсинга или модерации кандидатов.
    """
    with report.step("1. Автор создаёт программную задачу с публичными примерами"):
        task = api.create_task(
            admin, title="Число путей коня", task_type="programming", difficulty="easy", options=[],
            statement="На доске n × m конь идёт из (0, 0) в (n-1, m-1), только на (2, 1) или (1, 2). Выведите число путей.",
            examples=[{"input": "3 2", "output": "1", "explanation": "Один ход"},
                      {"input": "4 4", "output": "2", "explanation": "Два порядка ходов"},
                      {"input": "1 1", "output": "1", "explanation": "Начальная клетка"}],
        )
        api.change_task_status(admin, task.id, "published")

    with report.step("2. Студент отправляет корректный Python DP"):
        solution = (
            "n, m = map(int, input().split())\n"
            "dp = [[0] * m for _ in range(n)]\n"
            "dp[0][0] = 1\n"
            "for i in range(n):\n"
            "    for j in range(m):\n"
            "        if i + 2 < n and j + 1 < m: dp[i + 2][j + 1] += dp[i][j]\n"
            "        if i + 1 < n and j + 2 < m: dp[i + 1][j + 2] += dp[i][j]\n"
            "print(dp[n - 1][m - 1])\n"
        )
        submitted = api.submit_code(regular_user, task, solution, filename="solve.py")
        correct = asserts.wait(
            lambda: _completed_or_none(api, regular_user, submitted.id), timeout=120, interval=2,
            message="Корректный код должен завершиться через Kafka и gojudge",
        )
        asserts.equal(correct.verdict, "accepted", "Реальный исполнитель принимает верный DP")
        asserts.equal(len(correct.tests), 3, "Исполнены все три публичных примера")

    with report.step("3. Студент отправляет неверный код и получает wrong_answer"):
        submitted = api.submit_code(regular_user, task, "print(0)\n", filename="wrong.py")
        wrong = asserts.wait(
            lambda: _completed_or_none(api, regular_user, submitted.id), timeout=120, interval=2,
            message="Неверный код должен завершиться через Kafka и gojudge",
        )
        asserts.equal(wrong.verdict, "wrong_answer", "Неверный результат не принимается")
        asserts.is_not_empty(wrong.tests, "Возвращены результаты выполнения публичных примеров")
