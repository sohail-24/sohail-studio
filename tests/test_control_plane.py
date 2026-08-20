from pathlib import Path

import pytest

from core.control_plane import ControlPlane, ToolResult


def test_router_only_selects_matching_read_only_tools(tmp_path: Path):
    plane = ControlPlane(tmp_path)

    assert plane.route("What is today's date?") == "local_time"
    assert plane.route("what is todays date?") == "local_time"
    assert plane.route("show pwd") == "pwd"
    assert plane.route("what is my current directory?") == "pwd"
    assert plane.route("show files here") == "ls"
    assert plane.route("What files are in my project?") == "project_files"
    assert plane.route("What Docker containers are running?") == "docker_read"
    assert plane.route("show docker images") == "docker_read"
    assert plane.route("What branch am I on?") == "git_read"
    assert plane.route("What pods are running?") == "kubernetes_read"
    assert plane.route("Explain Docker containers") is None
    assert plane.route("What is Kubernetes?") is None
    assert plane.route("mkdir test-folder") is None
    assert plane.route("docker compose up -d") is None


def test_router_can_select_multiple_tools_for_one_message(tmp_path: Path):
    plane = ControlPlane(tmp_path)

    assert plane.routes("Check my project and tell me if Docker is being used and whether containers are running") == [
        "docker_read",
        "project_files",
    ]


@pytest.mark.asyncio
async def test_local_time_is_structured(tmp_path: Path):
    result = await ControlPlane(tmp_path).inspect("What time is it?")

    assert result is not None
    assert result.name == "local_time"
    assert set(result.payload or {}) == {"date", "time", "day", "timezone"}


@pytest.mark.asyncio
async def test_fixed_pwd_and_ls_are_workspace_scoped(tmp_path: Path):
    (tmp_path / "visible.txt").write_text("safe", encoding="utf-8")
    plane = ControlPlane(tmp_path)

    pwd_result = await plane.inspect("show pwd")
    ls_result = await plane.inspect("show files here")

    assert pwd_result is not None
    assert pwd_result.name == "pwd"
    assert pwd_result.payload["output"] == str(tmp_path)
    assert ls_result is not None
    assert ls_result.name == "ls"
    assert "visible.txt" in ls_result.payload["output"]


@pytest.mark.asyncio
async def test_project_files_stay_inside_workspace(tmp_path: Path):
    (tmp_path / "app.py").write_text("print('safe')", encoding="utf-8")
    (tmp_path / "nested").mkdir()

    result = await ControlPlane(tmp_path).inspect("What files are in my project?")

    assert result is not None
    assert "app.py" in result.payload["files"]
    assert "nested" in result.payload["directories"]


@pytest.mark.asyncio
async def test_project_search_finds_named_folder_and_dockerfile(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project = tmp_path / "sms"
    project.mkdir()
    (project / "Dockerfile").write_text("FROM python:3.14", encoding="utf-8")

    result = await ControlPlane(workspace).inspect(
        "Find my folder named sms and tell me whether it contains a Dockerfile."
    )

    assert result is not None
    assert result.payload["matches"]
    assert result.payload["matches"][0]["kind"] == "directory"
    assert result.payload["matches"][0]["contains_dockerfile"] is True


@pytest.mark.asyncio
async def test_project_search_accepts_short_folder_phrasing(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "sms").mkdir()

    result = await ControlPlane(workspace).inspect("find my sms folder")

    assert result is not None
    assert result.payload["search_name"] == "sms"


@pytest.mark.asyncio
async def test_tool_context_never_implies_write_success():
    context = ToolResult("docker_read", error="Docker is unavailable.").as_context()

    assert "Docker is unavailable" in context
    assert "write or execution action as completed" in context


def test_registered_tools_are_explicit(tmp_path: Path):
    plane = ControlPlane(tmp_path)

    assert set(plane.tools) == {
        "local_time",
        "pwd",
        "ls",
        "project_files",
        "docker_read",
        "git_read",
        "kubernetes_read",
    }
