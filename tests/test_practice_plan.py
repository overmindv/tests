"""Real gateway → entities/tasks/recommendations plan and submission feedback."""
import allure
import pytest

from src import asserts, generate, report

pytestmark = [pytest.mark.e2e, pytest.mark.tasks, pytest.mark.progress]


@allure.title("Практика по теме: объяснение подборки меняется после неверного и верного ответа")
def test_practice_plan_recomputes_from_real_student_answers(api, admin, regular_user):
    """Автор связывает две задачи с новой темой; план учитывает реальные попытки студента."""
    tasks = []
    with report.step("Автор создаёт активную тему и две опубликованные задачи этой темы"):
        topic = api.create_topic(admin, f"Практика e2e {generate.uuid4()}")
    try:
        for title in ("Сложение", "Умножение"):
            task = api.create_task(admin, title=title, statement="Выберите 4", options=[("4", True), ("5", False)],
                                   topic_id=topic["id"])
            tasks.append(task)
            api.change_task_status(admin, task.id, "published")

        with report.step("Студент выбирает тему и получает реальные задачи с объяснением START_TOPIC"):
            plan = api.practice_plan(regular_user, [topic["id"]])
            asserts.is_not_empty(plan["policyVersion"], "План содержит версию политики recommendations")
            asserts.equal({item["taskId"] for item in plan["items"]}, {task.id for task in tasks},
                          "В плане обе задачи выбранной темы")
            asserts.equal({item["topicId"] for item in plan["items"]}, {topic["id"]}, "В плане только выбранная тема")
            asserts.equal({item["reasonCode"] for item in plan["items"]}, {"START_TOPIC"}, "Объяснение начала темы")
            asserts.equal(plan["totalMinutes"], 20, "Две начальные задачи укладываются в бюджет")

        first = tasks[0]
        wrong = next(option for option in first.options if not option.isCorrect)
        right = next(option for option in first.options if option.isCorrect)
        with report.step("После неверного ответа пересчёт объясняет потребность в практике"):
            result = api.submit_answer(regular_user, first.id, first.taskVersionId, [wrong.id])
            asserts.equal(result.verdict, "wrong_answer", "Неверный ответ сохранён")
            plan = api.practice_plan(regular_user, [topic["id"]])
            asserts.equal(plan["items"][0]["taskId"], first.id, "Задача с ошибкой идёт первой")
            asserts.equal(plan["items"][0]["reasonCode"], "PRACTICE_GAP", "Подборка учитывает сохранённую ошибку")

        with report.step("После верного ответа решённая задача исключается, следующая объяснена"):
            result = api.submit_answer(regular_user, first.id, first.taskVersionId, [right.id])
            asserts.equal(result.verdict, "accepted", "Верный ответ сохранён")
            plan = api.practice_plan(regular_user, [topic["id"]])
            asserts.equal([item["taskId"] for item in plan["items"]], [tasks[1].id], "Осталась только нерешённая задача")
            asserts.equal(plan["items"][0]["reasonCode"], "NEXT_CHALLENGE", "Подборка объясняет следующий шаг")
    finally:
        with report.step("Очистка только задач и темы текущего сценария"):
            for task in tasks:
                api.delete_task(admin, task.id)
            api.delete_topic(admin, topic["id"])
