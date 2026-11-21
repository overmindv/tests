from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from requests import Response

from src import report
from src.api.gateway import AuthContext, Gateway
from src.api.graphql_client import GraphQLClient
from src.http_error import HttpError

OWNER = AuthContext(token="fixture-plan-owner", user_id="owner", email="owner@example.test", username="owner")
READER = AuthContext(token="fixture-plan-reader", user_id="reader", email="reader@example.test", username="reader")
GOAL = "Private learning fixture"
ITEM = {
    "taskId": "task",
    "taskVersionId": "version-1",
    "topicId": "topic",
    "title": "Suffix arrays",
    "difficulty": "easy",
    "taskType": "single_choice",
    "estimatedMinutes": 10,
    "reasonCode": "START_TOPIC",
}
PRACTICE = {"policyVersion": "practice-v2", "totalMinutes": 10, "warnings": [], "items": [ITEM]}
SCHEDULE = {
    **PRACTICE,
    "aiStatus": "GENERATED",
    "requestedSessions": 2,
    "totalPlannedMinutes": 10,
    "sessions": [{"number": 1, "totalMinutes": 10, "items": [ITEM]}],
    "topicInsights": [
        {
            "topicId": "topic",
            "title": "Strings",
            "isTarget": True,
            "acceptedTasks": 0,
            "failedTasks": 0,
            "eligibleTasks": 1,
            "plannedTasks": 1,
            "remainingToReadiness": 1,
            "recommendedDifficulty": "easy",
            "minimumMinutes": 10,
            "blockedBy": [{"id": "previous", "title": "Arrays"}],
            "nextAction": "practice",
        }
    ],
}
MATERIAL = {"id": "material", "title": "Arrays", "url": "/materials/material", "action": "read", "minutes": 10}
SAVED = {
    "id": "plan",
    "goal": GOAL,
    "isOwner": True,
    "public": False,
    "revision": 1,
    "minutes": 30,
    "sessionCount": 2,
    "materials": [{**MATERIAL, "status": "TODO"}],
    "tasks": [
        {
            "id": "task",
            "versionId": "version-1",
            "title": "Suffix arrays",
            "minutes": 10,
            "completed": False,
            "completionVersionId": None,
        }
    ],
    "progressAvailable": True,
}


@pytest.fixture
def gateway_stub(monkeypatch):
    gql = GraphQLClient(base_url="http://gateway.test", path="/graphql")
    received = []
    replies = []
    attachments = []

    def post(url, *, json, headers, timeout):
        received.append((json, headers))
        response = Response()
        response.status_code = 200
        response._content = replies.pop(0)
        return response

    def reply(body):
        replies.append(json.dumps(body).encode())

    monkeypatch.setattr(gql.session, "post", post)
    monkeypatch.setattr(report, "attach_json", lambda name, value: attachments.append((name, value)))
    return Gateway(gql), reply, received, attachments


def sent(received, actor=OWNER):
    request, headers = received[-1]
    assert headers["Authorization"] == f"Bearer {actor.token}"
    assert GOAL not in request["query"]
    return request.get("variables", {})


def test_practice_stays_compatible_while_schedule_includes_budget_and_prerequisites(gateway_stub):
    api, reply, received, attachments = gateway_stub
    reply({"data": {"practicePlan": PRACTICE}})
    plan = api.practice_plan(OWNER, ["topic"])
    assert plan.items[0].taskVersionId == "version-1"
    assert sent(received) == {"topicIds": ["topic"], "minutes": 60}
    assert "sessionCount" not in received[-1][0]["query"]
    assert "topicInsights" not in received[-1][0]["query"]
    reply({"data": {"practicePlan": SCHEDULE}})
    schedule = api.learning.practice_schedule(OWNER, ["topic"], 30, session_count=2, goal=GOAL)
    assert schedule.sessions[0].totalMinutes == 10
    assert schedule.topicInsights[0].blockedBy[0].id == "previous"
    assert sent(received) == {"topicIds": ["topic"], "minutes": 30, "sessionCount": 2, "goal": GOAL}
    assert attachments == []


def test_learning_preview_supports_no_practice(gateway_stub):
    api, reply, received, _ = gateway_stub
    reply(
        {
            "data": {
                "learningPlan": {
                    "aiStatus": "NO_MATCH",
                    "topics": [],
                    "materials": [MATERIAL],
                    "practice": None,
                    "warnings": ["NO_TASKS"],
                }
            }
        }
    )
    result = api.learning.preview(OWNER, goal=GOAL, minutes=30, session_count=2)
    assert result.practice is None
    assert result.materials[0].id == "material"
    assert sent(received) == {"goal": GOAL, "minutes": 30, "sessionCount": 2}


def test_practice_goal_stays_bound_to_the_authenticated_actor(gateway_stub):
    api, reply, received, _ = gateway_stub
    reply({"data": {"myPracticeGoal": None}})
    assert api.learning.practice_goal(OWNER) is None
    assert sent(received) == {}
    goal = {
        "topics": [{"id": "topic", "title": "Arrays", "status": "active"}],
        "minutes": 30,
        "sessionCount": 2,
        "revision": 3,
    }
    reply({"data": {"savePracticeGoal": goal}})
    assert api.learning.save_practice_goal(OWNER, ["topic"], 30, session_count=2).revision == 3
    assert sent(received) == {"topicIds": ["topic"], "minutes": 30, "sessionCount": 2}
    reply({"data": {"myPracticeGoal": goal}})
    assert api.learning.practice_goal(OWNER).topics[0].id == "topic"
    reply({"data": {"deletePracticeGoal": True}})
    assert api.learning.delete_practice_goal(OWNER)
    assert sent(received) == {}


def test_saved_plan_retry_and_independent_copy_keep_distinct_tokens_and_request_ids(gateway_stub):
    api, reply, received, attachments = gateway_stub
    reply({"data": {"saveLearningPlan": SAVED}})
    saved = api.learning.save(OWNER, goal=GOAL, minutes=30, session_count=2, request_id="create-request")
    assert saved.id == "plan"
    assert sent(received) == {"goal": GOAL, "minutes": 30, "sessionCount": 2, "requestId": "create-request"}
    reply({"data": {"myLearningPlans": [SAVED]}})
    assert api.learning.list_saved(OWNER) == [saved]
    assert sent(received) == {}
    reply({"data": {"savedLearningPlan": {**SAVED, "public": True, "isOwner": False, "progressAvailable": False}}})
    shared = api.learning.saved(READER, "plan")
    assert shared.progressAvailable is False
    assert sent(received, READER) == {"id": "plan"}
    reply({"data": {"cloneLearningPlan": {**SAVED, "id": "copy"}}})
    cloned = api.learning.clone(READER, shared.id, request_id="copy-request")
    assert cloned.id == "copy"
    assert cloned.public is False
    assert sent(received, READER) == {"id": "plan", "requestId": "copy-request"}
    assert attachments == []


def test_plan_writes_send_expected_revision_and_do_not_retry_conflicts(gateway_stub):
    api, reply, received, attachments = gateway_stub
    reply({"data": {"setLearningPlanPublic": {**SAVED, "revision": 2, "public": True}}})
    updated = api.learning.set_public(OWNER, "plan", 1, public=True)
    assert updated.public is True
    assert sent(received) == {"id": "plan", "revision": 1, "public": True}
    reply(
        {
            "data": {
                "updateLearningMaterial": {
                    **SAVED,
                    "revision": 3,
                    "materials": [{**MATERIAL, "status": "DONE"}],
                }
            }
        }
    )
    write = api.learning.mark_material(OWNER, "plan", 2, material_id="material", status="DONE")
    assert write.materials[0].status == "DONE"
    assert sent(received) == {"id": "plan", "revision": 2, "materialId": "material", "status": "DONE"}
    reply({"data": {"removeLearningPlanTask": {**SAVED, "revision": 4, "tasks": []}}})
    assert api.learning.remove_task(OWNER, "plan", write.revision, task_id="task").tasks == []
    assert sent(received) == {"id": "plan", "revision": 3, "taskId": "task"}
    reply({"errors": [{"message": GOAL, "extensions": {"code": "CONFLICT"}}]})
    with pytest.raises(HttpError, match="CONFLICT") as conflict:
        api.learning.refresh(OWNER, "plan", 3)
    assert GOAL not in str(conflict.value)
    assert sent(received) == {"id": "plan", "revision": 3}
    assert len(received) == 4
    assert attachments == []


def test_invalid_saved_plan_list_does_not_echo_private_payload(gateway_stub):
    api, reply, _, attachments = gateway_stub
    reply({"data": {"myLearningPlans": {"goal": GOAL}}})
    with pytest.raises(ValidationError) as invalid:
        api.learning.list_saved(OWNER)
    assert GOAL not in str(invalid.value)
    assert attachments == []
