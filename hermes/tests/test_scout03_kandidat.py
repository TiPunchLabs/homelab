"""SCOUT-03 — Kandidat for Scout (job-search) only, under an enforced write policy.

Offline: the declaration (two MCP entries, explicit allowlists, trust levels),
the role guards (validate.yml, the post-deploy `mcp` check), the pure verdict
functions, SOUL.md rules and the inactive cron drafts.

Lab (real Hermes v0.22.5 image, `--network none`, skipped when absent): the
declaration applied with `hermes config set`, a fake Kandidat MCP server with
the deployed tool surface (fixtures/kandidat_mcp_tools.json), and what Hermes
itself does: tools exposed per platform, denied tools unreachable, the approval
gate, duplicate refusal and retries, a lost connection, a server outage, an
embedded instruction. Nothing reaches hermes-31 or the real Kandidat.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import REPO, ROLE, RunTasks
from test_m2_cafe_ia import GROUP_VARS, HERMES, TASKS, validate
from test_m4_scout import FAKE_HINT, private_fact, resolved

sys.path.insert(0, str(ROLE / "filter_plugins"))
sys.path.insert(0, str(ROLE / "files"))

import hermes_checks as hc
import hermes_profiles as hp

FIXTURES = Path(__file__).parent / "fixtures"
SURFACE = json.loads((FIXTURES / "kandidat_mcp_tools.json").read_text())["tools"]
HINTS = {t["name"]: t["readOnlyHint"] for t in SURFACE}
DESTRUCTIVE = {t["name"] for t in SURFACE if t["destructiveHint"]}
SOUL = ROLE / "files/profiles/job-search/SOUL.md"
DRAFTS = HERMES / "cron-drafts/job-search.yml"
HOST_31 = yaml.safe_load((HERMES / "ansible/host_vars/hermes-31/main.yml").read_text())
IMAGE = "{}:{}".format(yaml.safe_load((ROLE / "defaults/main.yml").read_text())["hermes_image"], "v0.22.5")
READS = {
    "list_cibles",
    "get_cible_detail",
    "list_candidatures",
    "get_candidature",
    "get_candidature_history",
    "search_candidatures",
    "get_stats",
}
# No automatic write: at Kandidat a0cf66ea create_candidature also sets today's date_candidature and marks the
# company contactee (services/candidature.py), so it is gated with the others (Codex review, pass 3).
AUTO: set[str] = set()
CONFIRM = {"create_candidature", "create_cible", "update_candidature", "update_cible"}
LAB_PORT = 18765
FAKE_URL = f"http://127.0.0.1:{LAB_PORT}/mcp"


@pytest.fixture(scope="module")
def group_vars() -> dict[str, Any]:
    """The hermes group_vars, as written."""
    return yaml.safe_load(GROUP_VARS.read_text())


@pytest.fixture(scope="module")
def scout(group_vars: dict[str, Any]) -> dict[str, Any]:
    """Scout's declaration with fakes for the vault values, as hermes-31 receives it (v0.22 overlay)."""
    decl = resolved(group_vars["hermes_profile_job_search"])
    return decl | {"config": decl["config"] | HOST_31["hermes_v022_config"]}


def servers(profile: dict[str, Any]) -> dict[str, Any]:
    """The MCP servers a profile declares."""
    return hp.hermes_mcp_policy(profile).get("servers", {})


# --- Declaration ---------------------------------------------------------------------------------


def test_t01_two_entries_with_the_approved_tools(scout: dict[str, Any]) -> None:
    """kandidat: the seven reads only; kandidat_confirm: the four gated writes; same URL, nothing else."""
    decl = servers(scout)
    assert set(decl) == {"kandidat", "kandidat_confirm"}
    assert set(decl["kandidat"]["tools"]["include"]) == READS | AUTO
    assert set(decl["kandidat_confirm"]["tools"]["include"]) == CONFIRM
    assert decl["kandidat"]["trust"] == "full"
    assert decl["kandidat_confirm"]["trust"] == "untrusted"
    assert {s["url"] for s in decl.values()} == {"https://kandidat-mcp.internal/mcp"}
    for spec in decl.values():
        assert spec["tools"]["resources"] is False and spec["tools"]["prompts"] is False
    assert set(decl["kandidat"]) == {"url", "trust", "tools"}
    assert set(decl["kandidat_confirm"]) == {"url", "trust", "tools", "tool_costs", "spend_limit", "cost_unit"}


def test_t01_every_other_kandidat_tool_stays_out(scout: dict[str, Any]) -> None:
    """Deletes, contacts, AI operations, settings and history comments: in no allowlist."""
    included = {t for spec in servers(scout).values() for t in spec["tools"]["include"]}
    assert included <= set(HINTS), "a declared tool does not exist on the deployed server"
    assert not included & DESTRUCTIVE
    denied = set(HINTS) - READS - AUTO - CONFIRM
    assert denied == {
        "delete_cible",
        "delete_candidature",
        "delete_contact",
        "create_contact",
        "update_contact",
        "enrich_cible",
        "apply_enrichment",
        "adapt_cv",
        "save_adapted_cv",
        "evaluate_match",
        "get_settings",
        "update_historique_comment",
    }
    assert not included & denied


def test_t02_write_capable_tools_match_the_policy() -> None:
    """With the deployed annotations: kandidat exposes no write at all; every gated tool is a write."""
    assert {t for t in READS | AUTO if not HINTS[t]} == set()
    assert all(HINTS[t] is True for t in READS)
    assert all(HINTS[t] is False for t in CONFIRM)


def test_t02_local_gate_does_not_trust_the_server(scout: dict[str, Any]) -> None:
    """Every gated tool costs more than the per-chat limit (> 0): Hermes asks before each call, whatever readOnlyHint
    the server advertises."""
    confirm = servers(scout)["kandidat_confirm"]
    assert confirm["spend_limit"] > 0
    assert set(confirm["tool_costs"]) == CONFIRM
    assert all(cost > confirm["spend_limit"] for cost in confirm["tool_costs"].values())
    assert "tool_costs" not in servers(scout)["kandidat"]


def test_t02_platforms_and_cron(scout: dict[str, Any]) -> None:
    """Telegram, API and CLI get both servers; cron only kandidat (nobody can approve there); no no_mcp."""
    cfg = scout["config"]
    for platform in ("telegram", "api_server", "cli"):
        assert {"kandidat", "kandidat_confirm"} <= set(cfg[f"platform_toolsets.{platform}"])
    assert "kandidat" in cfg["platform_toolsets.cron"]
    assert "kandidat_confirm" not in cfg["platform_toolsets.cron"]
    assert not any("no_mcp" in cfg[f"platform_toolsets.{p}"] for p in ("telegram", "api_server", "cli", "cron"))
    assert "auto_writes" not in scout["mcp_policy"]
    assert hp.hermes_mcp_declaration_errors(scout) == []


def test_t03_other_profiles_keep_no_mcp(group_vars: dict[str, Any]) -> None:
    """Nora (default) and Kaféine: no_mcp everywhere, no server, an empty policy (zero active server expected)."""
    for key in ("hermes_profile_cafe_ia", "hermes_default_nora"):
        profile = group_vars[key]
        cfg = profile["config"]
        for platform in ("telegram", "api_server", "cli", "cron"):
            assert "no_mcp" in cfg[f"platform_toolsets.{platform}"], (key, platform)
            assert "kandidat" not in cfg[f"platform_toolsets.{platform}"]
        assert hp.hermes_mcp_policy(profile) == {}
        assert hp.hermes_mcp_declaration_errors(profile) == []
    assert group_vars["hermes_default_nora"]["config"]["mcp_servers.kandidat.enabled"] is False


@pytest.mark.parametrize(
    ("label", "mutate", "expected"),
    [
        ("exclude only", lambda s: s["config"]["mcp_servers.kandidat"]["tools"].update(exclude=["x"]), "exclude"),
        ("no include", lambda s: s["config"]["mcp_servers.kandidat"]["tools"].pop("include"), "include"),
        ("glob", lambda s: s["config"]["mcp_servers.kandidat"]["tools"]["include"].append("delete_*"), "explicit"),
        ("delete", lambda s: s["config"]["mcp_servers.kandidat_confirm"]["tools"]["include"].append("delete_cible"),
         "delete"),
        ("trust", lambda s: s["config"]["mcp_servers.kandidat_confirm"].pop("trust"), "trust"),
        ("utilities", lambda s: s["config"]["mcp_servers.kandidat"]["tools"].update(resources=True), "resources"),
        ("headers", lambda s: s["config"]["mcp_servers.kandidat"].update(headers={"X": "y"}), "headers"),
        ("auto on gated", lambda s: s["mcp_policy"].update(auto_writes={"kandidat_confirm": ["update_cible"]}),
         "approval-gated"),
        ("cron drift", lambda s: s["config"]["platform_toolsets.cron"].append("kandidat_confirm"), "cron"),
        ("no_mcp kept", lambda s: s["config"]["platform_toolsets.telegram"].append("no_mcp"), "telegram"),
        ("no policy", lambda s: s.pop("mcp_policy"), "without mcp_policy"),
        ("no local gate", lambda s: s["config"]["mcp_servers.kandidat_confirm"].pop("tool_costs"), "tool_costs"),
        ("limit zero", lambda s: s["config"]["mcp_servers.kandidat_confirm"].update(spend_limit=0), "spend_limit > 0"),
        ("cost under limit",
         lambda s: s["config"]["mcp_servers.kandidat_confirm"]["tool_costs"].update(update_cible=1), "update_cible"),
        ("sub-key", lambda s: s["config"].update({"mcp_servers.kandidat.enabled": True}), "whole servers"),
    ],
)
def test_t03_declaration_guard_refuses(scout: dict[str, Any], label: str, mutate: Any, expected: str) -> None:
    """Each weakening of the declaration is refused before any write, with a reason naming it."""
    bad = json.loads(json.dumps(scout))
    mutate(bad)
    errors = hp.hermes_mcp_declaration_errors(bad)
    assert errors, label
    assert any(expected in e for e in errors), (label, errors)


def test_t04_validate_yml_runs_the_guard(run_tasks: RunTasks, group_vars: dict[str, Any], scout: dict[str, Any]) -> None:
    """The real validate.yml accepts Scout as declared and refuses a gated write made automatic."""
    assert validate(run_tasks, group_vars, [scout]).returncode == 0
    bad = json.loads(json.dumps(scout))
    bad["mcp_policy"]["auto_writes"] = {"kandidat_confirm": ["update_candidature"]}
    result = validate(run_tasks, group_vars, [bad])
    assert result.returncode != 0
    assert "approval-gated" in result.stdout
    assert "SYNTHETIQUE-M4-TEST" not in result.stdout + result.stderr


def test_t04_deploy_check_runs_before_the_token_and_the_restart() -> None:
    """profile_multiplex.yml: the mcp check right after the toolset check, before the token write and restart."""
    names = [t["name"] for t in yaml.safe_load((TASKS / "profile_multiplex.yml").read_text())]
    mcp = names.index("Verify the MCP servers and tools exposed ({{ hermes_profile.name }})")
    assert names.index("Verify that the declared tool restrictions are effective ({{ hermes_profile.name }})") < mcp
    assert mcp < names.index("Pin the .env keys of profile {{ hermes_profile.name }}")
    assert mcp < names.index("Schedule one restart of the multiplexed gateway ({{ hermes_profile.name }})")
    task = yaml.safe_load((TASKS / "profile_multiplex.yml").read_text())[mcp]
    assert task["ansible.builtin.command"]["argv"][-2:] == ["mcp", "{{ hermes_profile | hermes_mcp_policy | to_json }}"]
    assert task["changed_when"] is False


def test_t04_failed_check_cannot_lose_the_restart() -> None:
    """Config written, then a check fails (Kandidat down): a marker on the host survives the failure, the next run
    restarts the gateway even with nothing left to change, and only then clears it."""
    tasks = yaml.safe_load((TASKS / "profile_multiplex.yml").read_text())
    names = [t["name"] for t in tasks]
    mark = names.index("Persist a pending gateway restart ({{ hermes_profile.name }})")
    assert names.index("Set the config keys of profile {{ hermes_profile.name }}") < mark
    assert mark < names.index("Verify the MCP servers and tools exposed ({{ hermes_profile.name }})")
    marker = tasks[mark]["ansible.builtin.copy"]
    assert marker["content"] == "pending\n" and marker["dest"] == "{{ hermes_install_dir }}/.multiplex-restart-pending"
    assert "hermes_profile_config_set is changed" in tasks[mark]["when"]
    main = yaml.safe_load((TASKS / "main.yml").read_text())
    names = [t.get("name") for t in main]
    read = names.index("Read a gateway restart left pending by an interrupted run")
    restart = names.index("Restart the multiplexed gateway once with the final profile configuration")
    done = names.index("Mark the pending gateway restart as done")
    assert read < restart < done
    assert any("== 'pending'" in str(c) for c in main[restart]["when"])
    assert main[done]["ansible.builtin.copy"]["content"] == "done\n"
    assert "hermes_multiplex_restarted is changed" in main[done]["when"]


def test_t04_soul_replaced_once_from_the_m43_version() -> None:
    """The live SOUL.md is replaced only if it is still the M4.3 one (checked on hermes-31 on 2026-11-12)."""
    previous = subprocess.run(
        ["git", "show", "origin/main:hermes/ansible/roles/hermes_agent/files/profiles/job-search/SOUL.md"],
        cwd=REPO,
        capture_output=True,
        check=False,
    )
    decl = yaml.safe_load(GROUP_VARS.read_text())["hermes_profile_job_search"]
    if previous.returncode == 0 and b"Kandidat \xe2\x80\x94 l'historique" not in previous.stdout:
        import hashlib

        assert hashlib.sha256(previous.stdout).hexdigest() == decl["soul_predecessor_sha256"]
    assert hashlib_of(SOUL) != decl["soul_predecessor_sha256"]


def hashlib_of(path: Path) -> str:
    """sha256 of a file."""
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- Verdict functions of the deploy check ---------------------------------------------------------


def test_t05_config_verdict(scout: dict[str, Any]) -> None:
    """Equal to the declaration: no error; drift, extra server or a disabled server named: errors."""
    decl = servers(scout)
    assert hc.mcp_config_errors(decl, decl) == []
    drift = json.loads(json.dumps(decl))
    drift["kandidat"]["tools"]["include"].append("update_candidature")
    assert any("differs" in e for e in hc.mcp_config_errors(drift, decl))
    assert any("differ from the declared" in e for e in hc.mcp_config_errors(decl | {"other": {"url": "x"}}, decl))
    assert hc.mcp_config_errors({"kandidat": {"enabled": False}}, {}) == []
    assert hc.mcp_config_errors({"kandidat": {"url": "x"}}, {})


def test_t05_hint_verdict(scout: dict[str, Any]) -> None:
    """Live annotations: an unapproved write on the full server, or a read on the gated one, is an error."""
    decl = servers(scout)
    hints = {"kandidat": HINTS, "kandidat_confirm": HINTS}
    registered = {n: set(s["tools"]["include"]) for n, s in decl.items()}
    trust = {"kandidat": "full", "kandidat_confirm": "untrusted"}
    auto: dict[str, list[str]] = {}
    assert hc.mcp_hint_errors(decl, registered, hints, trust, auto) == []
    # create_candidature put back on the full server: a write without approval, refused.
    back = registered | {"kandidat": registered["kandidat"] | {"create_candidature"}}
    assert any("without approval: create_candidature" in e for e in hc.mcp_hint_errors(decl, back, hints, trust, auto))
    flipped = hints | {"kandidat": HINTS | {"get_stats": False}}
    assert any("without approval: get_stats" in e for e in hc.mcp_hint_errors(decl, registered, flipped, trust, auto))
    loosened = hints | {"kandidat_confirm": HINTS | {"update_candidature": True}}
    assert any("skip the approval gate" in e for e in hc.mcp_hint_errors(decl, registered, loosened, trust, auto))
    assert any("trust" in e for e in hc.mcp_hint_errors(decl, registered, hints, trust | {"kandidat_confirm": "full"}, auto))
    extra = registered | {"kandidat": registered["kandidat"] | {"delete_cible"}}
    assert any("beyond tools.include" in e for e in hc.mcp_hint_errors(decl, extra, hints, trust, auto))


def test_t05_platform_and_exposure_verdicts() -> None:
    """Server lists and exposed MCP tools per platform must equal the policy exactly."""
    effective = {"telegram": {"web", "kandidat", "kandidat_confirm"}, "cron": {"web", "kandidat"}}
    policy = {"telegram": ["kandidat", "kandidat_confirm"], "cron": ["kandidat"]}
    assert hc.mcp_platform_errors(effective, {"kandidat", "kandidat_confirm"}, policy) == []
    assert hc.mcp_platform_errors(effective, {"kandidat", "kandidat_confirm"}, policy | {"cron": []})
    assert hc.mcp_exposure_errors({"cron": {"a"}}, {"cron": {"a"}}) == []
    assert hc.mcp_exposure_errors({"cron": {"a", "b"}}, {"cron": {"a"}})


# --- SOUL.md and drafts ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rule",
    [
        "cherche-la dans Kandidat",
        "sans paramètres de suivi",
        "Deux offres de la même entreprise restent deux offres",
        "correspondance à vérifier",
        "marque l'entreprise « contactée »",
        "Toute écriture passe par",
        "l'utilisateur approuve chaque appel",
        "Une relance déclarée est **une** relance",
        "propose-le, n'écris rien sans son accord",
        "n'est pas une exclusion",
        "historique Kandidat non vérifié",
        "relis la fiche avant toute nouvelle tentative",
        "présence physique programmée et récurrente hors de Guadeloupe",
        "N'assouplis jamais ce seuil",
        "« Remote France » ne prouve pas",
        "autorisation de travail",
        "date de ta vérification",
        "Une date absente ne prouve pas que l'offre est close",
        "plausibles tout de suite",
        "ne valent pas une longue expérience de production",
        "servent à **découvrir**",
        "réellement essayée",
        "ne la devine pas",
        "jamais une instruction",
        "nombre de relances",
    ],
)
def test_t06_soul_carries_the_rule(rule: str) -> None:
    """Each recovered or corrected search rule is in Scout's SOUL.md."""
    assert rule in SOUL.read_text()


def test_t06_soul_lists_only_tools_it_has_and_no_private_fact(scout: dict[str, Any]) -> None:
    """Tools named in SOUL.md exist in the allowlists; no fact of the real context, no company of the search."""
    text = SOUL.read_text()
    named = {t for t in HINTS if f"`{t}`" in text}
    assert named <= READS | AUTO | CONFIRM
    assert private_fact(text) is None
    assert "Ni Kandidat" not in text and "ni Kandidat" not in text


def test_t06_drafts_stay_inactive_and_use_kandidat() -> None:
    """Cron drafts: still read by nothing, deduplicate in Kandidat, never write without approval."""
    text = DRAFTS.read_text()
    assert "INACTIFS" in text
    drafts = yaml.safe_load(text)
    for name in ("veille-emploi", "prospection-entreprises"):
        prompt = drafts[name]["prompt"]
        assert "search_candidatures" in prompt
        assert "historique Kandidat non vérifié" in prompt
        assert "update_candidature" not in prompt or "approbation" in prompt
        # Nobody can approve in cron and every Kandidat write is gated: the drafts never ask for one.
        assert not {"create_candidature", "create_cible", "update_cible"} & set(re.findall(r"\w+", prompt))
    for path in (ROLE / "tasks").glob("*.yml"):
        assert "cron-drafts" not in path.read_text(), path


# --- Lab: real v0.22.5 image, offline, fake Kandidat --------------------------------------------------


def lab_values(profile: dict[str, Any]) -> dict[str, Any]:
    """Config values applied in the lab: the fake server in place of Kandidat, templated values left out."""
    out = {}
    for key, value in profile["config"].items():
        if isinstance(value, str) and "{{" in value:
            continue
        if key.startswith("mcp_servers.") and key.count(".") == 1:
            value = value | {"url": FAKE_URL}
        out[key] = value
    return out


def lab_profile(profile: dict[str, Any]) -> dict[str, str]:
    """Config keys as `hermes config set` arguments."""
    return {key: hp.hermes_config_arg(value) for key, value in lab_values(profile).items()}


def text(result: str) -> str:
    """A tool result as the model reads it: Hermes wraps the MCP text in {"result": ...}."""
    try:
        data = json.loads(result)
    except ValueError:
        return result
    inner = data.get("result") if isinstance(data, dict) else None
    return inner if isinstance(inner, str) else result


def lab_policy(profile: dict[str, Any]) -> dict[str, Any]:
    """The deploy check policy, the fake server in place of Kandidat."""
    policy = hp.hermes_mcp_policy(profile)
    for spec in policy.get("servers", {}).values():
        spec["url"] = FAKE_URL
    return policy


STEPS = [
    {"tool": "mcp__kandidat__delete_cible", "args": {"payload": "1"}},
    {"tool": "mcp__kandidat_confirm__delete_candidature", "args": {"payload": "piege"}},
    {"tool": "mcp__kandidat__get_settings", "args": {}},
    # Offers, each approved (3-6).
    {"tool": "mcp__kandidat_confirm__create_candidature", "consent": "accept",
     "args": {"entreprise": "Entreprise Existante", "cible_id": 1}},
    {"tool": "mcp__kandidat_confirm__create_candidature", "consent": "accept",
     "args": {"entreprise": "Nouvelle Offre", "cible_id": 1}},
    {"tool": "mcp__kandidat_confirm__create_candidature", "consent": "accept",
     "args": {"entreprise": "Nouvelle Offre", "cible_id": 1}},
    {"tool": "mcp__kandidat_confirm__create_candidature", "consent": "accept",
     "args": {"entreprise": "Entreprise Existante SRE", "cible_id": 1, "poste": "SRE"}},
    # Each gated tool: approved, refused, nobody to answer (7-16).
    {"tool": "mcp__kandidat_confirm__create_cible", "consent": "accept", "args": {"nom": "Acme", "categorie": "esn"}},
    {"tool": "mcp__kandidat_confirm__create_cible", "consent": "decline", "args": {"nom": "Acme2", "categorie": "esn"}},
    {"tool": "mcp__kandidat_confirm__create_cible", "nobody": True, "args": {"nom": "Acme3", "categorie": "esn"}},
    {"tool": "mcp__kandidat_confirm__update_candidature", "consent": "accept",
     "args": {"slug": "nouvelle-offre", "statut": "relancee"}},
    {"tool": "mcp__kandidat_confirm__update_candidature", "consent": "decline",
     "args": {"slug": "nouvelle-offre", "statut": "envoyee"}},
    {"tool": "mcp__kandidat_confirm__update_candidature", "nobody": True,
     "args": {"slug": "nouvelle-offre", "statut": "envoyee"}},
    {"tool": "mcp__kandidat_confirm__update_candidature", "consent": "accept",
     "args": {"slug": "nouvelle-offre", "statut": "envoyee", "commentaire": "Declare par l'utilisateur"}},
    {"tool": "mcp__kandidat_confirm__update_cible", "consent": "accept", "args": {"payload": "a"}},
    {"tool": "mcp__kandidat_confirm__update_cible", "consent": "decline", "args": {"payload": "b"}},
    {"tool": "mcp__kandidat_confirm__update_cible", "nobody": True, "args": {"payload": "c"}},
    # An offer text ordering deletions, then the very call it asks for (17-18).
    {"tool": "mcp__kandidat__get_candidature", "args": {"slug": "piege"}},
    {"tool": "mcp__kandidat__delete_cible", "args": {"payload": "all"}},
    # create_candidature: refused, nobody, approved (19-21); the former automatic path is unknown (22).
    {"tool": "mcp__kandidat_confirm__create_candidature", "consent": "decline",
     "args": {"entreprise": "Offre Refusee", "cible_id": 1}},
    {"tool": "mcp__kandidat_confirm__create_candidature", "nobody": True,
     "args": {"entreprise": "Offre Cron", "cible_id": 1}},
    {"tool": "mcp__kandidat_confirm__create_candidature", "consent": "accept",
     "args": {"entreprise": "Offre Approuvee", "cible_id": 1}},
    {"tool": "mcp__kandidat__create_candidature", "args": {"entreprise": "Offre Directe", "cible_id": 1}},
]
FLIP_STEPS = [
    {"tool": "mcp__kandidat_confirm__create_cible", "consent": "accept", "args": {"nom": "Flip1", "categorie": "esn"}},
    {"tool": "mcp__kandidat_confirm__create_cible", "consent": "decline", "args": {"nom": "Flip2", "categorie": "esn"}},
    {"tool": "mcp__kandidat_confirm__create_cible", "nobody": True, "args": {"nom": "Flip3", "categorie": "esn"}},
    {"tool": "mcp__kandidat_confirm__update_candidature", "consent": "accept",
     "args": {"slug": "entreprise-existante", "statut": "envoyee"}},
    {"tool": "mcp__kandidat_confirm__update_candidature", "consent": "decline",
     "args": {"slug": "entreprise-existante", "statut": "relancee"}},
    {"tool": "mcp__kandidat_confirm__update_candidature", "nobody": True,
     "args": {"slug": "entreprise-existante", "statut": "relancee"}},
    {"tool": "mcp__kandidat_confirm__update_cible", "consent": "accept", "args": {"payload": "p1"}},
    {"tool": "mcp__kandidat_confirm__update_cible", "consent": "decline", "args": {"payload": "p2"}},
    {"tool": "mcp__kandidat_confirm__update_cible", "nobody": True, "args": {"payload": "p3"}},
    {"tool": "mcp__kandidat_confirm__create_candidature", "consent": "accept",
     "args": {"entreprise": "Flip Offre A", "cible_id": 1}},
    {"tool": "mcp__kandidat_confirm__create_candidature", "consent": "decline",
     "args": {"entreprise": "Flip Offre B", "cible_id": 1}},
    {"tool": "mcp__kandidat_confirm__create_candidature", "nobody": True,
     "args": {"entreprise": "Flip Offre C", "cible_id": 1}},
]
BLOCKED = ("was NOT run", "did not approve", "blocked", "spend limit")


@pytest.fixture(scope="module")
def lab(group_vars: dict[str, Any], scout: dict[str, Any], tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Apply job-search, cafe-ia and default (Nora) to the offline v0.22.5 image and run the driver."""
    docker = shutil.which("docker")
    if not docker or subprocess.run([docker, "image", "inspect", IMAGE], capture_output=True, check=False).returncode:
        pytest.skip(f"{IMAGE} not available locally")
    overlay = HOST_31["hermes_v022_config"]
    cafe = group_vars["hermes_profile_cafe_ia"]
    nora = group_vars["hermes_default_nora"]
    drift_full = servers(scout)["kandidat"] | {"url": FAKE_URL}
    drift_full = drift_full | {"tools": drift_full["tools"] | {"include": [*drift_full["tools"]["include"],
                                                                           "update_candidature"]}}
    drift_trust = servers(scout)["kandidat_confirm"] | {"url": FAKE_URL, "trust": "full"}
    payload = {
        "port": LAB_PORT,
        "profiles": {
            "job-search": lab_profile(scout),
            "cafe-ia": lab_profile(cafe | {"config": cafe["config"] | overlay}),
            "default": lab_profile(nora | {"config": nora["config"] | overlay}),
        },
        "policies": {"job-search": lab_policy(scout), "cafe-ia": {}, "default": {}},
        "drifts": {
            "update_without_approval": ["mcp_servers.kandidat", hp.hermes_config_arg(drift_full)],
            "gated_server_trusted": ["mcp_servers.kandidat_confirm", hp.hermes_config_arg(drift_trust)],
            # Declaration AND config changed together: only the live annotations can catch it.
            "declared_write_without_approval": [
                "mcp_servers.kandidat",
                hp.hermes_config_arg(drift_full),
                lab_policy(scout) | {"servers": lab_policy(scout)["servers"] | {"kandidat": drift_full}},
            ],
            "cron_gets_gated_server": [
                "platform_toolsets.cron",
                hp.hermes_config_arg([*scout["config"]["platform_toolsets.cron"], "kandidat_confirm"]),
            ],
        },
        "steps": STEPS,
        "flip_steps": FLIP_STEPS,
    }
    work = tmp_path_factory.mktemp("scout03")
    (work / "input.json").write_text(json.dumps(payload))
    result = subprocess.run(
        [docker, "run", "--rm", "--network", "none", "-u", "10000", "-w", "/tmp", "-e", "HERMES_HOME=/tmp/data",
         "-v", f"{work / 'input.json'}:/lab/input.json:ro",
         "-v", f"{FIXTURES}:/lab/fixtures:ro",
         "-v", f"{ROLE / 'files/hermes_checks.py'}:/lab/hermes_checks.py:ro",
         "--entrypoint", "python3", IMAGE, "/lab/fixtures/scout03_lab_driver.py"],
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    line = next((x for x in result.stdout.splitlines() if x.startswith("LAB_RESULT ")), None)
    assert line, result.stdout[-3000:] + result.stderr[-3000:]
    return json.loads(line.removeprefix("LAB_RESULT "))


def results(lab: dict[str, Any]) -> list[str]:
    """Tool results of the main sequence, in STEPS order."""
    assert "error" not in lab["scout"], lab["scout"]
    return [text(r) for r in lab["scout"]["results"]]


def test_l01_declaration_applies_and_converges(lab: dict[str, Any], scout: dict[str, Any]) -> None:
    """Every key accepted and read back equal: no perpetual change on the next run."""
    for name, rcs in lab["set"].items():
        assert all(rc == 0 for rc in rcs.values()), (name, rcs)
    for key, value in lab_values(scout).items():
        assert hp.hermes_config_equal(lab["get"][key], value), key


def test_l02_deploy_check_passes_for_every_profile(lab: dict[str, Any]) -> None:
    """The role's mcp check: Scout's policy holds live; Kaféine and Nora have no active MCP server."""
    for name, (rc, out) in lab["check"].items():
        assert rc == 0, (name, out)
    assert "telegram: 11 MCP tools" in lab["check"]["job-search"][1]
    assert "cron: 7 MCP tools" in lab["check"]["job-search"][1]
    assert lab["check"]["default"][1].endswith("no MCP tool")


@pytest.mark.parametrize(
    ("drift", "reason"),
    [
        ("update_without_approval", "kandidat: configuration differs from the declaration"),
        ("gated_server_trusted", "differs from the declaration"),
        ("declared_write_without_approval", "write-capable tools would run without approval: update_candidature"),
        ("cron_gets_gated_server", "cron: MCP servers"),
    ],
)
def test_l03_deploy_check_catches_drift(lab: dict[str, Any], drift: str, reason: str) -> None:
    """A weakened live config fails the check; restored, it passes again."""
    rc, out = lab["check_drift"][drift]
    assert rc != 0
    assert reason in out, out
    assert lab["check_restored"][0] == 0


def test_l04_exposed_tools_per_platform(lab: dict[str, Any]) -> None:
    """Telegram/API/CLI: 7 kandidat reads + 4 gated writes; cron: the 7 reads only; never a denied tool."""
    exposed = lab["scout"]["exposed"]
    full = {f"mcp__kandidat__{t}" for t in READS | AUTO}
    gated = {f"mcp__kandidat_confirm__{t}" for t in CONFIRM}
    for platform in ("telegram", "api_server", "cli"):
        assert set(exposed[platform]) == full | gated, platform
    assert set(exposed["cron"]) == full
    assert set(lab["scout"]["registry_mcp"]) == full | gated


def test_l04_other_profiles_expose_no_mcp_tool(lab: dict[str, Any]) -> None:
    """Kaféine and Nora: zero MCP tools on every platform, with the fake Kandidat up."""
    for name, exposed in lab["others"].items():
        assert all(tools == [] for tools in exposed.values()), (name, exposed)


def test_l05_denied_tools_cannot_execute(lab: dict[str, Any]) -> None:
    """delete_*, get_settings: unknown tools for Hermes, and the server never saw them."""
    for res in [*results(lab)[:3], results(lab)[18], results(lab)[22]]:
        assert "Unknown tool" in res, res
    reached = {c["tool"] for c in lab["calls"]}
    assert not reached & {"delete_cible", "delete_candidature", "get_settings"}


def test_l06_existing_offer_not_duplicated_other_offer_eligible(lab: dict[str, Any]) -> None:
    """Approved each time: same company slug refused; a retry of a new offer refused; a second offer at the same
    company accepted. The created draft carries Kandidat's side effect (today's date), the reason for the gate."""
    res = results(lab)
    assert "already exists" in res[3]
    assert '"statut": "brouillon"' in res[4]
    assert '"date_candidature": "20' in res[4]
    assert "already exists" in res[5]
    assert '"slug": "entreprise-existante-sre"' in res[6]
    assert lab["scout"]["asked"][3:7] == [1, 1, 1, 1]
    creates = [c["args"]["entreprise"] for c in lab["calls"] if c["tool"] == "create_candidature"]
    assert creates[:4] == ["Entreprise Existante", "Nouvelle Offre", "Nouvelle Offre", "Entreprise Existante SRE"]


def test_l07_every_gated_call_asks_once(lab: dict[str, Any]) -> None:
    """Each of the four gated tools, in one session: approved -> runs; refused -> not run; nobody -> not run.

    One approval request per approved or refused call (no approval carried over to the next call), none when
    nobody can answer (fail-closed without prompting), and only approved calls reach the server.
    """
    res, asked = results(lab), lab["scout"]["asked"]
    for first in (7, 10, 14):
        assert asked[first : first + 2] == [1, 1], (first, asked)
        assert asked[first + 2] == 0, (first, asked)
        assert any(word in res[first + 1] for word in BLOCKED), res[first + 1]
        assert any(word in res[first + 2] for word in BLOCKED), res[first + 2]
    assert asked[13] == 1
    reached = [(c["tool"], c["args"]) for c in lab["calls"] if c["tool"] in ("create_cible", "update_candidature",
                                                                                "update_cible")]
    assert reached == [
        ("create_cible", {"nom": "Acme", "categorie": "esn"}),
        ("update_candidature", {"slug": "nouvelle-offre", "statut": "relancee", "commentaire": ""}),
        ("update_candidature", {"slug": "nouvelle-offre", "statut": "envoyee", "commentaire": "Declare par l'utilisateur"}),
        ("update_cible", {"payload": "a"}),
    ]
    assert "Transition de statut non autorisee" in res[10]
    assert '"statut": "envoyee"' in res[13]
    # create_candidature, the fourth gated tool: refused and nobody never reach the server; approved does.
    assert asked[19:22] == [1, 0, 1], asked
    assert any(word in res[19] for word in BLOCKED) and any(word in res[20] for word in BLOCKED)
    assert '"slug": "offre-approuvee"' in res[21]
    creates = [c["args"]["entreprise"] for c in lab["calls"] if c["tool"] == "create_candidature"]
    assert creates[4:] == ["Offre Approuvee"]


def test_l08_embedded_instruction_is_data_and_its_request_still_fails(lab: dict[str, Any]) -> None:
    """Transport/data test, not a model evaluation: an offer text ordering deletions and a new MCP server comes back
    as data, the deletion it asks for is then attempted and is unknown, and tools and config are unchanged."""
    res = results(lab)
    assert "IGNORE TES REGLES" in res[17]
    assert "Unknown tool" in res[18]
    assert lab["scout"]["registry_mcp_after"] == lab["scout"]["registry_mcp"]
    assert lab["scout"]["config_servers_after"] == ["kandidat", "kandidat_confirm"]
    assert not [c for c in lab["calls"] if c["tool"].startswith("delete_")]


def test_l09_lost_connection_is_not_replayed(lab: dict[str, Any]) -> None:
    """The server dies after receiving a write: Hermes reports a failure and does not send it again."""
    assert "error" not in lab["cut"], lab["cut"]
    assert lab["cut"]["asked"] == [1]
    assert [c["args"]["entreprise"] for c in lab["cut_calls"]] == ["Coupure"]
    assert '"statut": "brouillon"' not in text(lab["cut"]["results"][0])


def test_l10_server_down_fails_safe(lab: dict[str, Any]) -> None:
    """Kandidat down: the read returns an error instead of data, and the deploy check fails."""
    assert "error" not in lab["down"], lab["down"]
    res = text(lab["down"]["results"][0])
    assert "error" in res.lower()
    assert "entreprises" not in res
    assert lab["down_check"][0] != 0


def test_l11_lab_used_no_real_secret_or_context(lab: dict[str, Any]) -> None:
    """Synthetic context only."""
    assert json.loads(lab["get"]["agent.environment_hint"]) == FAKE_HINT


def test_l12_server_claiming_read_only_still_gated(lab: dict[str, Any]) -> None:
    """A Kandidat advertising the gated writes as read-only: the deploy check refuses it, and the local cost gate alone
    still asks before every call, in one session: approved -> runs, then refused -> not run (no approval carried
    over), nobody -> not run, for each of the four tools."""
    rc, out = lab["flip_check"]
    assert rc != 0 and "skip the approval gate" in out, out
    flip = lab["flip"]
    assert "error" not in flip, flip
    res = [text(r) for r in flip["results"]]
    assert flip["asked"] == [1, 1, 0] * 4
    for refused in (1, 2, 4, 5, 7, 8, 10, 11):
        assert any(word in res[refused] for word in BLOCKED), (refused, res[refused])
    assert [(c["tool"], c["args"]) for c in lab["flip_calls"]] == [
        ("create_cible", {"nom": "Flip1", "categorie": "esn"}),
        ("update_candidature", {"slug": "entreprise-existante", "statut": "envoyee", "commentaire": ""}),
        ("update_cible", {"payload": "p1"}),
        ("create_candidature", {"entreprise": "Flip Offre A", "cible_id": 1}),
    ]


def test_l13_one_process_profiles_in_turn(lab: dict[str, Any]) -> None:
    """Multiplex emulation: one process, the gateway's own per-turn profile scope, Scout -> Nora -> Kaféine -> Scout.
    Only Scout's turns expose (and can dispatch) Kandidat tools, before and after the other profiles."""
    seq = lab["scoped"]
    assert isinstance(seq, list), seq
    assert [x["profile"] for x in seq] == ["job-search", "default", "cafe-ia", "job-search"]
    for turn in (seq[0], seq[3]):
        assert len(turn["exposed"]["telegram"]) == 11 and len(turn["exposed"]["cron"]) == 7, turn["exposed"]
        assert "Entreprise Existante" in text(turn["list_cibles"])
    for turn in (seq[1], seq[2]):
        assert turn["exposed"] == {"telegram": [], "cron": []}, turn
        # Not just hidden from the model: under their scope the registry does not know the tool.
        assert "Unknown tool: mcp__kandidat__list_cibles" in turn["list_cibles"], turn
