from __future__ import annotations

from unittest.mock import Mock
from uuid import UUID

import pytest

from scripts.run_graded_e2e import validate_stack
from src.api import suite_fixture
from src.api.gateway import AuthContext, Task

ADMIN = AuthContext(
    token="fixture-only",
    user_id=str(UUID(int=1)),
    email="grader@example.test",
    username="grader",
    is_superuser=True,
)
TASK = Task(
    id=str(UUID(int=2)),
    taskVersionId=str(UUID(int=3)),
    status="draft",
    versionNumber=1,
    title="Echo",
    taskType="programming",
    difficulty="easy",
)


@pytest.fixture
def model(tmp_path):
    return {
        "networks": {"default": {"internal": True}, "judge": {"internal": True}},
        "services": {
            "gojudge": {"privileged": True, "read_only": True, "networks": {"judge": {}}},
            "test": {
                "volumes": [
                    {
                        "type": "bind",
                        "target": "/evidence",
                        "source": str(tmp_path),
                        "bind": {"create_host_path": False},
                    },
                ]
            },
        },
    }


def test_stack_accepts_only_expected_local_artifact_mount(model, tmp_path):
    validate_stack(model, tmp_path)
    model["services"]["test"]["volumes"][0]["source"] = str(tmp_path.parent)
    with pytest.raises(RuntimeError, match="Unexpected mount"):
        validate_stack(model, tmp_path)


def test_stack_rejects_host_access_and_runtime_credentials(model, tmp_path):
    test = model["services"]["test"]
    test["ports"] = [{"published": "8081"}]
    with pytest.raises(RuntimeError, match="Unexpected host access"):
        validate_stack(model, tmp_path)
    del test["ports"]
    model["services"]["gojudge"]["environment"] = {"Unexpected": "<fixture>"}
    with pytest.raises(RuntimeError, match="Unsafe runtime configuration"):
        validate_stack(model, tmp_path)


def test_stack_rejects_non_isolated_network(model, tmp_path):
    model["networks"]["judge"]["internal"] = False
    with pytest.raises(RuntimeError, match="networks must be private"):
        validate_stack(model, tmp_path)


def test_suite_is_not_published_outside_grading_stack(monkeypatch):
    monkeypatch.setenv("GRADED_E2E", "1")
    monkeypatch.setattr(suite_fixture.config, "BASE_URL", "https://example.test")
    start = Mock()
    monkeypatch.setattr(suite_fixture.requests, "Session", start)
    with pytest.raises(RuntimeError, match="dedicated graded E2E"):
        suite_fixture.publish_echo_suite(ADMIN, TASK, "python", "hidden-fixture\n")
    start.assert_not_called()
