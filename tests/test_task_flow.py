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

pytestmark = pytest.mark.e2e and pytest.mark.tasks


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
