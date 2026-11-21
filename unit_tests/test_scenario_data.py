from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import Mock, call
from uuid import UUID

import pytest

from src.api.gateway import AuthContext, Gateway, Task
from src.scenario_data import ScenarioData

OWNER_ID = str(UUID(int=1))
SECOND_ID = str(UUID(int=2))
TOPIC_ID = str(UUID(int=3))
TASK_ID = str(UUID(int=4))
ADMIN = AuthContext(
    token="fixture-admin-session",
    user_id=str(UUID(int=5)),
    email="admin@example.test",
    username="admin",
    is_admin=True,
    is_superuser=True,
)


@pytest.fixture
def api():
    gateway = Mock(spec=Gateway)
    ids = iter((OWNER_ID, SECOND_ID))

    def register(email, password, username):
        return AuthContext(token="fixture-user-session", user_id=next(ids), email=email, username=username)

    gateway.register.side_effect = register
    gateway.create_topic.return_value = {"id": TOPIC_ID}
    gateway.create_task.return_value = Task(
        id=TASK_ID,
        status="draft",
        taskVersionId="version",
        versionNumber=1,
        title="Arrays",
        taskType="single_choice",
        difficulty="easy",
    )
    gateway.delete_user.return_value = True
    gateway.delete_topic.return_value = True
    gateway.delete_task.return_value = True
    return gateway


def test_resources_use_distinct_accounts_and_clean_up_in_reverse_order(api):
    with ExitStack() as cleanup:
        data = ScenarioData(api, cleanup)
        owner = data.user()
        second = data.user()
        topic = data.topic(ADMIN, "Practice")
        task = data.task(ADMIN, title="Arrays", statement="Pick one", options=[], topic_id=topic)
        assert owner.email != second.email
        assert owner.username != second.username
        assert owner.email.endswith("@example.test")
        assert task.id == TASK_ID
        assert len(api.method_calls) == 4
        assert api.create_task.call_args.kwargs["topic_id"] == TOPIC_ID
    assert api.method_calls[-4:] == [
        call.delete_task(ADMIN, TASK_ID),
        call.delete_topic(ADMIN, TOPIC_ID),
        call.delete_user(second, SECOND_ID),
        call.delete_user(owner, OWNER_ID),
    ]


def test_cleanup_runs_when_a_later_setup_step_fails(api):
    api.create_task.side_effect = RuntimeError("gateway unavailable")
    with pytest.raises(RuntimeError, match="gateway unavailable"), ExitStack() as cleanup:
        data = ScenarioData(api, cleanup)
        owner = data.user()
        topic = data.topic(ADMIN, "Practice")
        data.task(ADMIN, title="Arrays", statement="Pick one", options=[], topic_id=topic)
    api.delete_task.assert_not_called()
    assert api.method_calls[-2:] == [call.delete_topic(ADMIN, TOPIC_ID), call.delete_user(owner, OWNER_ID)]


def test_one_cleanup_failure_does_not_skip_the_other_resources(api):
    api.delete_task.return_value = False
    with pytest.raises(RuntimeError, match="Could not remove test task"), ExitStack() as cleanup:
        data = ScenarioData(api, cleanup)
        owner = data.user()
        topic = data.topic(ADMIN, "Practice")
        data.task(ADMIN, title="Arrays", statement="Pick one", options=[], topic_id=topic)
    assert api.method_calls[-3:] == [
        call.delete_task(ADMIN, TASK_ID),
        call.delete_topic(ADMIN, TOPIC_ID),
        call.delete_user(owner, OWNER_ID),
    ]


def test_cleanup_is_not_registered_for_unexpected_account(api):
    api.register.side_effect = None
    api.register.return_value = ADMIN
    with pytest.raises(RuntimeError, match="did not return the new test account"), ExitStack() as cleanup:
        ScenarioData(api, cleanup).user()
    api.delete_user.assert_not_called()


def test_null_uuid_cannot_be_registered_for_cleanup(api):
    api.create_topic.return_value = {"id": str(UUID(int=0))}
    with pytest.raises(ValueError, match="Empty topic ID"), ExitStack() as cleanup:
        ScenarioData(api, cleanup).topic(ADMIN, "Practice")
    api.delete_topic.assert_not_called()
