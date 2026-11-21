from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENDPOINTS = ("unix://", "npipe://")
SERVICE_IMAGES = {
    "GATEWAY": ("api-gateway", "api-gateway", "Dockerfile"),
    "TASKS": ("tasks", "tasks", "Dockerfile"),
    "USERS": ("users", "users", "Dockerfile"),
    "WORKER": ("worker", "sandbox", "deployments/docker/Dockerfile.worker"),
    "JUDGE": ("judge", "sandbox", "deployments/docker/Dockerfile.gojudge-runtime"),
}
_JUDGES = {"gojudge", "gojudge-compiler"}


def output(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def require_local_docker() -> None:
    endpoint = output("docker", "context", "inspect", "--format", '{{(index .Endpoints "docker").Host}}')
    explicit = os.environ.get("DOCKER_HOST", endpoint)
    if not endpoint.startswith(LOCAL_ENDPOINTS) or not explicit.startswith(LOCAL_ENDPOINTS):
        raise SystemExit("Graded E2E requires a local Docker context")
    if output("docker", "info", "--format", "{{.OSType}}") != "linux":
        raise SystemExit("Graded E2E requires Linux containers")


def build_images(workspace: Path, run_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    entries = json.loads((ROOT / "ci/graded-refs.json").read_text(encoding="utf-8"))
    refs = {item["repository"]: item["revision"] for item in entries}
    if len(entries) != len(refs) or set(refs) != {repo for _, repo, _ in SERVICE_IMAGES.values()}:
        raise SystemExit("graded-refs.json does not match the service list")
    for repo, sha in refs.items():
        if not isinstance(sha, str) or not re.fullmatch("[0-9a-f]{40}", sha):
            raise SystemExit(f"Expected a full Git SHA for {repo}")
        source = workspace / repo
        remote = output("git", "-C", str(source), "remote", "get-url", "origin")
        if remote.removesuffix(".git") not in (
            f"https://github.com/overmindv/{repo}",
            f"git@github.com:overmindv/{repo}",
        ):
            raise SystemExit(f"Expected overmindv/{repo} in {source}")
        subprocess.run(["git", "-C", str(source), "merge-base", "--is-ancestor", sha, "origin/main"], check=True)
        archive = run_dir / f"{repo}.tar"
        subprocess.run(
            ["git", "-C", str(source), "-c", "core.autocrlf=false", "archive", "-o", str(archive), sha],
            check=True,
        )
        with tarfile.open(archive) as snapshot:
            snapshot.extractall(run_dir / repo, filter="data")
    images = {}
    for variable, (name, repo, dockerfile) in SERVICE_IMAGES.items():
        sha = refs[repo]
        context = run_dir / repo
        tag = f"ovm257-test/{name}:{sha[:7]}"
        subprocess.run(
            [
                "docker",
                "build",
                "--label",
                f"org.opencontainers.image.revision={sha}",
                "-t",
                tag,
                "-f",
                str(context / dockerfile),
                str(context),
            ],
            check=True,
        )
        images[f"GRADED_{variable}_IMAGE"] = output("docker", "image", "inspect", "--format", "{{.Id}}", tag)
    return refs, images


def validate_stack(model: dict[str, Any], evidence: Path) -> None:
    networks = model["networks"]
    if set(networks) != {"default", "judge"} or any(
        network.get("internal") is not True or network.get("external") for network in networks.values()
    ):
        raise RuntimeError("Graded E2E networks must be private to the project")
    if model.get("volumes"):
        raise RuntimeError("Graded E2E cannot use persistent volumes")
    for name, source in model.get("configs", {}).items():
        if name != "sandbox-graded" or not source.get("content") or set(source) - {"name", "content"}:
            raise RuntimeError("Graded E2E config must be inline")
    for name, service in model["services"].items():
        if any(
            service.get(key) for key in ("ports", "container_name", "network_mode", "pid", "ipc", "devices", "cap_add")
        ):
            raise RuntimeError(f"Unexpected host access in graded E2E service {name}")
        if name in _JUDGES:
            if (
                service.get("privileged") is not True
                or service.get("read_only") is not True
                or set(service.get("networks", ())) != {"judge"}
                or service.get("environment")
                or service.get("secrets")
            ):
                raise RuntimeError(f"Unsafe runtime configuration in {name}")
        elif service.get("privileged"):
            raise RuntimeError(f"Only the judge can be privileged, not {name}")
        for source in service.get("configs", ()):
            if (
                name != "sandbox"
                or source["source"] != "sandbox-graded"
                or source["target"] != "/etc/sandbox-graded.yaml"
            ):
                raise RuntimeError(f"Unexpected config mount in graded E2E service {name}")
        for mount in service.get("volumes", ()):
            if not (
                name == "test"
                and mount["type"] == "bind"
                and mount["target"] == "/evidence"
                and Path(mount["source"]).resolve() == evidence.resolve()
                and mount.get("bind", {}).get("create_host_path") is False
            ):
                raise RuntimeError(f"Unexpected mount in graded E2E service {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run graded submissions on an isolated local stack")
    parser.add_argument("--workspace", type=Path, default=ROOT.parent, help="Directory with Overmindv Git clones")
    args = parser.parse_args()
    require_local_docker()
    run_dir = Path(tempfile.mkdtemp(prefix="overmindv-graded-"))
    evidence = run_dir / "evidence"
    evidence.mkdir()
    print(f"Evidence: {evidence}", flush=True)
    refs, images = build_images(args.workspace.resolve(), run_dir)
    (evidence / "images.json").write_text(json.dumps({"sources": refs, "images": images}, indent=2), encoding="utf-8")
    env_file = run_dir / "compose.env"
    env_file.touch()
    env = {
        **os.environ,
        **images,
        **{
            f"GRADED_{key}": secrets.token_hex(24)
            for key in (
                "USERS_PASSWORD",
                "TASKS_PASSWORD",
                "JWT",
                "S3_ROOT",
                "S3_READER",
                "S3_WRITER",
                "TASK_HUNTER_TOKEN",
                "TASK_HUNTER_INGEST_TOKEN",
                "MEDIA_TOKEN",
                "MEDIA_USERS_TOKEN",
                "FEED_TOKEN",
            )
        },
        "GRADED_ADMIN_PASSWORD": "Aa9!" + secrets.token_urlsafe(24),
        "GRADED_EVIDENCE_DIR": str(evidence),
    }
    project = "ovm-graded-" + secrets.token_hex(8)
    if output("docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"):
        raise SystemExit("The generated Compose project already exists")
    compose = [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-p",
        project,
        "-f",
        str(ROOT / "ci/graded.compose.yml"),
    ]
    model = json.loads(subprocess.check_output([*compose, "--profile", "test", "config", "--format", "json"], env=env))
    validate_stack(model, evidence)
    try:
        return subprocess.run([*compose, "run", "--build", "--rm", "-T", "test"], env=env).returncode
    finally:
        subprocess.run([*compose, "stop"], check=True, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
