"""M3.3.1 — web_search was missing for Néo and Kaféine: the tools the model really receives.

Cause, proven on v2026.8.18: the `browser` toolset carries `web_search`, and
`agent.disabled_toolsets` is subtracted last, so denying `browser` stripped
`web_search` while `web_extract` stayed. The fix leaves `browser` out of the
denylist (its browser_* tools stay outside the allowlist) and the `toolsets`
check of profile.yml now judges tool by tool.

The lab runs the deployed image offline and throwaway, with a fake Tavily key:
it builds a real AIAgent per platform the way the gateway does (enabled =
platform toolsets, disabled = agent.disabled_toolsets) and reads the tool names
it would send to the model. Skipped when the image is not available locally.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from typing import Any

import pytest
import yaml
from conftest import ROLE
from test_m2_cafe_ia import GROUP_VARS, SENSITIVE

sys.path.insert(0, str(ROLE / "filter_plugins"))
sys.path.insert(0, str(ROLE / "files"))

import hermes_checks as hc
import hermes_profiles as hp

PROFILES = {"tech-watch": "hermes_profile_tech_watch", "cafe-ia": "hermes_profile_cafe_ia"}
PLATFORMS = ("telegram", "api_server", "cli", "cron")
# Every tool of the allowlist (web, skills, memory, session_search, todo, clarify) on v2026.8.18.
EXPECTED_TOOLS = {
    "web_search",
    "web_extract",
    "skill_manage",
    "skill_view",
    "skills_list",
    "memory",
    "session_search",
    "todo",
    "clarify",
}
IMAGE = "{}:{}".format(
    *(yaml.safe_load((ROLE / "defaults/main.yml").read_text())[k] for k in ("hermes_image", "hermes_image_tag"))
)

LAB_DRIVER = r'''
import json, os, subprocess
PROFILES, CHECKS = json.loads(os.environ["LAB_INPUT"])
def run(*argv, **kw):
    return subprocess.run(list(argv), capture_output=True, text=True, **kw)
probe = """
import json, logging, sys
logging.disable(logging.CRITICAL)
from hermes_cli.config import load_config
from hermes_cli.tools_config import _get_platform_tools
from run_agent import AIAgent
from tools import web_tools
cfg = load_config()
disabled = cfg["agent"]["disabled_toolsets"] + sys.argv[1:]
out = {"backend": web_tools._get_backend(), "tools": {}}
for p in ("telegram", "api_server", "cli", "cron"):
    agent = AIAgent(base_url="http://127.0.0.1:9/v1", api_key="x", model="deepseek-v4-flash", platform=p,
                    quiet_mode=True, enabled_toolsets=sorted(_get_platform_tools(cfg, p)), disabled_toolsets=disabled)
    out["tools"][p] = sorted(agent.valid_tool_names)
print("PROBE " + json.dumps(out))
"""
os.makedirs("/tmp/data", exist_ok=True)
out = {}
for name, (cfg, allowed, denied) in PROFILES.items():
    res = {"create": run("hermes", "profile", "create", name, "--no-alias").returncode}
    res["set"] = {k: run("hermes", "-p", name, "config", "set", k, v).returncode for k, v in cfg.items()}
    env = dict(os.environ, HERMES_HOME="/tmp/data/profiles/" + name)
    r = run("python3", "-c", CHECKS, "toolsets", allowed, denied, "true", env=env, cwd="/opt/hermes")
    res["check"] = [r.returncode, r.stdout.strip()]
    for label, extra in (("declared", []), ("browser_denied", ["browser"])):
        r = run("python3", "-c", probe, *extra, env=env, cwd="/opt/hermes")
        line = next((x for x in r.stdout.splitlines() if x.startswith("PROBE ")), None)
        res[label] = json.loads(line.removeprefix("PROBE ")) if line else "ERROR " + r.stderr[-800:]
    # The deploy-time check must refuse the M3.3 configuration that hid web_search.
    run("hermes", "-p", name, "config", "set", "agent.disabled_toolsets", json.dumps(denied.split(",") + ["browser"]))
    r = run("python3", "-c", CHECKS, "toolsets", allowed, denied + ",browser", "true", env=env, cwd="/opt/hermes")
    res["check_browser_denied"] = [r.returncode, r.stdout.strip()]
    out[name] = res
print("LAB_RESULT " + json.dumps(out))
'''


@pytest.fixture(scope="module")
def group_vars() -> dict[str, Any]:
    """The hermes group_vars, as written."""
    return yaml.safe_load(GROUP_VARS.read_text())


@pytest.fixture(scope="module")
def lab(group_vars: dict[str, Any]) -> dict[str, Any]:
    """Apply both profiles' declared config to a throwaway, offline container of the deployed image."""
    docker = shutil.which("docker")
    if (
        not docker
        or subprocess.run([docker, "image", "inspect", IMAGE], capture_output=True, check=False).returncode != 0
    ):
        pytest.skip(f"{IMAGE} not available locally")
    profiles = {}
    for name, var in PROFILES.items():
        cfg = group_vars[var]["config"]
        profiles[name] = [
            {k: hp.hermes_config_arg(v) for k, v in cfg.items()},
            ",".join(sorted(set(cfg["platform_toolsets.telegram"]) - {"no_mcp"})),
            ",".join(cfg["agent.disabled_toolsets"]),
        ]
    result = subprocess.run(
        [docker, "run", "--rm", "-i", "--network", "none", "-u", "10000", "-w", "/tmp"]
        + ["-e", "HERMES_HOME=/tmp/data", "-e", "LAB_INPUT", "-e", "TAVILY_API_KEY=tvly-FAKE-for-tests-only"]
        + ["--entrypoint", "python3", IMAGE, "-"],
        input=LAB_DRIVER,
        env={**os.environ, "LAB_INPUT": json.dumps([profiles, (ROLE / "files/hermes_checks.py").read_text()])},
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    line = next((x for x in result.stdout.splitlines() if x.startswith("LAB_RESULT ")), None)
    assert line, result.stdout[-2000:] + result.stderr[-2000:]
    return json.loads(line.removeprefix("LAB_RESULT "))


# --- Declaration -----------------------------------------------------------------


@pytest.mark.parametrize("var", PROFILES.values())
def test_w01_browser_is_neither_allowed_nor_denied(group_vars: dict[str, Any], var: str) -> None:
    """Denying `browser` would strip web_search; allowing it would expose browser_*: it is in neither list."""
    cfg = group_vars[var]["config"]
    denied = set(cfg["agent.disabled_toolsets"])
    # cli included: without its own whitelist it falls back to Hermes' defaults, browser among them.
    for platform in PLATFORMS:
        assert cfg[f"platform_toolsets.{platform}"] == cfg["platform_toolsets.telegram"]
    assert "browser" not in cfg["platform_toolsets.telegram"]
    assert "browser" not in denied
    assert SENSITIVE - {"browser"} <= denied
    assert "web" in cfg["platform_toolsets.telegram"]
    assert cfg["web.backend"] == "tavily"


def test_w01_both_profiles_keep_the_same_matrix(group_vars: dict[str, Any]) -> None:
    """The fix is the same one-line change for Néo and Kaféine: their matrices stay identical."""
    neo, cafe = (group_vars[v]["config"] for v in PROFILES.values())
    assert neo["agent.disabled_toolsets"] == cafe["agent.disabled_toolsets"]
    assert neo["platform_toolsets.telegram"] == cafe["platform_toolsets.telegram"]


# --- Pure verdict ----------------------------------------------------------------


def test_w02_tool_errors_flags_stripped_and_extra_tools() -> None:
    """A tool hidden by a denied toolset, and a tool beyond the allowlist, are both errors."""
    assert hc.tool_errors({"telegram": set(EXPECTED_TOOLS)}, EXPECTED_TOOLS) == []
    stripped = hc.tool_errors({"telegram": EXPECTED_TOOLS - {"web_search"}}, EXPECTED_TOOLS)
    assert stripped == ["telegram: allowed tools not exposed: web_search"]
    extra = hc.tool_errors({"cli": EXPECTED_TOOLS | {"browser_navigate"}}, EXPECTED_TOOLS)
    assert extra == ["cli: tools beyond the allowlist: browser_navigate"]


# --- Real image ------------------------------------------------------------------


@pytest.mark.parametrize("name", PROFILES)
def test_w03_lab_config_applies(lab: dict[str, Any], name: str) -> None:
    """Every declared key is accepted by the real image."""
    assert lab[name]["create"] == 0
    assert all(rc == 0 for rc in lab[name]["set"].values()), lab[name]["set"]


@pytest.mark.parametrize("name", PROFILES)
@pytest.mark.parametrize("platform", PLATFORMS)
def test_w03_lab_web_search_and_web_extract_are_exposed(lab: dict[str, Any], name: str, platform: str) -> None:
    """The real agent receives web_search AND web_extract, each checked on its own, on every platform."""
    declared = lab[name]["declared"]
    assert not isinstance(declared, str), declared
    tools = set(declared["tools"][platform])
    assert "web_search" in tools
    assert "web_extract" in tools


@pytest.mark.parametrize("name", PROFILES)
def test_w03_lab_exactly_the_allowlist_on_every_platform(lab: dict[str, Any], name: str) -> None:
    """Same tools on Telegram, API, CLI and cron: the allowlist, and no browser_*, terminal, file or code tool."""
    tools = lab[name]["declared"]["tools"]
    for platform in PLATFORMS:
        assert set(tools[platform]) == EXPECTED_TOOLS, platform
        assert not [t for t in tools[platform] if t.startswith("browser_")]
        assert not {"terminal", "process", "read_file", "write_file", "patch", "execute_code", "cronjob"} & set(
            tools[platform]
        )


@pytest.mark.parametrize("name", PROFILES)
def test_w03_lab_tavily_is_the_selected_backend(lab: dict[str, Any], name: str) -> None:
    """web.backend resolves to Tavily in the profile."""
    assert lab[name]["declared"]["backend"] == "tavily"


@pytest.mark.parametrize("name", PROFILES)
def test_w04_lab_cause_denying_browser_strips_web_search_only(lab: dict[str, Any], name: str) -> None:
    """The root cause, reproduced: with `browser` denied, web_search goes and web_extract stays."""
    tools = lab[name]["browser_denied"]["tools"]
    for platform in PLATFORMS:
        assert "web_search" not in tools[platform]
        assert "web_extract" in tools[platform]


@pytest.mark.parametrize("name", PROFILES)
def test_w05_lab_deploy_check_passes_tool_by_tool(lab: dict[str, Any], name: str) -> None:
    """The profile.yml check (same script, same arguments) passes and names the exposed tools."""
    rc, out = lab[name]["check"]
    assert rc == 0, out
    toolsets, tools = out.removeprefix("toolsets restricted to: ").split(" | tools: ")
    assert set(toolsets.split(", ")) == {"web", "skills", "memory", "session_search", "todo", "clarify"}
    assert tools.split(", ") == sorted(EXPECTED_TOOLS)


@pytest.mark.parametrize("name", PROFILES)
def test_w05_lab_deploy_check_refuses_the_m33_configuration(lab: dict[str, Any], name: str) -> None:
    """The check now stops a deploy that would hide web_search again (it passed in M3.3)."""
    rc, out = lab[name]["check_browser_denied"]
    assert rc == 1
    assert "allowed tools not exposed: web_search" in out
