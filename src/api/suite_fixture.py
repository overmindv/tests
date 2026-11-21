from __future__ import annotations

import os
from uuid import UUID

import requests

from src.api.gateway import AuthContext, ProgrammingLanguage, Task
from src.configuration import config

PUBLIC_INPUT = "sample-line\n"
SUITE_LIMITS = {
    "cpu_ms": 1000,
    "wall_ms": 1500,
    "memory_mb": 128,
    "pids": 16,
    "stdout_bytes": 256,
    "stderr_bytes": 256,
    "workspace_bytes": 4 << 20,
}
_TASKS = "http://tasks:8080/v1/admin"
_RUNTIMES = {"python": "3.12", "go": "1.26"}


def publish_echo_suite(admin: AuthContext, task: Task, language: ProgrammingLanguage, hidden_input: str) -> str:
    # The suite API is internal; use it only from the dedicated Compose network.
    if os.environ.get("GRADED_E2E") != "1" or config.BASE_URL != "http://api-gateway:8081":
        raise RuntimeError("Suite fixtures require the dedicated graded E2E stack")
    if not admin.is_superuser or task.status != "draft" or task.versionNumber != 1:
        raise RuntimeError("Expected the fixture superuser and a new task")
    headers = {"X-User-ID": str(UUID(admin.user_id)), "X-User-Roles": "superuser"}
    definition = {
        "language": language,
        "language_version": _RUNTIMES[language],
        "checker": "trim_newlines",
        "limits": SUITE_LIMITS,
        "cases": [
            {"id": "suite-sample", "input": PUBLIC_INPUT, "output": PUBLIC_INPUT, "hidden": False},
            {"id": "suite-private", "input": hidden_input, "output": hidden_input, "hidden": True},
        ],
    }
    with requests.Session() as session:
        session.trust_env = False
        draft = session.post(
            f"{_TASKS}/tasks/{UUID(task.id)}/suite-drafts",
            headers=headers,
            timeout=10,
            allow_redirects=False,
            json={"base_version_id": str(UUID(task.taskVersionId)), "definition": definition},
        )
        if draft.status_code != 201:
            raise RuntimeError(f"Suite fixture creation returned HTTP {draft.status_code}")
        data = draft.json()
        draft_id = UUID(data["id"])
        revision = data["revision"]
        published = session.post(
            f"{_TASKS}/suite-drafts/{draft_id}/publish",
            headers=headers,
            json={"revision": revision},
            timeout=20,
            allow_redirects=False,
        )
        if published.status_code != 200:
            raise RuntimeError(f"Suite fixture publication returned HTTP {published.status_code}")
        return str(UUID(published.json()["task_version_id"]))
