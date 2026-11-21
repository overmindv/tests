from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from requests import Response

from src import report
from src.api.gateway import AuthContext, Gateway
from src.api.graphql_client import GraphQLClient
from src.http_error import HttpError

ACTOR = AuthContext(token="fixture-material-session", user_id="reader", email="reader@example.test", username="reader")
SOURCE = "# Private fixture text"
REVISION = {"id": "r1", "number": 1, "message": "", "restoredFromRevisionId": None}
ENTRY = {"id": "m1", "title": "Graphs", "status": "draft", "authorId": "owner"}
MATERIAL = {**ENTRY, "publishedRevisionId": None, "revision": {**REVISION, "source": SOURCE}}
HEAD = {"id": "p1-r1", "ordinal": 1, "parentRevisionId": None, "message": ""}
PROPOSAL = {
    "id": "p1",
    "materialId": "m1",
    "baseRevisionId": "r1",
    "authorId": "author",
    "status": "open",
    "head": {**HEAD, "source": SOURCE},
    "baseOutdated": False,
    "mergedRevisionId": None,
}
VOTE = {"reviewerId": "reader", "decision": "approve", "reason": "", "legacy": False}


@pytest.fixture
def stub(monkeypatch):
    client = GraphQLClient(base_url="http://gateway.test")
    calls = []
    responses = []
    attachments = []

    def post(url, *, json, headers, timeout):
        calls.append((url, json, headers))
        return responses.pop(0)

    def enqueue(body, status=200):
        response = Response()
        response.status_code = status
        response._content = json.dumps(body).encode()
        responses.append(response)

    monkeypatch.setattr(client.session, "post", post)
    monkeypatch.setattr(report, "attach_json", lambda name, value: attachments.append((name, value)))
    return Gateway(client).materials, enqueue, calls, attachments


def arg(calls):
    url, payload, headers = calls[-1]
    assert url == "http://gateway.test/graphql"
    assert headers["Authorization"] == f"Bearer {ACTOR.token}"
    assert SOURCE not in payload["query"]
    return payload["variables"]


def test_material_reads_keep_cursors_and_distinguish_a_hidden_draft(stub):
    materials, enqueue, calls, attachments = stub
    enqueue({"data": {"materials": {"items": [ENTRY], "nextCursor": "next"}}})
    page = materials.catalog(ACTOR, author_id="owner", status="draft", cursor="previous", limit=2)
    assert page.items[0].id == "m1"
    assert page.nextCursor == "next"
    assert arg(calls) == {
        "filter": {"authorId": "owner", "status": "draft", "topicId": None},
        "cursor": "previous",
        "limit": 2,
    }
    enqueue({"data": {"material": None}})
    assert materials.detail(ACTOR, "m1") is None
    assert arg(calls) == {"id": "m1"}
    enqueue({"data": {"publishedMaterial": {**MATERIAL, "status": "published", "publishedRevisionId": "r1"}}})
    assert materials.detail(ACTOR, "m1", published=True).publishedRevisionId == "r1"
    enqueue({"data": {"materialRevisions": {"items": [REVISION], "nextBeforeRevision": 1}}})
    history = materials.revisions(ACTOR, "m1", before=2)
    assert history.items[0].number == 1
    assert history.nextBeforeRevision == 1
    assert arg(calls) == {"id": "m1", "limit": 20, "before": 2}
    assert "source" not in calls[-1][1]["query"]
    assert attachments == []


def test_save_draft_and_restore_send_explicit_revision_ids(stub):
    materials, enqueue, calls, attachments = stub
    enqueue({"data": {"createMaterialDraft": MATERIAL}})
    created = materials.create_draft(ACTOR, title="Graphs", slug="graphs", source=SOURCE, topic_ids=["topic"])
    assert created.revision.source == SOURCE
    assert arg(calls) == {
        "input": {
            "type": "note",
            "title": "Graphs",
            "slug": "graphs",
            "source": SOURCE,
            "learning": {"topicIds": ["topic"]},
        }
    }
    enqueue({"data": {"saveMaterialDraft": {**REVISION, "id": "r2", "number": 2, "source": SOURCE}}})
    saved = materials.save_draft(ACTOR, material_id="m1", expected_revision_id="r1", source=SOURCE)
    assert saved.id == "r2"
    assert arg(calls)["input"]["expectedRevisionId"] == "r1"
    enqueue(
        {
            "data": {
                "restoreMaterialRevision": {**REVISION, "id": "r3", "restoredFromRevisionId": "r1", "source": SOURCE}
            }
        }
    )
    restored = materials.restore(ACTOR, material_id="m1", expected_published_revision_id="r2", source_revision_id="r1")
    assert restored.restoredFromRevisionId == "r1"
    assert arg(calls) == {"id": "m1", "expected": "r2", "source": "r1"}
    assert attachments == []


def test_proposals_use_proposal_revision_ids_and_dont_fetch_history_bodies(stub):
    materials, enqueue, calls, _ = stub
    enqueue({"data": {"openMaterialChange": PROPOSAL}})
    opened = materials.open_change(ACTOR, material_id="m1", base_revision_id="r1", source=SOURCE)
    assert opened.head.id == "p1-r1"
    assert arg(calls)["input"]["baseRevisionId"] == "r1"
    enqueue({"data": {"appendMaterialChange": PROPOSAL}})
    materials.append_change(ACTOR, proposal_id="p1", expected_head_id="p1-r1", source=SOURCE)
    assert arg(calls)["input"]["expectedHeadId"] == "p1-r1"
    enqueue({"data": {"rebaseMaterialChange": {**PROPOSAL, "baseRevisionId": "r2"}}})
    assert (
        materials.rebase_change(
            ACTOR,
            proposal_id="p1",
            expected_head_id="p1-r2",
            base_revision_id="r2",
            source=SOURCE,
        ).baseRevisionId
        == "r2"
    )
    assert arg(calls)["input"]["expectedHeadId"] == "p1-r2"
    enqueue({"data": {"materialChangeProposal": PROPOSAL}})
    assert materials.change(ACTOR, "p1").id == "p1"
    enqueue(
        {"data": {"materialChangeHistory": {"items": [{**HEAD, "baseRevisionId": "r1"}], "nextBeforeOrdinal": None}}}
    )
    assert materials.change_history(ACTOR, "p1", before=2).items[0].baseRevisionId == "r1"
    assert arg(calls)["before"] == 2
    assert "source" not in calls[-1][1]["query"]
    enqueue(
        {
            "data": {
                "materialChangeDiff": {
                    "baseRevisionId": "r1",
                    "revisionId": "p1-r1",
                    "unifiedDiff": SOURCE,
                    "truncated": True,
                }
            }
        }
    )
    assert materials.diff(ACTOR, "p1", revision_id="p1-r1").truncated
    assert arg(calls) == {"id": "p1", "revision": "p1-r1"}
    enqueue({"data": {"closeMaterialChange": {**PROPOSAL, "status": "closed"}}})
    assert materials.close_change(ACTOR, "p1").status == "closed"


def test_vote_and_merge_use_expected_head_and_preserve_conflict(stub):
    materials, enqueue, calls, attachments = stub
    enqueue(
        {
            "data": {
                "materialReviewStatus": {
                    "revisionId": "p1-r1",
                    "current": False,
                    "assignments": [],
                    "decisions": [VOTE],
                    "outcome": "waiting_candidates",
                    "waitReason": "eligibility_unverified",
                    "topicId": "topic",
                }
            }
        }
    )
    review = materials.review(ACTOR, "p1", revision_id="p1-r1")
    assert review.current is False
    assert review.waitReason == "eligibility_unverified"
    assert arg(calls) == {"id": "p1", "revision": "p1-r1"}
    enqueue({"data": {"submitMaterialReview": VOTE}})
    assert materials.vote(ACTOR, proposal_id="p1", revision_id="p1-r2", decision="approve").decision == "approve"
    assert arg(calls)["input"]["revisionId"] == "p1-r2"
    enqueue(
        {
            "errors": [
                {"message": SOURCE, "extensions": {"code": "MERGE_CONFLICT", "detail": SOURCE}},
                {"message": SOURCE, "extensions": {"code": SOURCE}},
            ],
            "data": {"mergeMaterialChange": None},
        }
    )
    with pytest.raises(HttpError, match="MERGE_CONFLICT") as raised:
        materials.merge(ACTOR, proposal_id="p1", expected_head_id="p1-r1")
    assert SOURCE not in str(raised.value)
    assert arg(calls) == {"id": "p1", "head": "p1-r1"}
    enqueue({"data": {"mergeMaterialChange": {"materialId": "m1", "publishedRevisionId": "r3"}}})
    assert materials.merge(ACTOR, proposal_id="p1", expected_head_id="p1-r2").publishedRevisionId == "r3"
    assert attachments == []


def test_private_responses_never_echo_invalid_data(stub):
    materials, enqueue, _, attachments = stub
    enqueue({"data": {"material": {**MATERIAL, "status": SOURCE}}})
    with pytest.raises(ValidationError) as invalid:
        materials.detail(ACTOR, "m1")
    assert SOURCE not in str(invalid.value)
    enqueue({"errors": [{"message": SOURCE}]}, status=403)
    with pytest.raises(HttpError) as denied:
        materials.detail(ACTOR, "m1")
    assert denied.value.status_code == 403
    assert SOURCE not in str(denied.value)
    assert attachments == []
