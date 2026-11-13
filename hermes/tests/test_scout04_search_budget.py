"""SCOUT-04 — Scout's search consumption: what the declaration changes, checked offline and in the real image.

Baseline (hermes-31, 2026-11-13, private trace): one bounded search = 18 model calls, 669,431 cumulative prompt
tokens (the sum over calls, `agent/turn_usage.py`), then a background skill review of 3 more calls (~205k input).
Kandidat's list tools return 73-92k chars, above Hermes' 50k MCP spill threshold, so the model only sees a preview.

Offline: the declaration (skill review off for Scout only, SOUL predecessors) and the SOUL rules.
Lab (real Hermes v0.22.5 image, `--network none`, skipped when absent): the key reaches the agent the way Hermes
reads it, and the MCP spill threshold and preview size Scout's rules rely on.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import REPO, ROLE
from test_m2_cafe_ia import GROUP_VARS

sys.path.insert(0, str(ROLE / "filter_plugins"))

import hermes_profiles as hp

SOUL = ROLE / "files/profiles/job-search/SOUL.md"
IMAGE = "{}:{}".format(yaml.safe_load((ROLE / "defaults/main.yml").read_text())["hermes_image"], "v0.22.5")
M43_SOUL = "f712d3359f8a9bcb3a1eb4481435d11e5c17c31cabac9c61e6ca3f4e3f0382fa"
SCOUT03_SOUL = "777470b3fcaced3a4f7e7322e30aed238bc61907bb56d8b4eb16d2c0ab5b2fc1"


@pytest.fixture(scope="module")
def group_vars() -> dict[str, Any]:
    """The hermes group_vars, as written."""
    return yaml.safe_load(GROUP_VARS.read_text())


def test_b01_skill_review_off_for_scout_only(group_vars: dict[str, Any]) -> None:
    """Scout: no background skill review; Nora and Kaféine keep Hermes' default."""
    assert group_vars["hermes_profile_job_search"]["config"]["skills.creation_nudge_interval"] == 0
    for name in ("hermes_profile_cafe_ia", "hermes_default_nora"):
        assert "skills.creation_nudge_interval" not in group_vars[name]["config"], name


def test_b01_scout_permissions_unchanged(group_vars: dict[str, Any]) -> None:
    """SCOUT-04 touches no MCP entry, toolset list or tool budget."""
    cfg = group_vars["hermes_profile_job_search"]["config"]
    assert set(cfg["mcp_servers.kandidat"]["tools"]["include"]) == {
        "list_cibles", "get_cible_detail", "list_candidatures", "get_candidature", "get_candidature_history",
        "search_candidatures", "get_stats",
    }
    assert set(cfg["mcp_servers.kandidat_confirm"]["tools"]["include"]) == {
        "create_candidature", "create_cible", "update_candidature", "update_cible",
    }
    assert cfg["mcp_servers.kandidat_confirm"]["trust"] == "untrusted"
    assert cfg["platform_toolsets.cron"][-1] == "kandidat" and "kandidat_confirm" not in cfg["platform_toolsets.cron"]
    assert not [k for k in cfg if k.startswith("tool_budget") or (k.startswith("web.") and k != "web.backend")]


def test_b02_soul_predecessors_are_the_two_deployed_versions(group_vars: dict[str, Any]) -> None:
    """The guard replaces the M4.3 or the SCOUT-03 SOUL (35d693d, live on hermes-31 on 2026-11-13), nothing else."""
    assert group_vars["hermes_profile_job_search"]["soul_predecessor_sha256"] == [M43_SOUL, SCOUT03_SOUL]
    previous = subprocess.run(
        ["git", "show", "35d693d:hermes/ansible/roles/hermes_agent/files/profiles/job-search/SOUL.md"],
        cwd=REPO, capture_output=True, check=False,
    )
    if previous.returncode == 0:
        assert hashlib.sha256(previous.stdout).hexdigest() == SCOUT03_SOUL
    assert hashlib.sha256(SOUL.read_bytes()).hexdigest() not in (M43_SOUL, SCOUT03_SOUL)


@pytest.mark.parametrize(
    "rule",
    [
        "du plus précis au plus large, et arrête-toi dès qu'elle est trouvée",
        "`get_candidature` avec le slug probable",
        "ne cherche que dans le texte des fiches et respecte la casse",
        "un résultat vide ne prouve pas l'absence",
        "au plus une fois par demande",
        "« présence dans Kandidat non vérifiable », jamais « absente de Kandidat »",
        "reste valable jusqu'à ta prochaine écriture",
        "**Recherche bornée**",
        "dis ce qui n'a pas été couvert",
        "Ne relance pas une requête presque identique",
        "`char_limit` 5000",
        "n'est pas retentée",
        # SCOUT-03 rules the bound must not displace.
        "sans paramètres de suivi",
        "Deux offres de la même entreprise restent deux offres",
        "Une date absente ne prouve pas que l'offre est close",
        "présence physique programmée et récurrente hors de Guadeloupe",
    ],
)
def test_b03_soul_rules(rule: str) -> None:
    """The lookup protocol and the research bound are in Scout's SOUL.md, next to the rules they must keep."""
    assert rule in SOUL.read_text()


def test_b03_soul_stays_compact() -> None:
    """SOUL.md is re-sent with every model call: the SCOUT-04 rules add at most ~1.6k chars to SCOUT-03's."""
    assert len(SOUL.read_text()) <= 13800


LAB = r'''
import json, logging
from types import SimpleNamespace
logging.disable(logging.CRITICAL)
from hermes_cli.config import load_config_readonly
from agent.agent_init import _apply_agent_section
from tools.budget_config import DEFAULT_BUDGET, DEFAULT_PREVIEW_SIZE_CHARS
from tools.tool_result_storage import maybe_persist_tool_result
cfg = load_config_readonly()
agent = SimpleNamespace()
try:  # sets _skill_nudge_interval first, then needs a real agent for the rest of the section
    _apply_agent_section(agent, cfg)
except AttributeError:
    pass
big = json.dumps({"data": [{"id": i, "nom": "Entreprise %03d" % i, "notes": "x" * 700} for i in range(122)]}, indent=2)
shown = maybe_persist_tool_result(big, "mcp__kandidat__list_cibles", "call_lab")
print("LAB " + json.dumps({
    "nudge": agent._skill_nudge_interval,
    "threshold": DEFAULT_BUDGET.resolve_threshold("mcp__kandidat__list_cibles"),
    "preview": DEFAULT_PREVIEW_SIZE_CHARS,
    "big": len(big), "shown": len(shown), "last_company_visible": "Entreprise 121" in shown,
    "persisted": "persisted-output" in shown,
}))
'''


@pytest.fixture(scope="module")
def lab(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Two throwaway profiles in the real image: Scout's key set, and a control left at Hermes' default."""
    docker = shutil.which("docker")
    if not docker or subprocess.run([docker, "image", "inspect", IMAGE], capture_output=True, check=False).returncode:
        pytest.skip(f"{IMAGE} not available locally")
    work = tmp_path_factory.mktemp("scout04")
    (work / "lab.py").write_text(LAB)
    value = hp.hermes_config_arg(0)
    script = (
        "set -e; hermes profile create job-search --no-alias >/dev/null; "
        "hermes profile create control --no-alias >/dev/null; "
        f"hermes -p job-search config set skills.creation_nudge_interval {value} >/dev/null; "
        "for p in job-search control; do HERMES_HOME=/tmp/data/profiles/$p python3 /lab/lab.py | sed \"s/^LAB /$p /\"; done"
    )
    result = subprocess.run(
        [docker, "run", "--rm", "--network", "none", "-u", "10000", "-w", "/opt/hermes", "-e", "HERMES_HOME=/tmp/data",
         "-v", f"{work / 'lab.py'}:/lab/lab.py:ro", "--entrypoint", "sh", IMAGE, "-c", script],
        capture_output=True, text=True, timeout=600, check=False,
    )
    out = {}
    for line in result.stdout.splitlines():
        name, _, payload = line.partition(" ")
        if name in ("job-search", "control") and payload.startswith("{"):
            out[name] = json.loads(payload)
    assert set(out) == {"job-search", "control"}, result.stdout[-2000:] + result.stderr[-2000:]
    return out


def test_l01_skill_review_cannot_trigger_for_scout(lab: dict[str, Any]) -> None:
    """Hermes reads the key into the agent: 0 for Scout (turn_finalizer requires > 0), 10 by default."""
    assert lab["job-search"]["nudge"] == 0
    assert lab["control"]["nudge"] == 10


def test_l02_kandidat_lists_are_cut_to_a_preview(lab: dict[str, Any]) -> None:
    """Why the SOUL forbids "absente de Kandidat" from a list: above 50k chars an MCP result is persisted to a file
    and the model gets a ~1.5k preview; Scout has no file tool to page through it."""
    seen = lab["job-search"]
    assert seen["threshold"] == 50_000 and seen["preview"] == 1_500
    assert seen["big"] > 80_000 and seen["persisted"] is True
    assert seen["shown"] < 4_000 and seen["last_company_visible"] is False
