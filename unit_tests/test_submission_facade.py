from __future__ import annotations

import json

import pytest
from requests import Response

from src import report
from src.api.gateway import AuthContext, Gateway, Task
from src.api.graphql_client import GraphQLClient
from src.http_error import HttpError

SOURCE = "print('fixture for submission')"
TASK = Task(
    id="task",
    status="published",
    taskVersionId="version",
    versionNumber=2,
    title="Fixture",
    taskType="programming",
    difficulty="easy",
)
ACTOR = AuthContext(token="fixture-code-session", user_id="student", email="student@example.test", username="student")


@pytest.fixture
def gateway_stub(monkeypatch):
    client = GraphQLClient(base_url="http://gateway.test")
    calls = []
    responses = []
    attachments = []

    def post(url, *, headers, timeout, json=None, files=None):
        payload = json if files is None else _multipart_operations(files)
        calls.append((payload, files, headers))
        body = responses.pop(0)
        response = Response()
        response.status_code = 200
        response._content = _encode(body)
        return response

    monkeypatch.setattr(client.session, "post", post)
    monkeypatch.setattr(report, "attach_json", lambda name, value: attachments.append((name, value)))
    return Gateway(client), calls, responses, attachments


def _multipart_operations(files):
    return json.loads(files["operations"][1])


def _encode(value):
    return json.dumps(value).encode()


def test_legacy_file_submission_omits_mode_from_query_and_variables(gateway_stub):
    api, calls, responses, attachments = gateway_stub
    responses.append({"data": {"submitITTaskCode": {"id": "code", "status": "queued"}}})
    result = api.submit_code(ACTOR, TASK, SOURCE, idempotency_key="retry")
    payload, files, headers = calls[0]
    assert result.runMode is None
    assert "runMode" not in payload["query"]
    assert payload["variables"]["input"] == {
        "taskVersionId": "version",
        "idempotencyKey": "retry",
        "language": "python",
        "file": None,
    }
    assert json.loads(files["map"][1]) == {"0": ["variables.input.file"]}
    assert files["0"] == ("solution.py", SOURCE.encode(), "text/x-python")
    assert headers["Authorization"] == f"Bearer {ACTOR.token}"
    assert attachments == []


@pytest.mark.parametrize("mode", ["samples", "graded"])
def test_inline_modes_put_source_in_variables_without_reporting_it(gateway_stub, mode):
    api, calls, responses, attachments = gateway_stub
    responses.append({"data": {"submitITTaskCode": {"id": "code", "status": "queued", "runMode": mode}}})
    result = api.submit_source(ACTOR, TASK, SOURCE, run_mode=mode, idempotency_key="retry")
    payload, files, _ = calls[0]
    assert result.runMode == mode
    assert files is None
    assert SOURCE not in payload["query"]
    assert payload["variables"]["input"] == {
        "taskVersionId": "version",
        "idempotencyKey": "retry",
        "language": "python",
        "sourceCode": SOURCE,
        "runMode": mode,
    }
    assert attachments == []


def test_graded_file_and_status_can_select_mode_without_trimming_results(gateway_stub):
    api, calls, responses, attachments = gateway_stub
    responses.extend(
        [
            {"data": {"submitITTaskCode": {"id": "code", "status": "queued", "runMode": "graded", "language": "go"}}},
            {
                "data": {
                    "itCodeSubmission": {
                        "id": "code",
                        "status": "completed",
                        "runMode": "graded",
                        "tests": [{"testId": "projection-canary", "verdict": "accepted"}],
                    }
                }
            },
            {"data": {"itCodeSubmission": {"id": "legacy", "status": "completed"}}},
        ]
    )
    result = api.submit_code(
        ACTOR,
        TASK,
        b"package main\n",
        filename="main.go",
        language="go",
        run_mode="graded",
    )
    assert result.runMode == "graded"
    payload, files, _ = calls[0]
    assert payload["variables"]["input"]["runMode"] == "graded"
    assert files["0"] == ("main.go", b"package main\n", "text/plain")
    observed = api.get_code_submission(ACTOR, result.id, include_run_mode=True)
    assert observed.runMode == "graded"
    assert observed.tests[0].testId == "projection-canary"
    assert "runMode" in calls[1][0]["query"]
    assert api.get_code_submission(ACTOR, "legacy").runMode is None
    assert "runMode" not in calls[2][0]["query"]
    assert attachments == []


def test_submission_failure_reports_code_but_not_reflected_source(gateway_stub):
    api, _, responses, attachments = gateway_stub
    responses.append({"errors": [{"message": SOURCE, "extensions": {"code": "INVALID_ARGUMENT"}}]})
    with pytest.raises(HttpError, match="INVALID_ARGUMENT") as raised:
        api.submit_code(ACTOR, TASK, SOURCE, run_mode="samples")
    assert SOURCE not in str(raised.value)
    assert attachments == []
