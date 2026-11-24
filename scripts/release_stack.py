"""Start the release E2E stack from published images, without service checkouts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
NAME = re.compile(r"[a-z][a-z0-9-]*")
CANDIDATE_REGISTRY = "ghcr.io/overmindv/rc"
IMAGE_SOURCE_ALIASES = {"gojudge": "sandbox", "media-renderer": "media"}
UPSTREAM = {
    "kafka": "apache/kafka",
    "postgres": "postgres",
    "minio": "cgr.dev/chainguard/minio",
    "clamav": "clamav/clamav",
}
COMPOSE_ACTIONS = {"config", "pull", "up", "down", "ps"}
ALIASES = {"kafka-topics": "kafka", "media-buckets": "minio"}
GOJUDGE_SERVICES = {"gojudge", "gojudge-compiler"}
KAFKA_TOPICS_SCRIPT = Path("scripts/kafka/topics.sh")
KAFKA_TOPICS_TARGET = "/opt/overmind/kafka/topics.sh"
PORTS = {"frontend": ("FRONTEND_PORT", 3000), "api-gateway": ("API_GATEWAY_PORT", 8081)}
REQUIRED = {"sandbox", "gojudge", "feed", *PORTS}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def unique(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate release manifest key")
        obj[key] = value
    return obj


@dataclass(frozen=True)
class Release:
    registry: str
    sources: dict
    images: dict
    image_sources: dict
    upstream: dict
    plan_sha: str
    manifest_sha: str

    def role(self, service):
        if service in GOJUDGE_SERVICES:
            return "gojudge"
        if service in self.images or service in self.upstream:
            return service
        if service in ALIASES:
            return ALIASES[service]
        if service.endswith("-postgres"):
            return "postgres"
        if service.endswith("-migrate") and service.removesuffix("-migrate") in self.images:
            return service.removesuffix("-migrate")
        raise ValueError(f"{service}: missing release image mapping")

    def reference(self, service):
        role = self.role(service)
        return self.images[role] if role in self.images else self.upstream[role]

    def labels(self, service):
        role = self.role(service)
        if role not in self.image_sources:
            return {}
        repo = self.image_sources[role]
        source = f"https://github.com/overmindv/{repo}"
        labels = {
            "org.opencontainers.image.source": source,
            "org.opencontainers.image.revision": self.sources[repo],
            "io.overmindv.release.plan": self.plan_sha,
            "io.overmindv.release.service": role,
        }
        if self.registry == CANDIDATE_REGISTRY:
            labels["org.opencontainers.image.source"] = "https://github.com/overmindv/docs"
            labels["io.overmindv.release.source"] = source
        return labels


def validate_manifest(manifest, registry):
    plan, images = manifest["plan"], manifest["images"]
    if plan["version"] != 1 or plan["platform"] != "linux/amd64":
        raise ValueError("expected a v1 linux/amd64 release")
    if plan["registry"] != registry:
        raise ValueError("unexpected release registry")
    if images.keys() != plan["images"].keys() or not REQUIRED <= images.keys():
        raise ValueError("manifest is missing published service images")
    sources, upstream = plan["sources"], plan["upstream"]
    image_sources = {}
    for service, ref in images.items():
        repo, _, digest = ref.partition("@")
        if (
            service == "gojudge-compiler"
            or not NAME.fullmatch(service)
            or repo != f"{registry}/{service}"
            or not DIGEST.fullmatch(digest)
        ):
            raise ValueError("service image must use the expected repository and manifest digest")
        image_sources[service] = plan["images"][service]["source"]
        if image_sources[service] != IMAGE_SOURCE_ALIASES.get(service, service):
            raise ValueError(f"{service}: unexpected source repository")
    if sources.keys() != {"infra", *image_sources.values()} or any(
        not NAME.fullmatch(name) or not SHA.fullmatch(sha) for name, sha in sources.items()
    ):
        raise ValueError("manifest sources must contain full SHAs for all release repositories")
    if upstream.keys() != UPSTREAM.keys() or images.keys() & upstream.keys():
        raise ValueError("unexpected upstream image set")
    for role, repo in UPSTREAM.items():
        name, _, digest = upstream[role].partition("@")
        if name != repo or not DIGEST.fullmatch(digest):
            raise ValueError(f"{role}: expected upstream image digest")
    return Release(registry, sources, images, image_sources, upstream, fingerprint(plan), fingerprint(manifest))


def command(argv, cwd=None, timeout=60):
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        # Compose can include interpolated credentials in its diagnostics.
        label = " ".join(argv[:2])
        if argv[:2] == ["docker", "compose"]:
            label += " " + next((arg for arg in argv if arg in COMPOSE_ACTIONS), "")
        raise ValueError(f"{label} failed with code {result.returncode}")
    return result.stdout


def prepare_env(infra, env_file):
    from dotenv import dotenv_values

    if env_file.exists():
        raise ValueError("release stack requires a fresh env file")
    command(["sh", str(infra / "scripts/prepare-env.sh"), str(env_file)], cwd=infra)
    generated = dotenv_values(env_file, interpolate=False)
    required = (
        "JWT_SECRET",
        "BOOTSTRAP_SUPERUSER_PASSWORD",
        "FEED_GATEWAY_TOKEN",
        "RECOMMENDATIONS_SERVICE_TOKEN",
        "USERS_POSTGRES_PASSWORD",
    )
    if any(not re.fullmatch(r"[a-f0-9]{64}", generated.get(key) or "") for key in required):
        raise ValueError("prepare-env did not generate release test credentials")
    label = secrets.token_hex(6)
    overrides = {
        "BOOTSTRAP_SUPERUSER_EMAIL": f"release-{label}@simulation.example.test",
        "BOOTSTRAP_SUPERUSER_USERNAME": f"release_{label}",
        "BOOTSTRAP_SUPERUSER_PASSWORD": secrets.token_hex(32),
        "SANDBOX_EXECUTOR_TYPE": "gojudge",
        "SANDBOX_FEATURE_FAKE_EXECUTOR": "false",
        "SANDBOX_FEATURE_GOJUDGE_EXECUTOR": "true",
        "MEDIA_TOOL_PLATFORM": "linux/amd64",
        "CORS_ORIGINS": "http://127.0.0.1:3000,http://localhost:3000",
        "FRONTEND_PORT": "3000",
        "API_GATEWAY_PORT": "8081",
    }
    lines = [line for line in env_file.read_text().splitlines() if line.partition("=")[0] not in overrides]
    lines.extend(f"{key}={value}" for key, value in overrides.items())
    env_file.write_text("\n".join(lines) + "\n")
    env_file.chmod(0o600)


def compose(infra, run_dir, overlay=True):
    if not re.fullmatch(r"release-ci-[0-9a-f]{12}", run_dir.name):
        raise ValueError("expected a dedicated release-ci run directory")
    args = [
        "docker",
        "compose",
        "--project-name",
        run_dir.name,
        "--env-file",
        str(run_dir / "stack.env"),
        "-f",
        str(infra / "docker-compose.yml"),
        "--profile",
        "sandbox",
        "--profile",
        "gojudge",
    ]
    if overlay:
        args.extend(["-f", str(run_dir / "locked.compose.yml")])
    return args


def config(args):
    project = args[args.index("--project-name") + 1]
    document = json.loads(command([*args, "config", "--format", "json"]))
    for section in ("networks", "volumes"):
        for key, entry in document.get(section, {}).items():
            if entry.get("external") or entry.get("name") != f"{project}_{key}":
                raise ValueError(f"Compose {section} must be private to the test project")
    if not document.get("networks", {}).get("sandbox-runtime", {}).get("internal"):
        raise ValueError("sandbox-runtime must be an internal network")
    return document["services"]


def render_overlay(services, manifest):
    if not manifest.images.keys() <= services.keys():
        raise ValueError("Compose is missing a service from the release")
    lines = ["services:"]
    for service in sorted(services):
        if not NAME.fullmatch(service):
            raise ValueError("unexpected Compose service name")
        lines.append(f"  {service}:")
        if service == "kafka-ui":
            lines.extend(["    profiles: !override [debug-only]", "    ports: !reset []"])
            continue
        lines.extend(
            [
                f"    image: {json.dumps(manifest.reference(service))}",
                "    platform: linux/amd64",
                "    build: !reset null",
                "    pull_policy: !reset null",
            ]
        )
        if service in PORTS:
            key, target = PORTS[service]
            lines.append(f'    ports: !override ["127.0.0.1:${{{key}:-{target}}}:{target}"]')
        else:
            lines.append("    ports: !reset []")
        if service == "task-hunter":
            lines.append("    volumes: !reset []")
        if service == "kafka-topics" and any(m.get("type") == "bind" for m in services[service].get("volumes", [])):
            lines.extend(
                [
                    "    volumes: !override",
                    "      - type: bind",
                    f"        source: ./{KAFKA_TOPICS_SCRIPT.as_posix()}",
                    f"        target: {KAFKA_TOPICS_TARGET}",
                    "        read_only: true",
                    "        bind:",
                    "          create_host_path: false",
                ]
            )
    return "\n".join(lines) + "\n"


def approved_bind(service, mount, infra):
    script = infra / KAFKA_TOPICS_SCRIPT
    return (
        service == "kafka-topics"
        and mount.get("source") == str(script)
        and mount.get("target") == KAFKA_TOPICS_TARGET
        and mount.get("read_only") is True
        and mount.get("bind", {}).get("create_host_path") is False
        and script.resolve() == script
        and script.is_file()
    )


def verify_config(services, release, infra):
    if "kafka-ui" in services or not release.images.keys() <= services.keys():
        raise ValueError("unexpected active Compose services")
    for name, service in services.items():
        if (
            service.get("image") != release.reference(name)
            or "build" in service
            or service.get("platform") != "linux/amd64"
        ):
            raise ValueError(f"{name}: Compose image drift")
        ports = service.get("ports", [])
        if name in PORTS:
            _, target = PORTS[name]
            if len(ports) != 1 or ports[0].get("host_ip") != "127.0.0.1" or ports[0].get("target") != target:
                raise ValueError(f"{name}: expected one loopback port")
        elif ports:
            raise ValueError(f"{name}: unexpected published port")
        if (
            service.get("network_mode") == "host"
            or service.get("pid") == "host"
            or service.get("ipc") == "host"
            or service.get("devices")
            or service.get("container_name")
            or any(
                mount.get("type") == "bind" and not approved_bind(name, mount, infra)
                for mount in service.get("volumes", [])
            )
            or (name not in GOJUDGE_SERVICES and service.get("privileged"))
        ):
            raise ValueError(f"{name}: host access is not allowed")
        if name in GOJUDGE_SERVICES and set(service.get("networks", {})) != {"sandbox-runtime"}:
            raise ValueError(f"{name}: expected only the sandbox-runtime network")
    sandbox = services["sandbox"].get("environment", {})
    if (
        sandbox.get("SANDBOX_EXECUTOR_TYPE") != "gojudge"
        or sandbox.get("SANDBOX_FEATURE_FAKE_EXECUTOR") != "false"
        or sandbox.get("SANDBOX_FEATURE_GOJUDGE_EXECUTOR") != "true"
    ):
        raise ValueError("release e2e requires the real gojudge executor")
    compiler_url = sandbox.get("SANDBOX_GOJUDGE_COMPILER_URL")
    if "gojudge-compiler" in services or compiler_url:
        if "gojudge-compiler" not in services or compiler_url != "http://gojudge-compiler:5050":
            raise ValueError("release e2e requires the configured gojudge compiler")


def inspect_images(services, release):
    actual, inspected = {}, {}
    for name, service in sorted(services.items()):
        ref = service["image"]
        if ref not in inspected:
            (inspected[ref],) = json.loads(command(["docker", "image", "inspect", ref]))
        image = inspected[ref]
        labels = image["Config"].get("Labels") or {}
        if any(labels.get(key) != value for key, value in release.labels(name).items()):
            raise ValueError(f"{name}: release image labels do not match the manifest")
        if f"{image['Os']}/{image['Architecture']}" != "linux/amd64" or not DIGEST.fullmatch(image["Id"]):
            raise ValueError(f"{name}: unexpected pulled image")
        actual[name] = {"image": ref, "id": image["Id"]}
    return actual


def verify_running(containers, expected, project):
    observed = {}
    for item in containers:
        labels, state = item["Config"]["Labels"], item["State"]
        service = labels.get("com.docker.compose.service")
        if labels.get("com.docker.compose.project") != project or service not in expected or service in observed:
            raise ValueError("unexpected container in release stack")
        if item["Image"] != expected[service]["id"]:
            raise ValueError(f"{service}: container image does not match the pulled digest")
        job = service.endswith("-migrate") or service in ALIASES
        if not (state["Status"] == "exited" and state["ExitCode"] == 0 if job else state["Running"]):
            raise ValueError(f"{service}: container did not reach the required state")
        observed[service] = {**expected[service], "state": state["Status"]}
    if expected.keys() != observed.keys():
        raise ValueError("release stack did not start every service")
    return observed


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="action", required=True)
    for name in ("infra-ref", "render", "start", "stop"):
        cmd = commands.add_parser(name)
        if name != "stop":
            cmd.add_argument("--manifest", required=True, type=Path)
            cmd.add_argument("--registry", default="ghcr.io/overmindv")
        if name != "infra-ref":
            cmd.add_argument("--infra", required=True, type=Path)
            cmd.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.action == "stop":
            if (args.run_dir / "start.requested").is_file():
                command([*compose(args.infra.resolve(), args.run_dir.resolve()), "down", "--remove-orphans"])
            return
        release = validate_manifest(json.loads(args.manifest.read_text(), object_pairs_hook=unique), args.registry)
        if args.action == "infra-ref":
            print(release.sources["infra"])
            return
        infra, run_dir = args.infra.resolve(), args.run_dir.resolve()
        if command(["git", "rev-parse", "HEAD"], cwd=infra).strip() != release.sources["infra"]:
            raise ValueError("infra checkout does not match the manifest")
        locked = compose(infra, run_dir)
        if args.action == "render":
            run_dir.mkdir(mode=0o700)
            prepare_env(infra, run_dir / "stack.env")
            overlay = render_overlay(config(compose(infra, run_dir, overlay=False)), release)
            (run_dir / "locked.compose.yml").write_text(overlay)
            verify_config(config(locked), release, infra)
            return
        services = config(locked)
        verify_config(services, release, infra)
        print("Pull release digests", flush=True)
        command([*locked, "pull"], timeout=900)
        expected = inspect_images(services, release)
        print("Start release stack without builds", flush=True)
        (run_dir / "start.requested").touch()
        command([*locked, "up", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "600"], timeout=660)
        ids = command([*locked, "ps", "--all", "--quiet"]).split()
        containers = json.loads(command(["docker", "inspect", *ids])) if ids else []
        observed = verify_running(containers, expected, run_dir.name)
        tests = command(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1]).strip()
        receipt = {
            "manifest_sha256": release.manifest_sha,
            "sources": release.sources,
            "tests_commit": tests,
            "containers": observed,
        }
        (run_dir / "observed-release.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.TimeoutExpired) as exc:
        parser.exit(2, f"release e2e: {exc}\n")


if __name__ == "__main__":
    main()
