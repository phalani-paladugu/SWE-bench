from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from swebench.cli.cli import app
from swebench.image_builder import docker_build, prepare_images
from swebench.image_builder.image_spec import make_image_spec


@pytest.mark.parametrize(
    "options,arch,name_arch,platform",
    [
        ([], "amd64", "x86_64", "linux/amd64"),
        (["--arch", "amd64"], "amd64", "x86_64", "linux/amd64"),
        (["--arch", "arm64"], "arm64", "arm64", "linux/arm64/v8"),
    ],
)
def test_cli_architecture_reaches_image_builder(
    monkeypatch, tmp_path, options, arch, name_arch, platform
):
    instance_id = "example__repo-1"
    dockerfile = f"FROM --platform=linux/{arch} ubuntu:22.04\n"
    monkeypatch.setattr(prepare_images.resource, "setrlimit", Mock())
    monkeypatch.setattr(prepare_images.docker, "from_env", Mock())
    monkeypatch.setattr(prepare_images, "guard", Mock())
    monkeypatch.setattr(
        prepare_images,
        "select_tasks",
        Mock(return_value=[{"instance_id": instance_id}]),
    )
    monkeypatch.setattr(
        prepare_images, "load_dockerfiles", Mock(return_value={instance_id: dockerfile})
    )
    # An existing AMD64 image must not cause an ARM64 build to be skipped.
    existing = {f"sweb.eval.x86_64.{instance_id}:latest"} if arch == "arm64" else set()
    monkeypatch.setattr(prepare_images, "list_images", Mock(return_value=existing))
    build = Mock(return_value=([instance_id], []))
    monkeypatch.setattr(prepare_images, "build_instance_images", build)

    result = CliRunner().invoke(
        app, ["images", "build", str(tmp_path), "-i", instance_id, *options]
    )

    assert result.exit_code == 0, result.output
    build.assert_called_once()
    spec = build.call_args.kwargs["image_specs"][0]
    assert spec.arch == arch
    assert spec.name == f"sweb.eval.{name_arch}.{instance_id}:latest"
    assert spec.platform == platform
    assert spec.dockerfile == dockerfile


def test_cli_rejects_unknown_architecture_before_building(monkeypatch):
    build = Mock()
    monkeypatch.setattr(prepare_images, "main", build)
    result = CliRunner().invoke(app, ["images", "build", "tasks", "--arch", "ppc64le"])
    assert result.exit_code == 2
    build.assert_not_called()


def test_arm64_platform_and_name_reach_docker_buildx(monkeypatch, tmp_path):
    spec = make_image_spec(
        {"instance_id": "example__repo-1"},
        "FROM --platform=linux/arm64 ubuntu:22.04\n",
        namespace="example",
        tag="arm-test",
        arch="arm64",
    )
    monkeypatch.setattr(docker_build, "IMAGE_BUILDER_LOG_DIR", tmp_path)
    process = Mock(return_value=Mock(wait=Mock(return_value=0)))
    monkeypatch.setattr(docker_build.subprocess, "Popen", process)
    docker_build.build_image(spec)
    command = process.call_args.args[0]
    assert "--platform=linux/arm64/v8" in command
    assert "--tag=example/sweb.eval.arm64.example_1776_repo-1:arm-test" in command


def test_image_spec_rejects_unknown_architecture():
    with pytest.raises(ValueError, match="Must be 'amd64' or 'arm64'"):
        make_image_spec(
            {"instance_id": "example__repo-1"}, "FROM scratch", arch="other"
        )
