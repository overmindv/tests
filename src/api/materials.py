from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from src.api.gateway import AuthContext
    from src.api.graphql_client import GraphQLClient

MaterialStatus = Literal["draft", "published", "archived"]
ReviewDecision = Literal["approve", "request_changes"]
ReviewOutcome = Literal["waiting_candidates", "pending", "approved", "changes_requested"]


class _MaterialResponse(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class RevisionSummary(_MaterialResponse):
    id: str
    number: int
    message: str
    restoredFromRevisionId: str | None


class Revision(RevisionSummary):
    source: str


class RevisionPage(_MaterialResponse):
    items: list[RevisionSummary]
    nextBeforeRevision: int | None


class CatalogEntry(_MaterialResponse):
    id: str
    title: str
    status: MaterialStatus
    authorId: str | None


class CatalogPage(_MaterialResponse):
    items: list[CatalogEntry]
    nextCursor: str | None


class Material(CatalogEntry):
    publishedRevisionId: str | None
    revision: Revision | None


class ChangeRevision(_MaterialResponse):
    id: str
    ordinal: int
    parentRevisionId: str | None
    message: str


class ChangeCandidate(ChangeRevision):
    source: str


class ChangeHistoryEntry(ChangeRevision):
    baseRevisionId: str


class ChangeHistoryPage(_MaterialResponse):
    items: list[ChangeHistoryEntry]
    nextBeforeOrdinal: int | None


class ChangeProposal(_MaterialResponse):
    id: str
    materialId: str
    baseRevisionId: str
    authorId: str
    status: Literal["open", "closed", "merged"]
    head: ChangeCandidate
    baseOutdated: bool
    mergedRevisionId: str | None


class ChangeDiff(_MaterialResponse):
    baseRevisionId: str
    revisionId: str
    unifiedDiff: str
    truncated: bool


class Vote(_MaterialResponse):
    reviewerId: str
    decision: ReviewDecision
    reason: str
    legacy: bool


class ReviewAssignment(_MaterialResponse):
    reviewerId: str
    slot: int


class ReviewStatus(_MaterialResponse):
    revisionId: str
    current: bool
    assignments: list[ReviewAssignment]
    decisions: list[Vote]
    outcome: ReviewOutcome
    waitReason: str | None
    topicId: str | None


class MergeResult(_MaterialResponse):
    materialId: str
    publishedRevisionId: str


_REVISION_SUMMARY = "id number message restoredFromRevisionId"
_REVISION = f"{_REVISION_SUMMARY} source"
_CATALOG_ENTRY = "id title status authorId"
_MATERIAL = f"{_CATALOG_ENTRY} publishedRevisionId revision {{ {_REVISION} }}"
_CHANGE_REVISION = "id ordinal parentRevisionId message"
_PROPOSAL = (
    f"id materialId baseRevisionId authorId status baseOutdated mergedRevisionId head {{ {_CHANGE_REVISION} source }}"
)
_VOTE = "reviewerId decision reason legacy"

_Response = TypeVar("_Response", bound=_MaterialResponse)


class MaterialGateway:
    def __init__(self, gql: GraphQLClient) -> None:
        self._gql = gql

    def catalog(
        self,
        actor: AuthContext,
        *,
        topic_id: str | None = None,
        author_id: str | None = None,
        status: MaterialStatus | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> CatalogPage:
        return self._read(
            actor,
            "materials",
            "($filter: MaterialCatalogFilter, $limit: Int!, $cursor: String)",
            "(filter: $filter, limit: $limit, cursor: $cursor)",
            f"items {{ {_CATALOG_ENTRY} }} nextCursor",
            {
                "filter": {"topicId": topic_id, "authorId": author_id, "status": status},
                "limit": limit,
                "cursor": cursor,
            },
            CatalogPage,
        )

    def detail(self, actor: AuthContext, material_id: str, *, published: bool = False) -> Material | None:
        field = "publishedMaterial" if published else "material"
        payload = self._request(actor, "query", field, "($id: ID!)", "(id: $id)", _MATERIAL, {"id": material_id})
        return Material.model_validate(payload) if payload is not None else None

    def revisions(
        self,
        actor: AuthContext,
        material_id: str,
        *,
        limit: int = 20,
        before: int | None = None,
    ) -> RevisionPage:
        return self._read(
            actor,
            "materialRevisions",
            "($id: ID!, $limit: Int!, $before: Int)",
            "(id: $id, limit: $limit, beforeRevision: $before)",
            f"items {{ {_REVISION_SUMMARY} }} nextBeforeRevision",
            {"id": material_id, "limit": limit, "before": before},
            RevisionPage,
        )

    def create_draft(
        self,
        actor: AuthContext,
        *,
        title: str,
        slug: str,
        source: str,
        topic_ids: list[str] | None = None,
    ) -> Material:
        values = {"type": "note", "title": title, "slug": slug, "source": source}
        return self._mutate(
            actor,
            "createMaterialDraft",
            "CreateMaterialDraftInput",
            _MATERIAL,
            {**values, "learning": {"topicIds": topic_ids or []}},
            Material,
        )

    def save_draft(
        self,
        actor: AuthContext,
        *,
        material_id: str,
        expected_revision_id: str,
        source: str,
        message: str = "",
    ) -> Revision:
        return self._mutate(
            actor,
            "saveMaterialDraft",
            "SaveMaterialDraftInput",
            _REVISION,
            {
                "materialId": material_id,
                "expectedRevisionId": expected_revision_id,
                "source": source,
                "message": message,
            },
            Revision,
        )

    def open_change(
        self,
        actor: AuthContext,
        *,
        material_id: str,
        base_revision_id: str,
        source: str,
        message: str = "",
    ) -> ChangeProposal:
        return self._mutate(
            actor,
            "openMaterialChange",
            "OpenMaterialChangeInput",
            _PROPOSAL,
            {"materialId": material_id, "baseRevisionId": base_revision_id, "source": source, "message": message},
            ChangeProposal,
        )

    def append_change(
        self,
        actor: AuthContext,
        *,
        proposal_id: str,
        expected_head_id: str,
        source: str,
        message: str = "",
    ) -> ChangeProposal:
        return self._mutate(
            actor,
            "appendMaterialChange",
            "AppendMaterialChangeInput",
            _PROPOSAL,
            {"proposalId": proposal_id, "expectedHeadId": expected_head_id, "source": source, "message": message},
            ChangeProposal,
        )

    def rebase_change(
        self,
        actor: AuthContext,
        *,
        proposal_id: str,
        expected_head_id: str,
        base_revision_id: str,
        source: str,
        message: str = "",
    ) -> ChangeProposal:
        return self._mutate(
            actor,
            "rebaseMaterialChange",
            "RebaseMaterialChangeInput",
            _PROPOSAL,
            {
                "proposalId": proposal_id,
                "expectedHeadId": expected_head_id,
                "baseRevisionId": base_revision_id,
                "source": source,
                "message": message,
            },
            ChangeProposal,
        )

    def change(self, actor: AuthContext, proposal_id: str) -> ChangeProposal:
        return self._read(
            actor,
            "materialChangeProposal",
            "($id: ID!)",
            "(id: $id)",
            _PROPOSAL,
            {"id": proposal_id},
            ChangeProposal,
        )

    def close_change(self, actor: AuthContext, proposal_id: str) -> ChangeProposal:
        payload = self._request(
            actor,
            "mutation",
            "closeMaterialChange",
            "($id: ID!)",
            "(proposalId: $id)",
            _PROPOSAL,
            {"id": proposal_id},
        )
        return ChangeProposal.model_validate(payload)

    def change_history(
        self,
        actor: AuthContext,
        proposal_id: str,
        *,
        limit: int = 20,
        before: int | None = None,
    ) -> ChangeHistoryPage:
        return self._read(
            actor,
            "materialChangeHistory",
            "($id: ID!, $limit: Int!, $before: Int)",
            "(proposalId: $id, limit: $limit, beforeOrdinal: $before)",
            f"items {{ {_CHANGE_REVISION} baseRevisionId }} nextBeforeOrdinal",
            {"id": proposal_id, "limit": limit, "before": before},
            ChangeHistoryPage,
        )

    def diff(self, actor: AuthContext, proposal_id: str, *, revision_id: str | None = None) -> ChangeDiff:
        return self._read(
            actor,
            "materialChangeDiff",
            "($id: ID!, $revision: ID)",
            "(proposalId: $id, revisionId: $revision)",
            "baseRevisionId revisionId unifiedDiff truncated",
            {"id": proposal_id, "revision": revision_id},
            ChangeDiff,
        )

    def review(self, actor: AuthContext, proposal_id: str, *, revision_id: str | None = None) -> ReviewStatus:
        return self._read(
            actor,
            "materialReviewStatus",
            "($id: ID!, $revision: ID)",
            "(proposalId: $id, revisionId: $revision)",
            f"revisionId current assignments {{ reviewerId slot }} decisions {{ {_VOTE} }} outcome waitReason topicId",
            {"id": proposal_id, "revision": revision_id},
            ReviewStatus,
        )

    def vote(
        self,
        actor: AuthContext,
        *,
        proposal_id: str,
        revision_id: str,
        decision: ReviewDecision,
        reason: str = "",
    ) -> Vote:
        return self._mutate(
            actor,
            "submitMaterialReview",
            "SubmitMaterialReviewInput",
            _VOTE,
            {"proposalId": proposal_id, "revisionId": revision_id, "decision": decision, "reason": reason},
            Vote,
        )

    def merge(self, actor: AuthContext, *, proposal_id: str, expected_head_id: str) -> MergeResult:
        payload = self._request(
            actor,
            "mutation",
            "mergeMaterialChange",
            "($id: ID!, $head: ID!)",
            "(proposalId: $id, expectedHeadId: $head)",
            "materialId publishedRevisionId",
            {"id": proposal_id, "head": expected_head_id},
        )
        return MergeResult.model_validate(payload)

    def restore(
        self,
        actor: AuthContext,
        *,
        material_id: str,
        expected_published_revision_id: str,
        source_revision_id: str,
    ) -> Revision:
        payload = self._request(
            actor,
            "mutation",
            "restoreMaterialRevision",
            "($id: ID!, $expected: ID!, $source: ID!)",
            "(materialId: $id, expectedPublishedRevisionId: $expected, sourceRevisionId: $source)",
            _REVISION,
            {"id": material_id, "expected": expected_published_revision_id, "source": source_revision_id},
        )
        return Revision.model_validate(payload)

    def _read(
        self,
        actor: AuthContext,
        field: str,
        parameters: str,
        arguments: str,
        selection: str,
        variables: dict[str, Any],
        model: type[_Response],
    ) -> _Response:
        return model.model_validate(self._request(actor, "query", field, parameters, arguments, selection, variables))

    def _mutate(
        self,
        actor: AuthContext,
        field: str,
        input_type: str,
        selection: str,
        values: dict[str, Any],
        model: type[_Response],
    ) -> _Response:
        payload = self._request(
            actor,
            "mutation",
            field,
            f"($input: {input_type}!)",
            "(input: $input)",
            selection,
            {"input": values},
        )
        return model.model_validate(payload)

    def _request(
        self,
        actor: AuthContext,
        action: str,
        field: str,
        parameters: str,
        arguments: str,
        selection: str,
        variables: dict[str, Any],
    ) -> Any:
        operation = field[0].upper() + field[1:]
        query = f"{action} {operation}{parameters} {{ {field}{arguments} {{ {selection} }} }}"
        return self._gql.execute(operation, query, variables, token=actor.token, capture_body=False)[field]
