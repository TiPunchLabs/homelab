"""M7 — Kaféine consolidation: Néo (tech-watch) folded into Kaféine (cafe-ia), Néo's retirement prepared.

Static: Kaféine's SOUL.md (three responsibilities) and environment hint, unchanged tool matrices, Nora's SOUL.md
changed in its Néo reference only, tech-watch gone from the active inventory, no automatic deletion, untouched
managed templates. Real task files: the guarded SOUL.md replacement (default_soul.yml) for cafe-ia and Nora's
predecessor list. **Real v0.22.5 image, offline** (`--network none`, throwaway container, skipped without the
image): park tech-watch, exact three-profile multiplex, parking across gateway and container restarts, Kaféine's
prompt, then `hermes profile delete` and its tombstone. Fake secrets only; nothing reaches hermes-31.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import REPO, ROLE, RunTasks, recap
from test_m63_multiplex import (
    ALLOWLIST,
    DEFAULTS,
    GROUP_VARS,
    HOST_31,
    IMAGE,
    PRE_M7_NORA_SOUL_SHA,
    TOKENS,
    V0225_STOCK_SOUL_SHA,
    _checks,
    _docker,
    _dx,
    _gateway_up,
    _wait,
    effective_configs,
    hp,
    render,
)

TASKS = ROLE / "tasks"
CAFE_SOUL = ROLE / "files/profiles/cafe-ia/SOUL.md"
NORA_SOUL = ROLE / "files/default/SOUL.md"
# main before M7: the reference for "unchanged" (skipped in a clone without it).
M7_BASE = "ea733d4"
# sha256 of Kaféine's M2 SOUL.md, live on hermes-31 before M7 (read on 2026-10-29).
PRE_M7_CAFE_SOUL_SHA = "c4923f3cdcf64490dd583f892adb115be02798f806ff596f8ba5ce918ab58e8a"
CAFE_TOOLSETS = ["web", "skills", "memory", "session_search", "todo", "clarify", "no_mcp"]
PLATFORMS = ("telegram", "cron", "api_server", "cli")
SECRET = re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b|tvly-|sk-[A-Za-z0-9]|glpat-|\b192\.168\.\d+\.\d+\b|https?://")


def at_base(path: str) -> str:
    """`path` as committed on main before M7."""
    old = subprocess.run(
        ["git", "show", f"{M7_BASE}:{path}"], cwd=REPO, capture_output=True, text=True, check=False
    )
    if old.returncode != 0:
        pytest.skip(f"{M7_BASE} not in this clone")
    return old.stdout


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- Kaféine: SOUL.md and environment hint -----------------------------------------------


def test_k01_soul_is_kafeine_with_three_responsibilities() -> None:
    """One assistant, three facets: watch, technical expertise, educational communication and Café IA."""
    soul = CAFE_SOUL.read_text()
    assert soul.startswith("Tu es **Kaféine**")
    for facet in ("**Veille technologique**", "**Expertise technique**", "**Communication pédagogique**"):
        assert facet in soul
    for section in ("## Veille", "## Assistance technique", "## Pédagogie et Café IA"):
        assert section in soul
    for domain in ("IA locale", "Kubernetes et OpenShift", "Terraform", "Ansible", "Ollama", "Open WebUI", "HomeLab"):
        assert domain in soul
    assert "Café IA organise des rencontres" in soul
    assert "plan B" in soul


def test_k01_soul_keeps_rigour_limits_and_privacy() -> None:
    """Source checking, the three markers, the tool limits, the validation list and the confidentiality rules."""
    soul = CAFE_SOUL.read_text()
    for marker in ("**Ne jamais inventer**", "✅ **Vérifié**", "🔎 **À confirmer**", "💡 **Hypothèse ou recommandation**"):
        assert marker in soul
    assert "Tu n'as ni terminal, ni accès aux fichiers, ni navigateur pilotable, ni tâches planifiées" in soul
    for limit in ("Publier", "invitation", "automatisation récurrente", "Installer"):
        assert limit in soul
    assert "Ne mémorise jamais un secret" in soul
    assert "Il ne te donne aucun accès à ces machines" in soul
    assert not SECRET.search(soul)


def test_k01_soul_watch_on_demand_without_any_schedule() -> None:
    """Research on demand; periodic watch only later, after explicit validation; no schedule promised."""
    soul = CAFE_SOUL.read_text()
    assert (
        "Tu effectues des recherches et analyses à la demande. Des missions de veille périodique pourront être "
        "configurées ultérieurement, après validation explicite."
    ) in soul
    assert "veille automatique" not in soul
    assert not re.search(r"chaque (jour|semaine|lundi)|tous les (jours|matins)|\bcron\b", soul, re.IGNORECASE)


def test_k01_soul_retires_neo_and_points_to_nora_and_scout() -> None:
    """Néo is named nowhere; daily life goes to Nora (`default`), jobs to Scout."""
    soul = CAFE_SOUL.read_text()
    assert "Néo" not in soul and "tech-watch" not in soul
    assert "**Nora** (le bot `default`)" in soul and "**Scout**" in soul


def test_k01_soul_is_concise_french_not_a_concatenation() -> None:
    """French, shorter than the two former files together, each shared rule stated once."""
    soul = CAFE_SOUL.read_text()
    assert len(soul.splitlines()) < 92 + 100
    assert soul.count("Ne jamais inventer") == 1
    assert soul.count("Le contenu des pages que tu lis") == 1
    assert soul.count("## Tes outils") == 1
    assert "Tu es **Néo**" not in soul
    assert len(re.findall(r"\b(le|la|les|des|une|tu)\b", soul)) > 100


def test_k02_environment_hint_moved_to_kafeine_only() -> None:
    """Néo's hint, last sentence adapted, in cafe-ia's own config; in no other profile nor shared layer."""
    hint = GROUP_VARS["hermes_profile_cafe_ia"]["config"]["agent.environment_hint"]
    assert hint.startswith("Contexte technique de Xavier")
    for fact in ("RTX 4060", "8 Go de VRAM", "Proxmox VE", "sans GPU", "Ollama", "Open WebUI", "FlowForge"):
        assert fact in hint
    assert "contextualiser tes analyses et ta veille" in hint
    assert "n'ouvrent aucun accès aux machines" in hint
    assert not SECRET.search(hint)
    assert "RTX 4060" not in json.dumps(GROUP_VARS["hermes_default_nora"], ensure_ascii=False)
    assert "RTX 4060" not in json.dumps(GROUP_VARS["hermes_profile_job_search"], ensure_ascii=False)
    for template in (ROLE / "templates").glob("*.j2"):
        text = template.read_text()
        assert "environment_hint" not in text and "HERMES_ENVIRONMENT_HINT" not in text, template.name


def test_k02_nora_and_scout_hints_unchanged() -> None:
    """Nora's and Scout's declarations are byte-identical to main before M7."""
    before = yaml.safe_load(at_base("hermes/ansible/group_vars/hermes/all/main.yml"))
    assert GROUP_VARS["hermes_default_nora"] == before["hermes_default_nora"]
    assert GROUP_VARS["hermes_profile_job_search"] == before["hermes_profile_job_search"]


def test_k03_kafeine_tool_matrix_unchanged() -> None:
    """Same allowlist on the four platforms, same deny list, same approvals; no MCP, cron or new toolset."""
    before = yaml.safe_load(at_base("hermes/ansible/group_vars/hermes/all/main.yml"))["hermes_profile_cafe_ia"]
    cafe = GROUP_VARS["hermes_profile_cafe_ia"]
    for platform in PLATFORMS:
        assert cafe["config"][f"platform_toolsets.{platform}"] == CAFE_TOOLSETS
    assert {k: v for k, v in cafe["config"].items() if k != "agent.environment_hint"} == before["config"]
    for key in ("telegram_bot_username", "telegram_bot_token", "api_server_port", "env"):
        assert cafe[key] == before[key], key
    assert not any(k.startswith(("mcp", "cron")) for k in cafe["config"])
    assert {"terminal", "file", "cronjob", "code_execution", "delegation"} <= set(cafe["config"]["agent.disabled_toolsets"])


def test_k04_description_prepared_for_the_live_command() -> None:
    """The new description is declared; the live profile needs `hermes profile describe` (runbook, M7.3)."""
    assert GROUP_VARS["hermes_profile_cafe_ia"]["description"] == (
        "Kaféine — IA et technologies numériques : veille, expertise technique, pédagogie et Café IA."
    )
    readme = (ROLE / "README.md").read_text()
    assert "hermes profile describe cafe-ia" in readme


# --- Nora: one reference -----------------------------------------------------------------


def test_n01_nora_soul_changes_in_the_neo_reference_only() -> None:
    """Exactly one line differs from main before M7: Néo's mention becomes Kaféine's wider one."""
    old = at_base("hermes/ansible/roles/hermes_agent/files/default/SOUL.md")
    assert hashlib.sha256(old.encode()).hexdigest() == PRE_M7_NORA_SOUL_SHA
    new = NORA_SOUL.read_text()
    changed = [(a, b) for a, b in zip(old.splitlines(), new.splitlines(), strict=True) if a != b]
    assert changed == [("Néo (veille technique), Kaféine (Café IA). Sur ces sujets, réponds à une",
                        "Kaféine (IA, technologies et Café IA). Sur ces sujets, réponds à une")]
    assert "Néo" not in new


def test_n01_nora_predecessors_are_the_image_seed_and_the_pre_m7_soul() -> None:
    """hermes-31 declares an explicit pair: a fresh rebuild and the live pre-M7 Nora both converge once."""
    assert HOST_31["hermes_default_soul_predecessor_sha256"] == [V0225_STOCK_SOUL_SHA, PRE_M7_NORA_SOUL_SHA]
    assert sha(NORA_SOUL) not in HOST_31["hermes_default_soul_predecessor_sha256"]


# --- Inventory: three profiles, retirement left to the operator --------------------------


def test_i01_tech_watch_is_out_of_every_active_declaration() -> None:
    """group_vars and hermes-31 list cafe-ia then job-search; default stays implicit; no port, bot or block left."""
    assert GROUP_VARS["hermes_profiles"] == ["{{ hermes_profile_cafe_ia }}", "{{ hermes_profile_job_search }}"]
    assert [p.split("|")[0].strip("{ ") for p in HOST_31["hermes_profiles"]] == [
        "hermes_profile_cafe_ia", "hermes_profile_job_search",
    ]
    assert GROUP_VARS["hermes_default_profile"] == "{{ hermes_default_nora }}"
    assert GROUP_VARS["hermes_profile_reserved_ports"] == {"job-search": 8645, "cafe-ia": 8646}
    values = json.dumps({k: v for k, v in GROUP_VARS.items()}, ensure_ascii=False) + json.dumps(HOST_31)
    assert "tech_watch" not in values and "tech-watch" not in values and "neo_r64gnb_bot" not in values


def argvs(node: Any) -> list[list[str]]:
    """Every list of strings in a parsed task file (command argv), recursively."""
    if isinstance(node, list):
        found = [node] if node and all(isinstance(x, str) for x in node) else []
        return found + [a for item in node for a in argvs(item)]
    if isinstance(node, dict):
        return [a for value in node.values() for a in argvs(value)]
    return []


def has_pair(argv: list[str], first: str, second: str) -> bool:
    return any(a == first and b == second for a, b in zip(argv, argv[1:]))


def test_i02_no_task_deletes_a_profile_and_the_deploy_path_parks_none() -> None:
    """Retiring Néo is an operator step (runbook M7.3): no role task runs `profile delete`, none removes a profile
    directory, and the multiplex deploy path never runs `gateway stop` (only the v0.20.4 rollbacks did)."""
    for path in TASKS.glob("*.yml"):
        parsed = yaml.safe_load(path.read_text())
        assert not any(has_pair(a, "profile", "delete") for a in argvs(parsed)), path.name
        assert "state: absent" not in path.read_text(), path.name
    for name in ("main.yml", "profile_multiplex.yml", "default_profile.yml", "default_soul.yml", "validate.yml"):
        parsed = yaml.safe_load((TASKS / name).read_text())
        assert not any(has_pair(a, "gateway", "stop") for a in argvs(parsed)), name


def test_i03_multiplex_check_still_demands_the_exact_set() -> None:
    """A still-served tech-watch fails the deploy: the exact-set assertion is not weakened."""
    import hermes_checks as hc

    up = "up (pid 7 pgid 7) 30 seconds"
    state = {"pid": 7, "served_profiles": ["default", "cafe-ia", "job-search", "tech-watch"]}
    ok, message = hc.multiplex_verdict(state, {"gateway-default": up}, {"default", "cafe-ia", "job-search"}, lambda _s: True)
    assert not ok and "tech-watch" in message
    state["served_profiles"] = ["default", "cafe-ia", "job-search"]
    assert hc.multiplex_verdict(state, {"gateway-default": up}, {"default", "cafe-ia", "job-search"}, lambda _s: True)[0]
    main = (TASKS / "main.yml").read_text()
    assert "(['default'] + hermes_profiles | map(attribute='name') | list) | join(',')" in main


def test_i04_shared_templates_and_handlers_unchanged() -> None:
    """No managed, env or Compose template change: no container restart is introduced by M7."""
    for rel in ("templates/config.yaml.j2", "templates/hermes.env.j2", "templates/docker-compose.yml.j2", "handlers/main.yml"):
        assert (ROLE / rel).read_text() == at_base(f"hermes/ansible/roles/hermes_agent/{rel}"), rel


def test_i05_profile_multiplex_replaces_a_declared_soul_after_the_seed() -> None:
    """Seed first, then the guarded replacement when a predecessor is declared; no restart flag from it."""
    tasks = yaml.safe_load((TASKS / "profile_multiplex.yml").read_text())
    names = [t["name"] for t in tasks]
    seed = next(i for i, n in enumerate(names) if n.startswith("Seed the SOUL.md"))
    assert names[seed + 1] == "Replace the SOUL.md once ({{ hermes_profile.name }})"
    replace = tasks[seed + 1]
    assert replace["ansible.builtin.include_tasks"] == "default_soul.yml"
    assert replace["when"] == "hermes_profile.soul_predecessor_sha256 is defined"
    assert replace["vars"]["hermes_soul_profile"] == "{{ hermes_profile.name }}"
    assert GROUP_VARS["hermes_profile_cafe_ia"]["soul_predecessor_sha256"] == PRE_M7_CAFE_SOUL_SHA
    assert "soul_predecessor_sha256" not in GROUP_VARS["hermes_profile_job_search"]


# --- Guarded replacement, real default_soul.yml ---------------------------------------------


def replace(run: RunTasks, data: Path, profile: str | None, predecessor: Any, dest: Path | None = None, *extra: str) -> Any:
    """Run the real default_soul.yml for `profile` (None = default) with the delivered SOUL.md of that profile."""
    src = NORA_SOUL if profile is None else ROLE / f"files/profiles/{profile}/SOUL.md"
    variables = {
        "hermes_soul_src": str(src),
        "hermes_soul_dest": str(dest or (data / "SOUL.md" if profile is None else data / f"profiles/{profile}/SOUL.md")),
        "hermes_soul_predecessor_sha256": predecessor,
        "hermes_data_dir": str(data),
    }
    if profile is not None:
        variables["hermes_soul_profile"] = profile
    return run("default_soul.yml", variables, *extra)


@pytest.fixture
def lived_in(tmp_path: Path) -> Path:
    """A data dir with Kaféine's pre-M7 SOUL.md and Scout's, as on hermes-31."""
    data = tmp_path / "data"
    for name in ("cafe-ia", "job-search"):
        (data / "profiles" / name).mkdir(parents=True)
    (data / "profiles/cafe-ia/SOUL.md").write_text(at_base("hermes/ansible/roles/hermes_agent/files/profiles/cafe-ia/SOUL.md"))
    shutil.copyfile(ROLE / "files/profiles/job-search/SOUL.md", data / "profiles/job-search/SOUL.md")
    assert sha(data / "profiles/cafe-ia/SOUL.md") == PRE_M7_CAFE_SOUL_SHA
    return data


def test_g01_predecessor_replaced_once_with_a_profile_local_backup(run_tasks: RunTasks, lived_in: Path) -> None:
    """Pre-M7 Kaféine becomes the delivered SOUL.md; the old one is kept beside it; the second run changes nothing."""
    first = replace(run_tasks, lived_in, "cafe-ia", PRE_M7_CAFE_SOUL_SHA)
    assert first.returncode == 0, first.stdout
    assert recap(first)["changed"] == 1
    profile = lived_in / "profiles/cafe-ia"
    assert sha(profile / "SOUL.md") == sha(CAFE_SOUL)
    backups = [p for p in profile.iterdir() if p.name.startswith("SOUL.md.") and p.name != "SOUL.md"]
    assert len(backups) == 1 and sha(backups[0]) == PRE_M7_CAFE_SOUL_SHA
    second = replace(run_tasks, lived_in, "cafe-ia", PRE_M7_CAFE_SOUL_SHA)
    assert second.returncode == 0, second.stdout
    assert recap(second)["changed"] == 0
    assert len([p for p in profile.iterdir() if p.name.startswith("SOUL.md.")]) == 1


def test_g02_unknown_or_edited_soul_is_refused_untouched(run_tasks: RunTasks, lived_in: Path) -> None:
    """A SOUL.md edited from the dashboard is neither predecessor nor delivered: failure, nothing written."""
    target = lived_in / "profiles/cafe-ia/SOUL.md"
    target.write_text(target.read_text() + "\nRetouche depuis le dashboard.\n")
    before = target.read_bytes()
    result = replace(run_tasks, lived_in, "cafe-ia", PRE_M7_CAFE_SOUL_SHA)
    assert result.returncode != 0
    assert "Revue humaine requise" in result.stdout
    assert target.read_bytes() == before
    assert sorted(p.name for p in target.parent.iterdir()) == ["SOUL.md"]


def test_g03_check_mode_writes_nothing(run_tasks: RunTasks, lived_in: Path) -> None:
    """--check reports the replacement but leaves the file and creates no backup."""
    result = replace(run_tasks, lived_in, "cafe-ia", PRE_M7_CAFE_SOUL_SHA, None, "--check")
    assert result.returncode == 0, result.stdout
    assert sha(lived_in / "profiles/cafe-ia/SOUL.md") == PRE_M7_CAFE_SOUL_SHA
    assert sorted(p.name for p in (lived_in / "profiles/cafe-ia").iterdir()) == ["SOUL.md"]


def test_g04_other_profiles_are_unaffected(run_tasks: RunTasks, lived_in: Path) -> None:
    """Replacing Kaféine leaves Scout's SOUL.md, and the root, as they were."""
    scout = lived_in / "profiles/job-search/SOUL.md"
    before = sha(scout)
    assert replace(run_tasks, lived_in, "cafe-ia", PRE_M7_CAFE_SOUL_SHA).returncode == 0
    assert sha(scout) == before
    assert sorted(p.name for p in lived_in.iterdir()) == ["profiles"]


@pytest.mark.parametrize(
    ("profile", "target"),
    [
        ("cafe-ia", "profiles/job-search/SOUL.md"),
        ("cafe-ia", "SOUL.md"),
        ("cafe-ia", "profiles/cafe-ia/../job-search/SOUL.md"),
        ("default", "profiles/cafe-ia/SOUL.md"),
        ("Cafe IA", "profiles/Cafe IA/SOUL.md"),
    ],
)
def test_g05_target_follows_the_profile_and_nothing_else(
    run_tasks: RunTasks, lived_in: Path, profile: str, target: str
) -> None:
    """A dest that is not exactly <data>/profiles/<profile>/SOUL.md (or the root one for default) is refused."""
    dest = lived_in / target
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(at_base("hermes/ansible/roles/hermes_agent/files/profiles/cafe-ia/SOUL.md"))
    before = dest.read_bytes()
    result = run_tasks(
        "default_soul.yml",
        {
            "hermes_soul_src": str(CAFE_SOUL),
            "hermes_soul_dest": str(dest),
            "hermes_soul_predecessor_sha256": PRE_M7_CAFE_SOUL_SHA,
            "hermes_soul_profile": profile,
            "hermes_data_dir": str(lived_in),
        },
    )
    assert result.returncode != 0
    assert dest.read_bytes() == before


@pytest.mark.parametrize("predecessor", [[], ["not-a-sha"], [PRE_M7_CAFE_SOUL_SHA, "0" * 63]])
def test_g06_malformed_predecessor_lists_are_refused(run_tasks: RunTasks, lived_in: Path, predecessor: list[str]) -> None:
    """An empty list or a non-sha256 entry never authorizes anything."""
    result = replace(run_tasks, lived_in, "cafe-ia", predecessor)
    assert result.returncode != 0
    assert sha(lived_in / "profiles/cafe-ia/SOUL.md") == PRE_M7_CAFE_SOUL_SHA


def test_g07_delivered_soul_cannot_be_its_own_predecessor(run_tasks: RunTasks, lived_in: Path) -> None:
    """Declaring the delivered checksum as a predecessor is a configuration error."""
    assert replace(run_tasks, lived_in, "cafe-ia", [PRE_M7_CAFE_SOUL_SHA, sha(CAFE_SOUL)]).returncode != 0


def run_validate(run: RunTasks, cafe_predecessor: Any, nora_predecessor: Any) -> Any:
    """The real validate.yml with Kaféine and Nora declarations carrying the given predecessors (fake secrets)."""
    cafe = GROUP_VARS["hermes_profile_cafe_ia"] | {
        "telegram_bot_token": TOKENS["cafe-ia"], "env": {"TAVILY_API_KEY": "tvly-FAKE-cafe"},
        "soul_predecessor_sha256": cafe_predecessor,
    }
    nora = GROUP_VARS["hermes_default_nora"] | {
        "soul_predecessor_sha256": nora_predecessor, "env": {"TAVILY_API_KEY": "tvly-FAKE-nora"},
    }
    return run("validate.yml", {
        "hermes_telegram_enabled": True,
        "hermes_telegram_bot_token": TOKENS["default"],
        "hermes_telegram_allowed_users": ALLOWLIST,
        "hermes_profile_reserved_ports": GROUP_VARS["hermes_profile_reserved_ports"],
        "hermes_profiles": [cafe],
        "hermes_default_profile": nora,
    })


def test_v01_validate_accepts_the_declared_predecessors(run_tasks: RunTasks) -> None:
    """Kaféine's single checksum and hermes-31's Nora pair pass the inventory guards."""
    result = run_validate(run_tasks, PRE_M7_CAFE_SOUL_SHA, HOST_31["hermes_default_soul_predecessor_sha256"])
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    ("cafe", "nora"),
    [
        ("not-a-sha", PRE_M7_NORA_SOUL_SHA),
        ([], PRE_M7_NORA_SOUL_SHA),
        (PRE_M7_CAFE_SOUL_SHA, []),
        (PRE_M7_CAFE_SOUL_SHA, [V0225_STOCK_SOUL_SHA, "0" * 63]),
    ],
)
def test_v02_validate_refuses_malformed_predecessors(run_tasks: RunTasks, cafe: Any, nora: Any) -> None:
    """An empty list or a non-sha256 entry stops the playbook before any write."""
    assert run_validate(run_tasks, cafe, nora).returncode != 0


@pytest.mark.parametrize("start", ["stock", "pre-m7"])
def test_g08_nora_converges_from_either_declared_predecessor(run_tasks: RunTasks, tmp_path: Path, start: str) -> None:
    """hermes-31's list: the image seed (rebuild) or the live pre-M7 Nora both become the delivered Nora, once."""
    data = tmp_path / "data"
    data.mkdir()
    pre_m7 = at_base("hermes/ansible/roles/hermes_agent/files/default/SOUL.md")
    if start == "stock":
        content = subprocess.run(
            ["docker", "run", "--rm", "--network", "none", "--entrypoint", "cat", IMAGE, "/opt/hermes/docker/SOUL.md"],
            capture_output=True, text=True, check=False,
        )
        if content.returncode != 0:
            pytest.skip(f"{IMAGE} not available locally")
        (data / "SOUL.md").write_text(content.stdout)
    else:
        (data / "SOUL.md").write_text(pre_m7)
    predecessors = HOST_31["hermes_default_soul_predecessor_sha256"]
    first = replace(run_tasks, data, None, predecessors)
    assert first.returncode == 0, first.stdout
    assert sha(data / "SOUL.md") == sha(NORA_SOUL)
    assert recap(replace(run_tasks, data, None, predecessors))["changed"] == 0


# --- Lab: the real v0.22.5 image, offline -------------------------------------------------------

GW = "hermes-m7-lab-gw"
NEO = "tech-watch"
LAB_PROFILES = ["cafe-ia", "job-search", NEO]
THREE = "default,cafe-ia,job-search"
FOUR = "default,cafe-ia,job-search,tech-watch"
NEO_TOKEN = "333333333:FAKE-techwatch-cccccccccccccccccccccc"

PROMPT_PROBE = r'''
import json, logging, sys
logging.disable(logging.CRITICAL)
from run_agent import AIAgent
from agent.system_prompt import build_system_prompt
agent = AIAgent(base_url="http://127.0.0.1:9/v1", api_key="x", model="deepseek-v4-flash", platform="telegram", quiet_mode=True)
print(json.dumps(build_system_prompt(agent)))
'''


def _state(data: Path) -> dict[str, Any]:
    try:
        return json.loads((data / "gateway_state.json").read_text())
    except (OSError, ValueError):
        return {}


def _root_files(data: Path) -> dict[str, str]:
    """sha256 of every root file outside profiles/ and the volatile runtime dirs (logs, caches, locks)."""
    out = {}
    for path in sorted(data.rglob("*")):
        rel = path.relative_to(data).as_posix()
        if not path.is_file() or rel.startswith(("profiles/", "logs/", "cache/", ".cache/", "home/", "cron/")):
            continue
        out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def _prompt(home: str) -> str:
    r = _dx("python3", "-c", PROMPT_PROBE, env={"HERMES_HOME": home}, container=GW)
    return json.loads(r.stdout) if r.returncode == 0 else f"PROBE FAILED: {r.stderr[-1500:]}"


@pytest.fixture(scope="module")
def lab(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    """Run the M7.3 sequence on the real v0.22.5 image, offline: four served, park Néo, restarts, prompt, delete."""
    if not shutil.which("docker") or _docker("image", "inspect", IMAGE).returncode != 0:
        pytest.skip(f"{IMAGE} not available locally")
    tmp = tmp_path_factory.mktemp("m7lab")
    data, managed = tmp / "data", tmp / "managed"
    data.mkdir()
    managed.mkdir(mode=0o750)
    variables = {k: DEFAULTS[k] for k in (
        "hermes_provider_name", "hermes_provider_display_name", "hermes_provider_base_url", "hermes_provider_key_env",
        "hermes_model_default", "hermes_dashboard_public_url", "hermes_gateway_port", "hermes_dashboard_username",
        "hermes_pgid")} | {
        "hermes_managed_dir": "/etc/hermes", "hermes_deepseek_api_key": "sk-FAKE",
        "hermes_api_server_key": "FAKE-api-server-key-0123456789", "hermes_dashboard_password": "FAKE-dashboard-pass",
        "hermes_dashboard_secret": "FAKE-dashboard-secret-0123456789abcdef", "hermes_telegram_allowed_users": ALLOWLIST,
    }
    render_dir = tmp / "render"
    render_dir.mkdir()
    for template, dest in (("config.yaml.j2", "config.yaml"), ("hermes.env.j2", ".env")):
        (managed / dest).write_text(render(render_dir, template, variables))
        (managed / dest).chmod(0o640)
    facts: dict[str, Any] = {}
    _docker("rm", "-f", GW)
    try:
        run = _docker("run", "-d", "--name", GW, "--network", "none", "-v", f"{data}:/opt/data",
                      "-v", f"{managed}:/etc/hermes:ro", "-e", f"PUID={os.getuid()}", "-e", f"PGID={os.getgid()}",
                      IMAGE, "gateway", "run")
        assert run.returncode == 0, run.stderr
        assert _wait(lambda: _gateway_up(GW)), _docker("logs", GW).stdout[-3000:]

        # hermes-31 before M7.3: Néo (stand-in SOUL.md) served beside Kaféine (M7 config) and Scout.
        configs = effective_configs()
        for name in LAB_PROFILES:
            r = _dx("hermes", "profile", "create", name, "--no-alias", container=GW)
            assert r.returncode == 0, r.stdout + r.stderr
        shutil.copyfile(CAFE_SOUL, data / "profiles/cafe-ia/SOUL.md")
        shutil.copyfile(ROLE / "files/profiles/job-search/SOUL.md", data / "profiles/job-search/SOUL.md")
        (data / f"profiles/{NEO}/SOUL.md").write_text("Tu es **Néo**, l'analyste de veille technique (lab M7).\n")
        for name in ("default", "cafe-ia", "job-search"):
            for key, value in configs[name].items():
                _dx("hermes", "-p", name, "config", "set", key, hp.hermes_config_arg(value), container=GW)
        facts["cafe_hint_get"] = _dx(
            "hermes", "-p", "cafe-ia", "config", "get", "agent.environment_hint", "--json", container=GW
        ).stdout.strip()
        tokens = TOKENS | {NEO: NEO_TOKEN}
        for name in ["default", *LAB_PROFILES]:
            env = data / ".env" if name == "default" else data / f"profiles/{name}/.env"
            env.write_text((env.read_text() if env.exists() else "")
                           + f"\nTAVILY_API_KEY=tvly-FAKE-{name}\nTELEGRAM_BOT_TOKEN={tokens[name]}\n")
        _dx("hermes", "-p", "default", "gateway", "restart", container=GW)
        assert _wait(lambda: _gateway_up(GW))
        facts["four_served"] = _wait(lambda: _checks("multiplex", "/opt/data/gateway_state.json", FOUR, container=GW)[0] == 0, 150)
        _wait(lambda: f"{NEO}:telegram" in _state(data).get("platforms", {}), 240)
        before = _state(data)
        facts["before"] = {"pid": before.get("pid"), "served": before.get("served_profiles"),
                           "neo_entry": f"{NEO}:telegram" in before.get("platforms", {})}
        facts["three_before_park"] = _checks("multiplex", "/opt/data/gateway_state.json", THREE, container=GW)

        # Step 4 of the runbook: park Néo with its native CLI.
        park = _dx("hermes", "-p", NEO, "gateway", "stop", container=GW)
        facts["park"] = [park.returncode, (park.stdout + park.stderr).strip()[-800:]]
        facts["three_after_park"] = _wait(
            lambda: _checks("multiplex", "/opt/data/gateway_state.json", THREE, container=GW)[0] == 0, 90
        )
        _wait(lambda: f"{NEO}:telegram" not in _state(data).get("platforms", {}), 60)
        after = _state(data)
        facts["after_park"] = {"pid": after.get("pid"), "served": after.get("served_profiles"),
                               "parked": after.get("parked_profiles"),
                               "neo_entry": f"{NEO}:telegram" in after.get("platforms", {}),
                               "marker": (data / f"profiles/{NEO}/gateway.parked").exists()}
        facts["four_after_park"] = _checks("multiplex", "/opt/data/gateway_state.json", FOUR, container=GW)

        # Parking survives a gateway restart (the one M7.3's deploy triggers) and a container restart.
        _dx("hermes", "-p", "default", "gateway", "restart", container=GW)
        assert _wait(lambda: _gateway_up(GW))
        facts["three_after_gateway_restart"] = _wait(
            lambda: _checks("multiplex", "/opt/data/gateway_state.json", THREE, container=GW)[0] == 0, 120
        )
        facts["served_after_gateway_restart"] = _state(data).get("served_profiles")
        restart = _docker("restart", GW)
        assert restart.returncode == 0, restart.stderr
        assert _wait(lambda: _gateway_up(GW))
        facts["three_after_container_restart"] = _wait(
            lambda: _checks("multiplex", "/opt/data/gateway_state.json", THREE, container=GW)[0] == 0, 120
        )
        facts["served_after_container_restart"] = _state(data).get("served_profiles")
        facts["neo_entry_after_restarts"] = f"{NEO}:telegram" in _state(data).get("platforms", {})

        # Kaféine's prompt, built the way a NEW session builds it, before and after a SOUL.md change on disk.
        facts["prompt"] = {name: _prompt("/opt/data" if name == "default" else f"/opt/data/profiles/{name}")
                           for name in ("default", "cafe-ia", "job-search")}
        soul = data / "profiles/cafe-ia/SOUL.md"
        original = soul.read_text()
        soul.write_text(original + "\nMARQUEUR-M7-NOUVELLE-SESSION\n")
        facts["prompt_after_soul_change"] = _prompt("/opt/data/profiles/cafe-ia")
        soul.write_text(original)

        # Step 13 (separate approval in production): permanent deletion, then rediscovery attempts.
        kept = {name: {f: sha(data / f"profiles/{name}/{f}") for f in ("SOUL.md", "config.yaml", ".env")}
                for name in ("cafe-ia", "job-search")}
        root_before = _root_files(data)
        delete = _dx("hermes", "profile", "delete", NEO, "--yes", container=GW)
        facts["delete"] = [delete.returncode, (delete.stdout + delete.stderr).strip()[-1500:]]
        facts["neo_dir_after_delete"] = (data / f"profiles/{NEO}").exists()
        facts["tombstone"] = (data / f"profiles/.deleted/{NEO}").exists()
        facts["slot_after_delete"] = _dx("ls", "/run/service", container=GW).stdout.split()
        facts["kept_unchanged"] = kept == {
            name: {f: sha(data / f"profiles/{name}/{f}") for f in ("SOUL.md", "config.yaml", ".env")}
            for name in ("cafe-ia", "job-search")
        }
        root_after = _root_files(data)
        facts["root_changed"] = sorted(k for k in root_before.keys() | root_after.keys()
                                       if root_before.get(k) != root_after.get(k))
        facts["three_after_delete"] = _checks("multiplex", "/opt/data/gateway_state.json", THREE, container=GW)
        # A stale writer recreating the directory, then a gateway restart: the tombstone keeps it unlisted.
        ghost = data / f"profiles/{NEO}"
        ghost.mkdir(parents=True, exist_ok=True)
        (ghost / "config.yaml").write_text("model: {}\n")
        _dx("hermes", "-p", "default", "gateway", "restart", container=GW)
        assert _wait(lambda: _gateway_up(GW))
        time.sleep(35)  # one full rescan period
        facts["three_after_ghost"] = _checks("multiplex", "/opt/data/gateway_state.json", THREE, container=GW)
        facts["profile_list_after_ghost"] = _dx("hermes", "profile", "list", container=GW).stdout
        if os.environ.get("M7_LAB_FACTS"):
            # Evidence for the mission report: everything but the full prompts.
            dump = facts | {"prompt": {k: v[:200] for k, v in facts["prompt"].items()}, "prompt_after_soul_change": "..."}
            Path(os.environ["M7_LAB_FACTS"]).write_text(json.dumps(dump, indent=1, ensure_ascii=False))
        yield facts
    finally:
        _docker("rm", "-f", GW)


def test_lab_kafeine_config_and_hint_apply(lab: dict[str, Any]) -> None:
    """The M7 hint is accepted by v0.22.5 and reads back equal."""
    hint = GROUP_VARS["hermes_profile_cafe_ia"]["config"]["agent.environment_hint"]
    assert json.loads(lab["cafe_hint_get"]) == hint


def test_lab_four_served_before_parking_and_the_three_profile_check_refuses(lab: dict[str, Any]) -> None:
    """As on hermes-31 today: Néo is served; the M7 deploy's exact-set check would fail before the park."""
    assert lab["four_served"]
    assert set(lab["before"]["served"]) == set(FOUR.split(","))
    assert lab["before"]["neo_entry"] is True
    assert lab["three_before_park"][0] != 0 and "tech-watch" in lab["three_before_park"][1]


def test_lab_gateway_stop_parks_tech_watch_without_restarting_the_gateway(lab: dict[str, Any]) -> None:
    """`hermes -p tech-watch gateway stop`: marker, unserved, bot entry gone, same gateway pid."""
    assert lab["park"][0] == 0, lab["park"]
    assert "parked" in lab["park"][1]
    assert lab["after_park"]["marker"] is True
    assert lab["after_park"]["pid"] == lab["before"]["pid"]
    assert lab["after_park"]["neo_entry"] is False


def test_lab_parked_neo_leaves_served_profiles_and_three_converge(lab: dict[str, Any]) -> None:
    """served_profiles = default, cafe-ia, job-search; the exact-set check passes for three, fails for four.

    v0.22.5 leaves the root `parked_profiles` empty after a park: the proof is the marker plus `served_profiles`.
    """
    assert lab["three_after_park"], lab["after_park"]
    assert set(lab["after_park"]["served"]) == set(THREE.split(","))
    assert lab["after_park"]["parked"] in ({}, None, [])
    assert lab["four_after_park"][0] != 0


def test_lab_parking_survives_a_gateway_restart(lab: dict[str, Any]) -> None:
    """The deploy's single `hermes -p default gateway restart` does not bring Néo back."""
    assert lab["three_after_gateway_restart"], lab["served_after_gateway_restart"]


def test_lab_parking_survives_a_container_restart(lab: dict[str, Any]) -> None:
    """Boot reconcile keeps Néo parked; its bot entry does not come back."""
    assert lab["three_after_container_restart"], lab["served_after_container_restart"]
    assert lab["neo_entry_after_restarts"] is False


def test_lab_kafeine_prompt_carries_its_soul_and_hint_only(lab: dict[str, Any]) -> None:
    """Kaféine's built prompt has its new SOUL.md and the hint; Nora's and Scout's prompts carry neither."""
    cafe = lab["prompt"]["cafe-ia"]
    assert not cafe.startswith("PROBE FAILED"), cafe
    assert "Tu es **Kaféine**" in cafe and "Trois facettes, un seul assistant" in cafe
    assert "RTX 4060" in cafe and "contextualiser tes analyses et ta veille" in cafe
    for other in ("default", "job-search"):
        assert "RTX 4060" not in lab["prompt"][other], other
        assert "Tu es **Kaféine**" not in lab["prompt"][other], other


def test_lab_soul_change_reaches_a_new_session(lab: dict[str, Any]) -> None:
    """SOUL.md is read when a session's prompt is built: a change on disk shows in the next one, no restart."""
    assert "MARQUEUR-M7-NOUVELLE-SESSION" in lab["prompt_after_soul_change"]


def test_lab_profile_delete_removes_only_neo(lab: dict[str, Any]) -> None:
    """`hermes profile delete tech-watch --yes`: directory and s6 slot gone, tombstone written, others untouched."""
    assert lab["delete"][0] == 0, lab["delete"]
    assert lab["neo_dir_after_delete"] is False
    assert lab["tombstone"] is True
    assert "gateway-tech-watch" not in lab["slot_after_delete"]
    assert {"gateway-default", "gateway-cafe-ia", "gateway-job-search"} <= set(lab["slot_after_delete"])
    assert lab["kept_unchanged"] is True
    assert lab["three_after_delete"][0] == 0, lab["three_after_delete"]


def test_lab_profile_delete_shared_state_is_bounded(lab: dict[str, Any]) -> None:
    """Outside profiles/ only gateway bookkeeping changes (state, locks, session index, state.db); no config, .env, SOUL."""
    for rel in lab["root_changed"]:
        assert rel not in ("config.yaml", ".env", "SOUL.md"), rel
        assert rel.startswith((".local/state/hermes/", "gateway_state.json", "state.db", "sessions/",
                               "gateway", "processes", "auth", "channel_directory")), lab["root_changed"]


def test_lab_tombstone_prevents_rediscovery(lab: dict[str, Any]) -> None:
    """A recreated directory with a config.yaml stays unlisted and unserved after a gateway restart."""
    assert lab["three_after_ghost"][0] == 0, lab["three_after_ghost"]
    assert NEO not in lab["profile_list_after_ghost"]
