import allure
import pytest

from src import asserts, report
from src.http_error import HttpError

pytestmark = [pytest.mark.e2e, pytest.mark.tasks, pytest.mark.progress]


@allure.title("Два студента видят только свои решения одной задачи")
def test_submission_access_is_scoped_to_student(api, admin, regular_user, scenario_data):
    with report.step("Публикуем задачу и сохраняем два ответа от разных студентов"):
        other_student = scenario_data.user()
        topic_id = scenario_data.topic(admin, "Доступ к решению")
        task = scenario_data.task(
            admin,
            title="Проверка доступа к решению",
            statement="Сколько будет 2 + 2?",
            options=[("4", True), ("5", False)],
            topic_id=topic_id,
        )
        api.change_task_status(admin, task.id, "published")
        right = next(option for option in task.options if option.isCorrect)
        wrong = next(option for option in task.options if not option.isCorrect)
        first = api.submit_answer(regular_user, task.id, task.taskVersionId, [right.id])
        second = api.submit_answer(other_student, task.id, task.taskVersionId, [wrong.id])
        asserts.not_equal(first.id, second.id, "Студенты получили разные решения")

    for student, own, foreign, verdict in (
        (regular_user, first, second, "accepted"),
        (other_student, second, first, "wrong_answer"),
    ):
        with report.step("Студент видит свой результат и свое решение в истории"):
            result = api.get_submission(student, own.id)
            asserts.equal(result.id, own.id, "Результат принадлежит студенту")
            asserts.equal(result.verdict, verdict, "Результат соответствует ответу")
            ids = [item["id"] for item in api.my_submissions(student, task.id)]
            asserts.equal(ids, [own.id], "История не содержит чужое решение")

        with report.step("Чужое решение недоступно по ID"):
            with pytest.raises(HttpError) as denied:
                api.get_submission(student, foreign.id)
            asserts.equal(
                denied.value.response,
                {"errors": [{"extensions": {"code": "PERMISSION_DENIED"}}]},
                "Gateway отклонил чтение чужого решения",
            )
