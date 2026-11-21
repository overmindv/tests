from __future__ import annotations

import os

import pytest

from src import asserts, generate, report
from src.api.gateway import ITCodeSubmission
from src.api.suite_fixture import PUBLIC_INPUT, publish_echo_suite
from src.http_error import HttpError

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.tasks,
    pytest.mark.skipif(os.environ.get("GRADED_E2E") != "1", reason="Requires the dedicated graded Compose stack"),
]

PROGRAMS = {
    "python": {
        "filename": "main.py",
        "echo": "import sys\nsys.stdout.write(sys.stdin.read())\n",
        "sample": "print('sample-line')\n",
        "overflow": "print('x' * 4096)\n",
        "wait": "import time\ntime.sleep(3)\n",
    },
    "go": {
        "filename": "main.go",
        "echo": 'package main\nimport ("io"; "os")\nfunc main() { io.Copy(os.Stdout, os.Stdin) }\n',
        "sample": 'package main\nimport "fmt"\nfunc main() { fmt.Println("sample-line") }\n',
        "overflow": 'package main\nimport ("fmt"; "strings")\nfunc main() { fmt.Println(strings.Repeat("x", 4096)) }\n',
        "wait": 'package main\nimport "time"\nfunc main() { time.Sleep(3*time.Second) }\n',
    },
}


def _completed(api, actor, submission_id):
    current = api.get_code_submission(actor, submission_id, include_run_mode=True)
    return current if current.status == "completed" else None


def _wait(api, actor, submitted):
    return asserts.wait(
        lambda: _completed(api, actor, submitted.id),
        timeout=120,
        interval=2,
        message="Посылка завершилась в настоящем Sandbox",
    )


def _check_private(submission: ITCodeSubmission, hidden: str) -> None:
    asserts.equal(submission.runMode, "graded", "Результат относится к закрытой проверке")
    asserts.equal(len(submission.tests), 0, "API не показывает отдельные кейсы закрытой проверки")
    dump = submission.model_dump_json()
    asserts.is_false(hidden in dump or "suite-private" in dump, "Ответ не содержит скрытый ввод или его ID")
    for phase in (submission.compilation, submission.execution):
        if phase is not None:
            asserts.equal(bool(phase.stdout or phase.stderr), False, "Подробный вывод фазы не опубликован")


@pytest.mark.parametrize("language", ["python", "go"])
def test_samples_and_graded_on_the_real_judge(api, admin, regular_user, scenario_data, language):
    program = PROGRAMS[language]
    hidden = f"private-{generate.uuid4()}"
    with report.step("Публикуем версию задачи с открытым и закрытым кейсами"):
        task = scenario_data.task(
            admin,
            title=f"Echo {language}",
            statement="Повторите входную строку.",
            task_type="programming",
            options=[],
            examples=[{"input": PUBLIC_INPUT, "output": PUBLIC_INPUT}],
        )
        version_id = publish_echo_suite(admin, task, language, hidden + "\n")
        publication = api.change_task_status(admin, task.id, "published")
        asserts.equal(publication["status"], "published", "Задача опубликована")
        current = api.admin_it_task(admin, task.id)
        asserts.equal(current.taskVersionId, version_id, "Задача ссылается на опубликованный набор")
    with report.step("Проверяем открытый пример"):
        sample = _wait(
            api,
            regular_user,
            api.submit_source(
                regular_user,
                current,
                program["echo"],
                language=language,
                run_mode="samples",
            ),
        )
        asserts.equal(sample.verdict, "accepted", "Открытый пример проходит")
        asserts.equal(
            [test.stdout.rstrip("\n") for test in sample.tests],
            [PUBLIC_INPUT.rstrip("\n")],
            "Видно только вывод открытого примера",
        )
    with report.step("Отправляем файл на закрытую проверку и повторяем тот же запрос"):
        key = generate.uuid4()
        first = api.submit_code(
            regular_user,
            current,
            program["echo"],
            program["filename"],
            language,
            key,
            run_mode="graded",
        )
        duplicate = api.submit_code(
            regular_user,
            current,
            program["echo"],
            program["filename"],
            language,
            key,
            run_mode="graded",
        )
        asserts.equal(duplicate.id, first.id, "Повтор с тем же ключом возвращает исходную посылку")
        asserts.equal(duplicate.executionId, first.executionId, "Повтор не создает новый запуск")
        with pytest.raises(HttpError, match="IDEMPOTENCY_KEY_CONFLICT"):
            api.submit_code(
                regular_user,
                current,
                program["sample"],
                program["filename"],
                language,
                key,
                run_mode="graded",
            )
        accepted = _wait(api, regular_user, first)
        asserts.equal(accepted.verdict, "accepted", "Решение проходит оба кейса")
        _check_private(accepted, hidden)
    results = [accepted]
    for source, verdict, step in (
        (program["sample"], "wrong_answer", "Решение, верное только на открытом примере, не проходит"),
        (program["overflow"], "output_limit_exceeded", "Проверка ограничивает размер вывода"),
        (program["wait"], "time_limit_exceeded", "Проверка ограничивает время запуска"),
    ):
        with report.step(step):
            submitted = api.submit_source(regular_user, current, source, language=language, run_mode="graded")
            result = _wait(api, regular_user, submitted)
            asserts.equal(result.verdict, verdict, "Вердикт реального Sandbox")
            _check_private(result, hidden)
            results.append(result)
    with report.step("Проверяем историю без закрытых данных"):
        page = api.my_code_submissions(regular_user, task.id)
        asserts.equal(
            {item.id for item in page.items}, {sample.id, *(item.id for item in results)}, "История без дублей"
        )
        for item in page.items:
            if item.id != sample.id:
                _check_private(item, hidden)
