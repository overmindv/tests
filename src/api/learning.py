from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, TypeAdapter

from src import generate

if TYPE_CHECKING:
    from src.api.gateway import AuthContext
    from src.api.graphql_client import GraphQLClient

MaterialProgress = Literal["TODO", "IN_PROGRESS", "DONE"]
_Result = TypeVar("_Result")


class _LearningResponse(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class Topic(_LearningResponse):
    id: str
    title: str


class GoalTopic(Topic):
    status: str


class PracticeGoal(_LearningResponse):
    topics: list[GoalTopic]
    minutes: int
    sessionCount: int
    revision: int


class PracticeItem(_LearningResponse):
    taskId: str
    taskVersionId: str
    topicId: str
    title: str
    difficulty: str
    taskType: str
    estimatedMinutes: int
    reasonCode: str


class PracticePlan(_LearningResponse):
    policyVersion: str
    totalMinutes: int
    warnings: list[str]
    items: list[PracticeItem]


class PracticeSession(_LearningResponse):
    number: int
    totalMinutes: int
    items: list[PracticeItem]


class TopicInsight(_LearningResponse):
    topicId: str
    title: str
    isTarget: bool
    acceptedTasks: int
    failedTasks: int
    eligibleTasks: int
    plannedTasks: int
    remainingToReadiness: int
    recommendedDifficulty: str
    minimumMinutes: int
    blockedBy: list[Topic]
    nextAction: str


class PracticeSchedule(PracticePlan):
    aiStatus: str
    requestedSessions: int
    totalPlannedMinutes: int
    sessions: list[PracticeSession]
    topicInsights: list[TopicInsight]


class LearningMaterial(_LearningResponse):
    id: str
    title: str
    url: str
    action: str
    minutes: int


class LearningPreview(_LearningResponse):
    aiStatus: str
    topics: list[Topic]
    materials: list[LearningMaterial]
    practice: PracticeSchedule | None
    warnings: list[str]


class SavedMaterial(LearningMaterial):
    status: MaterialProgress


class SavedTask(_LearningResponse):
    id: str
    versionId: str
    title: str
    minutes: int
    completed: bool
    completionVersionId: str | None


class SavedPlan(_LearningResponse):
    id: str
    goal: str
    isOwner: bool
    public: bool
    revision: int
    minutes: int
    sessionCount: int
    materials: list[SavedMaterial]
    tasks: list[SavedTask]
    progressAvailable: bool


_PRACTICE_ITEM = "taskId taskVersionId topicId title difficulty taskType estimatedMinutes reasonCode"
_PRACTICE = f"policyVersion totalMinutes warnings items {{ {_PRACTICE_ITEM} }}"
_SCHEDULE = (
    f"{_PRACTICE} aiStatus requestedSessions totalPlannedMinutes"
    f" sessions {{ number totalMinutes items {{ {_PRACTICE_ITEM} }} }}"
    " topicInsights { topicId title isTarget acceptedTasks failedTasks eligibleTasks plannedTasks"
    " remainingToReadiness recommendedDifficulty minimumMinutes blockedBy { id title } nextAction }"
)
_GOAL = "topics { id title status } minutes sessionCount revision"
_MATERIAL = "id title url action minutes"
_PREVIEW = f"aiStatus topics {{ id title }} materials {{ {_MATERIAL} }} practice {{ {_SCHEDULE} }} warnings"
_SAVED = (
    "id goal isOwner public revision minutes sessionCount progressAvailable"
    f" materials {{ {_MATERIAL} status }}"
    " tasks { id versionId title minutes completed completionVersionId }"
)
_PRACTICE_ARGS = {"topicIds": "[ID!]!", "minutes": "Int!"}
_SCHEDULE_ARGS = {**_PRACTICE_ARGS, "sessionCount": "Int", "goal": "String"}
_LEARNING_ARGS = {"goal": "String!", "minutes": "Int!", "sessionCount": "Int!"}
_REVISION_ARGS = {"id": "ID!", "revision": "Int!"}
_SAVED_LIST = TypeAdapter(list[SavedPlan], config=ConfigDict(hide_input_in_errors=True))
_OPTIONAL_GOAL = TypeAdapter(PracticeGoal | None, config=ConfigDict(hide_input_in_errors=True))
_BOOL = TypeAdapter(bool, config=ConfigDict(hide_input_in_errors=True, strict=True))


class LearningGateway:
    def __init__(self, gql: GraphQLClient) -> None:
        self._gql = gql

    def practice(self, actor: AuthContext, topic_ids: list[str], minutes: int = 60) -> PracticePlan:
        # The shared E2E job pins a Gateway without session and insight fields.
        return self._call(
            actor,
            "query",
            "practicePlan",
            _PRACTICE,
            PracticePlan.model_validate,
            _PRACTICE_ARGS,
            topicIds=topic_ids,
            minutes=minutes,
        )

    def practice_schedule(
        self,
        actor: AuthContext,
        topic_ids: list[str],
        minutes: int = 60,
        *,
        session_count: int | None = None,
        goal: str | None = None,
    ) -> PracticeSchedule:
        return self._call(
            actor,
            "query",
            "practicePlan",
            _SCHEDULE,
            PracticeSchedule.model_validate,
            _SCHEDULE_ARGS,
            topicIds=topic_ids,
            minutes=minutes,
            sessionCount=session_count,
            goal=goal,
        )

    def preview(self, actor: AuthContext, *, goal: str, minutes: int, session_count: int) -> LearningPreview:
        return self._call(
            actor,
            "query",
            "learningPlan",
            _PREVIEW,
            LearningPreview.model_validate,
            _LEARNING_ARGS,
            goal=goal,
            minutes=minutes,
            sessionCount=session_count,
        )

    def practice_goal(self, actor: AuthContext) -> PracticeGoal | None:
        return self._call(actor, "query", "myPracticeGoal", _GOAL, _OPTIONAL_GOAL.validate_python)

    def save_practice_goal(
        self,
        actor: AuthContext,
        topic_ids: list[str],
        minutes: int,
        *,
        session_count: int | None = None,
    ) -> PracticeGoal:
        return self._call(
            actor,
            "mutation",
            "savePracticeGoal",
            _GOAL,
            PracticeGoal.model_validate,
            {**_PRACTICE_ARGS, "sessionCount": "Int"},
            topicIds=topic_ids,
            minutes=minutes,
            sessionCount=session_count,
        )

    def delete_practice_goal(self, actor: AuthContext) -> bool:
        return self._call(actor, "mutation", "deletePracticeGoal", "", _BOOL.validate_python)

    def list_saved(self, actor: AuthContext) -> list[SavedPlan]:
        return self._call(actor, "query", "myLearningPlans", _SAVED, _SAVED_LIST.validate_python)

    def saved(self, actor: AuthContext, plan_id: str) -> SavedPlan:
        return self._call(
            actor,
            "query",
            "savedLearningPlan",
            _SAVED,
            SavedPlan.model_validate,
            {"id": "ID!"},
            id=plan_id,
        )

    def save(
        self,
        actor: AuthContext,
        *,
        goal: str,
        minutes: int,
        session_count: int,
        request_id: str | None = None,
    ) -> SavedPlan:
        return self._call(
            actor,
            "mutation",
            "saveLearningPlan",
            _SAVED,
            SavedPlan.model_validate,
            {**_LEARNING_ARGS, "requestId": "ID!"},
            goal=goal,
            minutes=minutes,
            sessionCount=session_count,
            requestId=request_id or generate.uuid4(),
        )

    def clone(self, actor: AuthContext, plan_id: str, *, request_id: str | None = None) -> SavedPlan:
        return self._call(
            actor,
            "mutation",
            "cloneLearningPlan",
            _SAVED,
            SavedPlan.model_validate,
            {"id": "ID!", "requestId": "ID!"},
            id=plan_id,
            requestId=request_id or generate.uuid4(),
        )

    def set_public(self, actor: AuthContext, plan_id: str, revision: int, *, public: bool) -> SavedPlan:
        return self._call(
            actor,
            "mutation",
            "setLearningPlanPublic",
            _SAVED,
            SavedPlan.model_validate,
            {**_REVISION_ARGS, "public": "Boolean!"},
            id=plan_id,
            revision=revision,
            public=public,
        )

    def mark_material(
        self,
        actor: AuthContext,
        plan_id: str,
        revision: int,
        *,
        material_id: str,
        status: MaterialProgress,
    ) -> SavedPlan:
        return self._call(
            actor,
            "mutation",
            "updateLearningMaterial",
            _SAVED,
            SavedPlan.model_validate,
            {**_REVISION_ARGS, "materialId": "ID!", "status": "MaterialProgress!"},
            id=plan_id,
            revision=revision,
            materialId=material_id,
            status=status,
        )

    def remove_task(self, actor: AuthContext, plan_id: str, revision: int, *, task_id: str) -> SavedPlan:
        return self._call(
            actor,
            "mutation",
            "removeLearningPlanTask",
            _SAVED,
            SavedPlan.model_validate,
            {**_REVISION_ARGS, "taskId": "ID!"},
            id=plan_id,
            revision=revision,
            taskId=task_id,
        )

    def refresh(self, actor: AuthContext, plan_id: str, revision: int) -> SavedPlan:
        return self._call(
            actor,
            "mutation",
            "refreshLearningPlan",
            _SAVED,
            SavedPlan.model_validate,
            _REVISION_ARGS,
            id=plan_id,
            revision=revision,
        )

    def _call(
        self,
        actor: AuthContext,
        kind: str,
        field: str,
        selection: str,
        decode: Callable[[Any], _Result],
        arg_types: dict[str, str] | None = None,
        **variables: Any,
    ) -> _Result:
        operation = field[0].upper() + field[1:]
        declaration = (
            "(" + ", ".join(f"${name}: {type_}" for name, type_ in arg_types.items()) + ")" if arg_types else ""
        )
        arguments = "(" + ", ".join(f"{name}: ${name}" for name in arg_types) + ")" if arg_types else ""
        fields = f" {{ {selection} }}" if selection else ""
        query = f"{kind} {operation}{declaration} {{ {field}{arguments}{fields} }}"
        return decode(self._gql.execute(operation, query, variables, token=actor.token, capture_body=False)[field])
