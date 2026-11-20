"""Release checks run without a registry or a shared test account."""

import json
from unittest.mock import Mock

import pytest

from scripts import release_stack as stack
from src.api.gateway import Gateway
from src.configuration import config

DIGEST = "sha256:" + "a" * 64
REGISTRY = "ghcr.io/overmindv"
PROJECT = "release-ci-aabbccddeeff"
CODE_SERVICES = ("api-gateway", "frontend", "feed", "gojudge", "sandbox")


def candidate():
    repos = {name: ("sandbox" if name == "gojudge" else name) for name in CODE_SERVICES}
    return {
        "plan": {
            "version": 1,
            "registry": REGISTRY,
            "platform": "linux/amd64",
            "sources": dict.fromkeys({"infra", *repos.values()}, "1" * 40),
            "images": {name: {"source": repo} for name, repo in repos.items()},
            "upstream": {role: f"{name}@{DIGEST}" for role, name in stack.UPSTREAM.items()},
        },
        "images": {name: f"{REGISTRY}/{name}@{DIGEST}" for name in CODE_SERVICES},
    }


def services(release):
    services = {
        name: {"image": release.reference(name), "platform": "linux/amd64"}
        for name in (*CODE_SERVICES, "kafka", "kafka-topics", "feed-migrate", "feed-postgres")
    }
    for name, (_, port) in stack.PORTS.items():
        services[name]["ports"] = [{"host_ip": "127.0.0.1", "target": port}]
    services["sandbox"]["environment"] = {
        "SANDBOX_EXECUTOR_TYPE": "gojudge",
        "SANDBOX_FEATURE_FAKE_EXECUTOR": "false",
        "SANDBOX_FEATURE_GOJUDGE_EXECUTOR": "true",
    }
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
    stack.verify_config(actual, release)


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
        stack.verify_config(actual, release)


def test_resolved_fake_executor_is_rejected():
    release = stack.validate_manifest(candidate(), REGISTRY)
    actual = services(release)
    actual["sandbox"]["environment"]["SANDBOX_EXECUTOR_TYPE"] = "fake"
    with pytest.raises(ValueError, match="real gojudge"):
        stack.verify_config(actual, release)


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
    }

    def container(service, running):
        return {
            "Image": DIGEST,
            "Config": {"Labels": {"com.docker.compose.project": PROJECT, "com.docker.compose.service": service}},
            "State": {"Running": running, "Status": "running" if running else "exited", "ExitCode": 0},
        }

    instances = [container("feed", True), container("feed-migrate", False)]
    assert stack.verify_running(instances, expected, PROJECT)["feed-migrate"]["state"] == "exited"
    with pytest.raises(ValueError, match="every service"):
        stack.verify_running(instances[:1], expected, PROJECT)
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
