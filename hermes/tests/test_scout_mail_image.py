"""SCOUT-MAIL-01 — the plugin inside the real Hermes v0.22.5 image (``--network none``; skipped when absent).

Proves on Hermes' own code, in one process serving three homes like the multiplexed gateway:
- the plugin loads for Scout only (Nora/default and Kaféine/cafe-ia see no command and no hook);
- it adds no tool and no toolset to the global registry;
- 400 concurrent pre_tool_call decisions across the three homes: a tainted Scout session is always blocked,
  every other (profile, session) pair is never blocked (no capability leaks either way);
- the command fails closed without credential, for a stranger and in a group, and writes no session history.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROLE = Path(__file__).resolve().parents[1] / "ansible/roles/hermes_agent"
PLUGIN = ROLE / "files/plugins/scout_mail"
LAB = Path(__file__).parent / "fixtures/scout_mail/image_lab.py"
IMAGE = "{}:{}".format(yaml.safe_load((ROLE / "defaults/main.yml").read_text())["hermes_image"], "v0.22.5")
SETTINGS = {"enabled": True, "profile": "job-search", "inbox_id": "lab-scout@agentmail.to", "owner_user_ids": ["111"]}


@pytest.fixture(scope="module")
def lab(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    docker = shutil.which("docker")
    if not docker or subprocess.run([docker, "image", "inspect", IMAGE], capture_output=True, check=False).returncode:
        pytest.skip(f"{IMAGE} not available locally")
    work = tmp_path_factory.mktemp("scout_mail")
    (work / "settings.json").write_text(json.dumps(SETTINGS))
    script = (
        "set -e; hermes profile create job-search --no-alias >/dev/null; "
        "hermes profile create cafe-ia --no-alias >/dev/null; "
        "mkdir -p /tmp/data/profiles/job-search/plugins; "
        "cp -r /plugin /tmp/data/profiles/job-search/plugins/scout_mail; "
        "cp /lab/settings.json /tmp/data/profiles/job-search/plugins/scout_mail/settings.json; "
        "hermes -p job-search config set plugins.enabled '[\"scout_mail\"]' >/dev/null; "
        "python3 /lab/image_lab.py"
    )
    result = subprocess.run(
        [docker, "run", "--rm", "--network", "none", "-u", "10000", "-w", "/opt/hermes", "-e", "HERMES_HOME=/tmp/data",
         "-v", f"{PLUGIN}:/plugin:ro", "-v", f"{LAB}:/lab/image_lab.py:ro",
         "-v", f"{work / 'settings.json'}:/lab/settings.json:ro", "--entrypoint", "sh", IMAGE, "-c", script],
        capture_output=True, text=True, timeout=600, check=False,
    )
    line = next((x for x in result.stdout.splitlines() if x.startswith("LAB ")), None)
    assert line, result.stdout[-2000:] + result.stderr[-2000:]
    return json.loads(line[4:])


def test_i01_plugin_loads_for_scout_only(lab: dict[str, Any]) -> None:
    d = lab["discovery"]
    assert d["job-search"]["commands"] == ["courriels"] and d["job-search"]["scout_plugins"] == {"scout_mail": True}
    assert d["job-search"]["hooks"] == ["pre_gateway_dispatch", "pre_llm_call", "pre_tool_call", "transform_tool_result"]
    for other in ("default", "cafe-ia"):
        assert d[other] == {"commands": [], "scout_plugins": {}, "hooks": []}


def test_i02_no_tool_added_to_the_global_registry(lab: dict[str, Any]) -> None:
    assert lab["toolsets_added"] == [] and lab["scout_tool_entries"] == []


def test_c8_06_concurrent_multi_profile_decisions_never_leak(lab: dict[str, Any]) -> None:
    c = lab["concurrency"]
    assert c["decisions"] == 400 and c["under_blocked"] == 0 and c["over_blocked"] == 0
    assert c["scout_tainted_blocked"] == "block"
    assert c["nora_same_session"] is None and c["cafe_same_session"] is None and c["scout_clean"] is None


def test_c8_07_command_absent_elsewhere_and_fail_closed_in_scout(lab: dict[str, Any]) -> None:
    cmd = lab["command"]
    assert cmd["default"] is None and cmd["cafe-ia"] is None
    assert cmd["job-search"].startswith("Accès à la boîte refusé")
    assert lab["stranger"].startswith("Cette commande n'est disponible") and lab["group"] == lab["stranger"]


def test_c5_07_command_writes_no_session_history_and_ledger_is_private(lab: dict[str, Any]) -> None:
    assert lab["history_unchanged"] is True
    assert lab["ledger_mode"] == "0o600" and lab["ledger_has_marker_text"] is False
