"""Release checks run without a registry or a shared test account."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import release_stack as stack
from src.api.gateway import Gateway
from src.configuration import config

DIGEST = "sha256:" + "a" * 64
REGISTRY = "ghcr.io/overmindv"
PROJECT = "release-ci-aabbccddeeff"
INFRA = Path("infra").resolve()
CODE_SERVICES = ("api-gateway", "frontend", "feed", "gojudge", "sandbox")


def candidate(registry=REGISTRY):
    repos = {name: ("sandbox" if name == "gojudge" else name) for name in CODE_SERVICES}
    return {
        "plan": {
            "version": 1,
            "registry": registry,
            "platform": "linux/amd64",
            "sources": dict.fromkeys({"infra", *repos.values()}, "1" * 40),
            "images": {name: {"source": repo} for name, repo in repos.items()},
            "upstream": {role: f"{name}@{DIGEST}" for role, name in stack.UPSTREAM.items()},
        },
        "images": {name: f"{registry}/{name}@{DIGEST}" for name in CODE_SERVICES},
    }


def services(release):
    services = {
        name: {"image": release.reference(name), "platform": "linux/amd64"}
        for name in (*CODE_SERVICES, "gojudge-compiler", "kafka", "kafka-topics", "feed-migrate", "feed-postgres")
    }
    for name, (_, port) in stack.PORTS.items():
        services[name]["ports"] = [{"host_ip": "127.0.0.1", "target": port}]
    services["sandbox"]["environment"] = {
        "SANDBOX_EXECUTOR_TYPE": "gojudge",
        "SANDBOX_FEATURE_FAKE_EXECUTOR": "false",
        "SANDBOX_FEATURE_GOJUDGE_EXECUTOR": "true",
        "SANDBOX_GOJUDGE_COMPILER_URL": "http://gojudge-compiler:5050",
    }
    for name in stack.GOJUDGE_SERVICES:
        services[name].update(privileged=True, networks={"sandbox-runtime": None})
    return services


def test_feeds_and_migrations_use_published_images():
    release = stack.validate_manifest(candidate(), REGISTRY)
    actual = services(release)
    overlay = stack.render_overlay({**actual, "kafka-ui": {}}, release)
    assert "image: " + json.dumps(release.images["feed"]) in overlay
    assert "profiles: !override [debug-only]" in overlay
    assert "build: !reset null" in overlay
    assert release.reference("feed-migrate") == release.images["feed"]
    assert release.reference("feed-postgres") == release.upstream["postgres"]
    assert release.labels("gojudge")["org.opencontainers.image.source"].endswith("/sandbox")
    assert release.reference("gojudge-compiler") == release.images["gojudge"]
    assert release.labels("gojudge-compiler") == release.labels("gojudge")
    stack.verify_config(actual, release, INFRA)


def test_candidate_keeps_renderer_source_and_rejects_regular_registry():
    registry = "ghcr.io/overmindv/rc"
    manifest = candidate(registry)
    plan = manifest["plan"]
    plan["images"].update({"media": {"source": "media"}, "media-renderer": {"source": "media"}})
    plan["sources"]["media"] = "2" * 40
    for role in ("media", "media-renderer"):
        manifest["images"][role] = f"{registry}/{role}@{DIGEST}"
    release = stack.validate_manifest(manifest, registry)
    assert release.reference("media-renderer") == manifest["images"]["media-renderer"]
    assert release.labels("media-renderer") == {
        "org.opencontainers.image.source": "https://github.com/overmindv/docs",
        "org.opencontainers.image.revision": "2" * 40,
        "io.overmindv.release.source": "https://github.com/overmindv/media",
        "io.overmindv.release.plan": release.plan_sha,
        "io.overmindv.release.service": "media-renderer",
    }
    with pytest.raises(ValueError, match="unexpected release registry"):
        stack.validate_manifest(manifest, REGISTRY)
    plan["images"]["media-renderer"]["source"] = "media-renderer"
    with pytest.raises(ValueError, match="unexpected source repository"):
        stack.validate_manifest(manifest, registry)


@pytest.mark.parametrize("bad_ref", ["ghcr.io/overmindv/feed:latest", f"example.test/feed@{DIGEST}", DIGEST])
def test_rejects_tag_or_wrong_repository(bad_ref):
    manifest = candidate()
    manifest["images"]["feed"] = bad_ref
    with pytest.raises(ValueError, match="expected repository"):
        stack.validate_manifest(manifest, REGISTRY)


@pytest.mark.parametrize(
    "extra, reason",
    [
        ({"build": {}}, "image drift"),
        ({"ports": [{"host_ip": "0.0.0.0", "target": 8080}]}, "unexpected published port"),
        ({"volumes": [{"type": "bind", "source": "/workspace"}]}, "host access"),
        ({"privileged": True}, "host access"),
    ],
)
def test_rejects_unsafe_resolved_compose(extra, reason):
    release = stack.validate_manifest(candidate(), REGISTRY)
    actual = services(release)
    actual["feed"].update(extra)
    with pytest.raises(ValueError, match=reason):
        stack.verify_config(actual, release, INFRA)


def test_resolved_fake_executor_is_rejected():
    release = stack.validate_manifest(candidate(), REGISTRY)
    actual = services(release)
    actual["sandbox"]["environment"]["SANDBOX_EXECUTOR_TYPE"] = "fake"
    with pytest.raises(ValueError, match="real gojudge"):
        stack.verify_config(actual, release, INFRA)


def test_compiler_cannot_be_omitted_when_configured():
    release = stack.validate_manifest(candidate(), REGISTRY)
    actual = services(release)
    del actual["gojudge-compiler"]
    with pytest.raises(ValueError, match="configured gojudge compiler"):
        stack.verify_config(actual, release, INFRA)
    del actual["sandbox"]["environment"]["SANDBOX_GOJUDGE_COMPILER_URL"]
    stack.verify_config(actual, release, INFRA)


def test_compiler_cannot_join_a_second_network():
    release = stack.validate_manifest(candidate(), REGISTRY)
    actual = services(release)
    actual["gojudge-compiler"]["networks"]["default"] = None
    with pytest.raises(ValueError, match="only the sandbox-runtime network"):
        stack.verify_config(actual, release, INFRA)


def test_kafka_topics_can_only_mount_the_checked_out_script(tmp_path):
    release = stack.validate_manifest(candidate(), REGISTRY)
    actual = services(release)
    script = tmp_path / stack.KAFKA_TOPICS_SCRIPT
    script.parent.mkdir(parents=True)
    script.touch()
    mount = {
        "type": "bind",
        "source": str(script),
        "target": stack.KAFKA_TOPICS_TARGET,
        "read_only": True,
        "bind": {"create_host_path": False},
    }
    actual["kafka-topics"]["volumes"] = [mount]
    overlay = stack.render_overlay(actual, release)
    assert "source: ./scripts/kafka/topics.sh" in overlay
    stack.verify_config(actual, release, tmp_path)
    for change in ({"read_only": False}, {"source": str(script.parent)}, {"target": "/etc/topics.sh"}):
        actual["kafka-topics"]["volumes"] = [{**mount, **change}]
        with pytest.raises(ValueError, match="host access"):
            stack.verify_config(actual, release, tmp_path)


def test_compiler_cannot_use_a_separate_release_image():
    manifest = candidate()
    manifest["plan"]["images"]["gojudge-compiler"] = {"source": "sandbox"}
    manifest["images"]["gojudge-compiler"] = f"{REGISTRY}/gojudge-compiler@{DIGEST}"
    with pytest.raises(ValueError, match="expected repository"):
        stack.validate_manifest(manifest, REGISTRY)


def test_executor_network_must_be_internal(monkeypatch):
    monkeypatch.setattr(
        stack,
        "command",
        Mock(
            return_value=json.dumps(
                {
                    "services": {},
                    "networks": {"sandbox-runtime": {"name": f"{PROJECT}_sandbox-runtime"}},
                }
            )
        ),
    )
    with pytest.raises(ValueError, match="must be an internal network"):
        stack.config(["docker", "compose", "--project-name", PROJECT])


def test_existing_external_volume_is_rejected(monkeypatch):
    command = Mock(
        return_value=json.dumps(
            {
                "services": {},
                "volumes": {"db": {"name": "shared_db", "external": True}},
            }
        )
    )
    monkeypatch.setattr(stack, "command", command)
    with pytest.raises(ValueError, match="private to the test project"):
        stack.config(["docker", "compose", "--project-name", PROJECT])


def test_prepare_failure_does_not_fall_back_to_an_existing_env(tmp_path, monkeypatch):
    env_file = tmp_path / "stack.env"
    command = Mock(side_effect=ValueError("sh failed"))
    monkeypatch.setattr(stack, "command", command)
    with pytest.raises(ValueError, match="sh failed"):
        stack.prepare_env(tmp_path, env_file)
    assert not env_file.exists()
    env_file.touch()
    with pytest.raises(ValueError, match="fresh env"):
        stack.prepare_env(tmp_path, env_file)
    assert command.call_count == 1


def test_running_image_drift_and_missing_migration_are_rejected():
    expected = {
        "feed": {"image": f"{REGISTRY}/feed@{DIGEST}", "id": DIGEST},
        "feed-migrate": {"image": f"{REGISTRY}/feed@{DIGEST}", "id": DIGEST},
        "gojudge-compiler": {"image": f"{REGISTRY}/gojudge@{DIGEST}", "id": DIGEST},
    }

    def container(service, running):
        return {
            "Image": DIGEST,
            "Config": {"Labels": {"com.docker.compose.project": PROJECT, "com.docker.compose.service": service}},
            "State": {"Running": running, "Status": "running" if running else "exited", "ExitCode": 0},
        }

    instances = [container("feed", True), container("feed-migrate", False), container("gojudge-compiler", True)]
    assert stack.verify_running(instances, expected, PROJECT)["feed-migrate"]["state"] == "exited"
    with pytest.raises(ValueError, match="every service"):
        stack.verify_running(instances[:2], expected, PROJECT)
    instances[0]["Image"] = "sha256:" + "b" * 64
    with pytest.raises(ValueError, match="does not match"):
        stack.verify_running(instances, expected, PROJECT)


def test_bootstrap_login_never_uses_a_default_password(monkeypatch):
    gateway = Gateway.__new__(Gateway)
    gateway.login = Mock()
    monkeypatch.setattr(config, "BOOTSTRAP_SUPERUSER_EMAIL", "test@example.invalid")
    monkeypatch.setattr(config, "BOOTSTRAP_SUPERUSER_PASSWORD", None)
    with pytest.raises(ValueError, match="BOOTSTRAP_SUPERUSER_PASSWORD"):
        gateway.login_bootstrap_superuser()
    gateway.login.assert_not_called()
