"""M4 — Scout (profile job-search): prepared in M4.2, activated in M4.3 by its entry in hermes_profiles.

Declaration, identity, SOUL.md, private professional context, tools, cron
drafts, preflight and rollback. Everything runs against throwaway directories,
fake tokens, a synthetic context and a fake `docker`/`ss` on PATH; nothing
reaches hermes-30 and no real vault value is read. The lab tests run the real
Hermes image, offline and throwaway, when it is present locally.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
import test_m2_cafe_ia as m2
import yaml
from conftest import (
    ANSIBLE_PLAYBOOK,
    FAKE_TOKEN,
    FAKE_TOKEN_2,
    REPO,
    ROLE,
    RunTasks,
    recap,
)
from test_m2_cafe_ia import (
    FAKE_TAVILY,
    FAKE_TOKEN_3,
    GROUP_VARS,
    HERMES,
    HERMES_TOOLSETS,
    SENSITIVE,
    TASKS,
    assert_fails_quietly,
    calls,
    meminfo,
    snapshot,
    validate,
)
from test_m2_cafe_ia import FAKE_DOCKER_M3, IMAGE

sys.path.insert(0, str(ROLE / "filter_plugins"))

import hermes_profiles as hp

data_dir = m2.data_dir
fake_pve = m2.fake_pve

SCOUT_SRC = ROLE / "files/profiles/job-search"
SOUL = SCOUT_SRC / "SOUL.md"
PREFLIGHT = HERMES / "ansible/m4-preflight.yml"
ROLLBACK = HERMES / "ansible/m4-rollback.yml"
BOT_CHECK = TASKS / "candidate_bot_identity.yml"
DRAFTS = HERMES / "cron-drafts/job-search.yml"
FAKE_TOKEN_4 = "444444444:FAKE-token-for-tests-ONLY-dddddddddddd"
FAKE_TAVILY_4 = "tvly-FAKE-scout-for-tests-only"
FAKE_USERNAME = "scout_FAKE00_bot"
# Synthetic, multi-line, accented: shaped like the real context, carrying none of it.
FAKE_HINT = (
    "Contexte professionnel SYNTHETIQUE-M4-TEST :\n"
    "- Parcours : marqueur-parcours-fictif, « guillemets » et accents éàç.\n"
    "- Critères : marqueur-criteres-fictif.\n"
    "Ces informations sont fictives."
)
HINT_MARKERS = ("SYNTHETIQUE-M4-TEST", "marqueur-parcours-fictif", "marqueur-criteres-fictif")
ALLOWED = {"web", "skills", "memory", "session_search", "todo", "clarify"}
PLATFORMS = ("telegram", "api_server", "cli", "cron")
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
# Personal facts of the real context: none may be published in clear in what Scout ships.
# Generic shapes in clear; the specific facts (certifications, stacks, companies, file names of the
# real context) only as sha256 prefixes of one- and two-word lowercase phrases: listing them in a
# public test would publish what the test guards.
# A CEFR level (A1-C2) is a personal fact too: the public files grade against "the declared level".
PRIVATE_SHAPES = re.compile(r"Xavier|\b\d{1,2} ans\b|depuis (19|20)\d\d|\b[ABC][12]\b", re.IGNORECASE)
PRIVATE_HASHES = {
    "cc35c048b250c73f",
    "a80bc956a3b25658",
    "0ffa85ee30ca52cb",
    "8dfe5e6cf73b1d6b",
    "12a5d18ee896e599",
    "4f93c88d5199fadd",
    "47ae238e02472def",
    "169726cabaeb6843",
    "ed962b75355d9b22",
    "de75f24335d8115e",
    "1d4b6289382b90c6",
    "65a82d8221b24c36",
}


def private_fact(text: str) -> str | None:
    """Return what looks like a fact of the real professional context, or None."""
    shape = PRIVATE_SHAPES.search(text)
    if shape:
        return shape.group(0)
    words = re.findall(r"[a-z0-9-]+", text.lower())
    for phrase in [*words, *(f"{a} {b}" for a, b in pairwise(words))]:
        if hashlib.sha256(phrase.encode()).hexdigest()[:16] in PRIVATE_HASHES:
            return f"<hashed marker {hashlib.sha256(phrase.encode()).hexdigest()[:16]}>"
    return None


@pytest.fixture(scope="module")
def group_vars() -> dict[str, Any]:
    """The hermes group_vars, as written (vault references left unresolved)."""
    return yaml.safe_load(GROUP_VARS.read_text())


@pytest.fixture(scope="module")
def scout(group_vars: dict[str, Any]) -> dict[str, Any]:
    """The prepared job-search declaration."""
    return group_vars["hermes_profile_job_search"]


@pytest.fixture(scope="module")
def m43_ports(group_vars: dict[str, Any]) -> dict[str, int]:
    """Reserved ports as M4.3 found them on hermes-30: tech-watch (8643) was still declared."""
    return group_vars["hermes_profile_reserved_ports"] | {"tech-watch": 8643}


@pytest.fixture(scope="module")
def deployed(group_vars: dict[str, Any]) -> list[dict[str, Any]]:
    """cafe-ia and tech-watch as deployed at M4.3, fake secrets in place of the vault references.

    M7 retired Néo's declaration. Its frozen stand-in is Kaféine's declaration (the very matrix Néo shared, D5 and
    M3.3.1) under Néo's id, port and bot name: the M4.3 scenarios on hermes-30 stay reproducible as history.
    """
    cafe = group_vars["hermes_profile_cafe_ia"] | {
        "telegram_bot_token": FAKE_TOKEN_2,
        "env": {"TAVILY_API_KEY": FAKE_TAVILY},
    }
    neo = group_vars["hermes_profile_cafe_ia"] | {
        "name": "tech-watch",
        "description": "Néo — veille technique (M3, retire en M7).",
        "api_server_port": 8643,
        "telegram_bot_token": FAKE_TOKEN_3,
        "telegram_bot_username": "neo_FAKE00_bot",
        "env": {"TAVILY_API_KEY": "tvly-x"},
    }
    neo["config"] = neo["config"] | {"agent.environment_hint": "contexte de Néo"}
    return [cafe, neo]


def resolved(scout: dict[str, Any], token: str = FAKE_TOKEN_4, username: str = FAKE_USERNAME) -> dict[str, Any]:
    """The job-search declaration with fakes in place of the vault keys, the bot name and the context."""
    return scout | {
        "telegram_bot_token": token,
        "telegram_bot_username": username,
        "env": {"TAVILY_API_KEY": FAKE_TAVILY_4},
        "config": scout["config"] | {"agent.environment_hint": FAKE_HINT},
    }


def scout_block() -> str:
    """The group_vars text of Scout's declaration, comments included."""
    return GROUP_VARS.read_text().split("# Scout —")[1].split("# ====")[0]


# --- Identite -----------------------------------------------------------------


def test_s01_identity_and_port(group_vars: dict[str, Any], scout: dict[str, Any]) -> None:
    """Scout keeps the technical id job-search and its reserved port 8645."""
    assert scout["name"] == "job-search"
    assert scout["description"].startswith("Scout — recherche d'emploi")
    assert scout["api_server_port"] == group_vars["hermes_profile_reserved_ports"]["job-search"] == 8645


def test_s01_active_after_cafe_ia(group_vars: dict[str, Any]) -> None:
    """M4.3 appended job-search after cafe-ia and tech-watch; since M7 (Néo retired) it follows cafe-ia; no daily-life."""
    assert group_vars["hermes_profiles"] == [
        "{{ hermes_profile_cafe_ia }}",
        "{{ hermes_profile_job_search }}",
    ]


def test_s01_no_charlie_and_current_mission_numbering() -> None:
    """The former name is gone; the comment says M4 = job-search, M5 = default becomes Nora."""
    for text in (scout_block(), SOUL.read_text(), PREFLIGHT.read_text(), ROLLBACK.read_text(), DRAFTS.read_text()):
        assert not re.search(r"charlie", text, re.IGNORECASE)
    text = GROUP_VARS.read_text()
    assert "M4 daily-life" not in text and "M5 job-search" not in text
    assert "M4 job-search" in text and "en Nora" in text and "Maya" not in text


def test_s02_bot_username_is_the_confirmed_literal(scout: dict[str, Any]) -> None:
    """The BotFather name confirmed by the operator, written as is (like Kaféine's): getMe always runs."""
    assert scout["telegram_bot_username"] == "scout_r64gnb_bot"
    assert re.fullmatch(r"scout_[A-Za-z0-9]{6}_bot", scout["telegram_bot_username"])
    assert "hermes_job_search_telegram_bot_username" not in GROUP_VARS.read_text()


def test_s02_getme_applies_once_the_bot_name_is_set(
    run_tasks: RunTasks, group_vars: dict[str, Any], scout: dict[str, Any]
) -> None:
    """Resolved, the declaration passes and profile.yml's getMe check applies; a malformed name is refused."""
    assert validate(run_tasks, group_vars, [resolved(scout)]).returncode == 0
    getme = next(t for t in yaml.safe_load((TASKS / "profile.yml").read_text()) if "token belongs" in t["name"])
    assert "hermes_profile.telegram_bot_username is defined" in getme["when"]
    assert_fails_quietly(validate(run_tasks, group_vars, [resolved(scout, username="scout_bot")]))


# --- Configuration --------------------------------------------------------------


def test_s03_dedicated_vault_references(group_vars: dict[str, Any], scout: dict[str, Any]) -> None:
    """Token, Tavily key and context: Scout's own vault keys, none shared with default or Kaféine (Néo retired in M7)."""
    assert scout["telegram_bot_token"] == "{{ vault_hermes_job_search_telegram_bot_token }}"
    assert scout["env"] == {"TAVILY_API_KEY": "{{ vault_hermes_job_search_tavily_api_key }}"}
    assert "vault_hermes_job_search_environment_hint" in scout["config"]["agent.environment_hint"]
    others = [group_vars["hermes_profile_cafe_ia"]]
    for other in others:
        assert scout["telegram_bot_token"] != other["telegram_bot_token"]
        assert scout["env"]["TAVILY_API_KEY"] != other["env"]["TAVILY_API_KEY"]
    assert scout["telegram_bot_token"] != group_vars["hermes_telegram_bot_token"]
    assert not re.search(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b|tvly-[A-Za-z0-9]", GROUP_VARS.read_text())


def test_s03_tavily_backend_no_mcp_no_cron(scout: dict[str, Any]) -> None:
    """Tavily backend; no MCP server, no cron key, Kandidat named nowhere in the declaration."""
    cfg = scout["config"]
    assert cfg["web.backend"] == "tavily"
    assert not any(key.startswith(("mcp", "cron")) for key in cfg)
    assert "no_mcp" in cfg["platform_toolsets.telegram"]
    assert "kandidat" not in json.dumps(scout).lower()


def test_s03_no_telegram_conflict_with_the_deployed_bots(
    run_tasks: RunTasks,
    group_vars: dict[str, Any],
    scout: dict[str, Any],
    deployed: list[dict[str, Any]],
    m43_ports: dict[str, int],
) -> None:
    """Four gateways together (M4.3): Scout can reuse neither default's, Kaféine's nor Néo's token."""
    ports = {"hermes_profile_reserved_ports": m43_ports}
    assert validate(run_tasks, group_vars, [*deployed, resolved(scout)], **ports).returncode == 0
    for token in (FAKE_TOKEN, FAKE_TOKEN_2, FAKE_TOKEN_3):
        assert_fails_quietly(validate(run_tasks, group_vars, [*deployed, resolved(scout, token=token)], **ports))


def test_s03_empty_tavily_key_is_refused(
    run_tasks: RunTasks, group_vars: dict[str, Any], scout: dict[str, Any]
) -> None:
    """An empty Tavily key would silently remove web search: refused before any write."""
    bad = resolved(scout)
    bad["env"] = {"TAVILY_API_KEY": " "}
    assert_fails_quietly(validate(run_tasks, group_vars, [bad]))


@pytest.mark.parametrize(
    "key",
    ["web.backend", "platform_toolsets.telegram", "agent.disabled_toolsets", "skills.write_approval"],
)
def test_s03_config_values_converge(scout: dict[str, Any], key: str) -> None:
    """What `config set` stores reads back equal: no perpetual change."""
    value = scout["config"][key]
    stored = yaml.safe_load(hp.hermes_config_arg(value))
    assert stored == value
    assert hp.hermes_config_equal(json.dumps(stored), value)


# --- SOUL.md ------------------------------------------------------------------


def test_s04_soul_names_scout_and_is_its_own() -> None:
    """A dedicated SOUL.md, distinct from Kaféine's (and from Néo's, retired in M7), in French."""
    soul = SOUL.read_text()
    assert soul.startswith("Tu es **Scout**")
    for other in ("cafe-ia",):
        assert soul != (ROLE / f"files/profiles/{other}/SOUL.md").read_text()
    assert "Réponds en **français**" in soul


def test_s04_domains_and_quality_over_quantity() -> None:
    """Five domains; quality first, an empty week beats weak offers."""
    soul = SOUL.read_text()
    assert re.findall(r"^### (\d)\. (.+)$", soul, re.MULTILINE) == [
        ("1", "Recherche d'emploi"),
        ("2", "Analyse des offres"),
        ("3", "Recherche géographique"),
        ("4", "Compétences linguistiques"),
        ("5", "Accompagnement professionnel"),
    ]
    assert "une semaine sans offre réellement pertinente vaut mieux" in soul
    for field in ("DevOps", "Platform Engineering", "Kubernetes", "backend Python", "backend Java / Spring"):
        assert field in soul, field


def test_s04_geography_guadeloupe_first() -> None:
    """P1 Guadeloupe, P2 full remote France, P3 selective international; remote compatibility qualified."""
    geo = SOUL.read_text().split("### 3. Recherche géographique")[1].split("### 4.")[0]
    assert geo.index("P1 : Guadeloupe") < geo.index("P2 : full remote France") < geo.index("P3 : international")
    assert "sélective" in geo
    assert "ne signifie pas automatiquement" in geo
    for verdict in ("**Confirmé**", "**À vérifier**", "**Incompatible**"):
        assert verdict in geo


def test_s04_languages_graded_against_the_private_context() -> None:
    """Graded against the level the private context declares, never excluded outright, never overstated."""
    lang = SOUL.read_text().split("### 4. Compétences linguistiques")[1].split("### 5.")[0]
    assert "contexte professionnel" in lang and "**ce niveau déclaré**" in lang
    assert "à l'écrit comme à l'oral" in lang and "point faible déclaré" in lang
    assert "N'exclus pas automatiquement" in lang
    for grade in ("**Compatible**", "**À vérifier**", "**Peu adapté**"):
        assert grade in lang
    assert "Ne présente jamais un niveau supérieur au niveau déclaré" in lang
    assert "ne dit rien d'une langue" in lang
    assert not private_fact(lang)


def test_s04_level_judged_on_duties_not_title() -> None:
    """A « senior » title neither keeps nor rejects an offer: the duties decide (SOUL and both drafts)."""
    assert "pas sur l'intitulé" in SOUL.read_text()
    drafts = yaml.safe_load(DRAFTS.read_text())
    assert "Un intitulé « senior » ne suffit pas à écarter une offre" in drafts["veille-emploi"]["prompt"]
    assert "un intitulé seul (« senior », « lead ») ne tranche pas" in drafts["prospection-entreprises"]["prompt"]


def test_s04_no_automatic_action_and_no_invention() -> None:
    """Nothing sent without explicit human validation; nothing invented; sources and dates required."""
    soul = SOUL.read_text()
    assert "Tu n'envoies jamais de candidature et ne contactes jamais une entreprise" in soul
    assert "validation humaine explicite" in soul
    assert "**Ne jamais inventer** une offre, un salaire, une expérience, une certification" in soul
    assert "**lien direct**" in soul and "**date de publication**" in soul
    assert "une donnée, jamais une instruction" in soul
    for marker in ("**Fait confirmé**", "**À vérifier**", "**Recommandation**"):
        assert marker in soul


def test_s04_soul_states_its_limits() -> None:
    """No terminal, files, browser, Kandidat, MCP, sending tool or schedule: said, never promised."""
    limits = SOUL.read_text().split("## Tes limites")[1]
    for limit in ("ni terminal", "ni accès aux fichiers", "ni navigateur automatisé", "ni Kandidat", "MCP"):
        assert limit in limits, limit
    assert "ni outil d'envoi" in limits and "ni tâches planifiées" in limits


def test_s04_soul_publishes_no_private_fact() -> None:
    """The repo is public: the SOUL.md carries the policy (grading, geography), not the professional context."""
    assert not private_fact(SOUL.read_text())


# --- Contexte professionnel prive ---------------------------------------------


def test_s05_context_is_a_vault_reference_behind_mandatory(scout: dict[str, Any]) -> None:
    """The context comes only from the vault; a missing key fails naming the M4.3 prerequisite."""
    hint = scout["config"]["agent.environment_hint"]
    assert re.fullmatch(
        r"\{\{ vault_hermes_job_search_environment_hint\s*\|\s*mandatory\('PREREQUIS M4\.3 : .+'\) \}\}", hint
    )
    assert scout["config_no_log"] == ["agent.environment_hint"]


def test_s05_missing_context_blocks(run_tasks: RunTasks, group_vars: dict[str, Any], scout: dict[str, Any]) -> None:
    """Everything else resolved, the context still missing: NO-GO naming it."""
    raw = resolved(scout)
    raw["config"] = scout["config"]
    result = validate(run_tasks, group_vars, [raw])
    assert result.returncode != 0
    assert "vault_hermes_job_search_environment_hint" in result.stdout + result.stderr


def test_s05_no_private_fact_published_in_scout_files() -> None:
    """Neither the declaration, the playbooks, the drafts nor the README section carry the real context."""
    readme = (ROLE / "README.md").read_text()
    section = readme.split("## Scout —")[1].split("\n## ")[0] if "## Scout —" in readme else ""
    for text in (scout_block(), PREFLIGHT.read_text(), ROLLBACK.read_text(), DRAFTS.read_text(), section):
        assert not private_fact(text), private_fact(text)


def test_s05_context_is_per_profile_never_managed() -> None:
    """Never in the managed layer nor HERMES_ENVIRONMENT_HINT: both would reach every profile."""
    assert "environment_hint" not in (ROLE / "templates/config.yaml.j2").read_text()
    assert "environment_hint" not in (ROLE / "templates/hermes.env.j2").read_text()
    assert "HERMES_ENVIRONMENT_HINT" not in (ROLE / "templates/docker-compose.yml.j2").read_text()


def test_s05_config_no_log_must_name_declared_keys(
    run_tasks: RunTasks, group_vars: dict[str, Any], scout: dict[str, Any]
) -> None:
    """A misspelt masked key would mask nothing: refused."""
    bad = resolved(scout) | {"config_no_log": ["agent.environment_hnt"]}
    assert_fails_quietly(validate(run_tasks, group_vars, [bad]))


FAKE_DOCKER_CONFIG = r'''#!/usr/bin/env python3
"""Fake `docker exec ... hermes -p <p> config get|set`: a key store, set calls recorded."""
import json, os, sys
from pathlib import Path
store_file = Path(os.environ["FAKE_STORE"])
store = json.loads(store_file.read_text())
args = sys.argv[2:]
while args and args[0] in ("-u", "-e"):
    args = args[2:]
cmd = args[1:]
assert cmd[:2] == ["hermes", "-p"] and cmd[3] == "config", cmd
key = cmd[5]
if cmd[4] == "get":
    if key not in store["values"]:
        sys.exit(1)
    print(json.dumps(store["values"][key]))
elif cmd[4] == "set":
    store["sets"].append([key, cmd[6]])
    store_file.write_text(json.dumps(store))
    if key in store.get("fail", []):
        print("config set failed for " + key + ": " + cmd[6])
        sys.exit(3)
'''


def run_config_tasks(tmp_path: Path, profile: dict[str, Any], current: dict[str, Any], fail: list[str]) -> Any:
    """Run the REAL config read/set tasks of profile.yml, verbatim, against a fake key store, at -vvv."""
    tasks = [
        t
        for t in yaml.safe_load((TASKS / "profile.yml").read_text())
        if t["name"].split(" profile ")[0]
        in (
            "Read the config keys of",
            "Set the config keys of",
        )
    ]
    assert len(tasks) == 2
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "docker").write_text(FAKE_DOCKER_CONFIG.replace("#!/usr/bin/env python3", f"#!{sys.executable}"))
    (bindir / "docker").chmod(0o755)
    store = tmp_path / "store.json"
    store.write_text(json.dumps({"values": current, "sets": [], "fail": fail}))
    (tmp_path / "vars.json").write_text(
        json.dumps({"hermes_profile": profile, "hermes_puid": 1000, "ansible_python_interpreter": sys.executable})
    )
    (tmp_path / "play.yml").write_text(
        yaml.safe_dump([{"hosts": "localhost", "connection": "local", "gather_facts": False, "tasks": tasks}])
    )
    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    result = subprocess.run(
        [str(ANSIBLE_PLAYBOOK), "-i", "localhost,", "play.yml", "-e", "@vars.json", "-vvv"],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "FAKE_STORE": str(store),
            "ANSIBLE_CONFIG": str(tmp_path / "ansible.cfg"),
            "ANSIBLE_FILTER_PLUGINS": str(ROLE / "filter_plugins"),
            "ANSIBLE_LOCAL_TEMP": str(tmp_path / ".ansible-tmp"),
            "ANSIBLE_NOCOLOR": "1",
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, json.loads(store.read_text())["sets"]


def test_s05_context_reaches_config_set_verbatim_and_never_the_output(tmp_path: Path, scout: dict[str, Any]) -> None:
    """Real profile.yml tasks at -vvv: the multi-line context is set byte for byte, and printed nowhere.

    The previous value (read back by `config get`) is private too: neither shows. Public keys keep
    their usual output.
    """
    profile = resolved(scout)
    old = FAKE_HINT.replace("SYNTHETIQUE-M4-TEST", "ANCIEN-CONTEXTE-M4-TEST")
    result, sets = run_config_tasks(tmp_path, profile, {"agent.environment_hint": old}, fail=[])
    out = result.stdout + result.stderr
    assert result.returncode == 0, out[-3000:]
    assert ["agent.environment_hint", FAKE_HINT] in sets
    for marker in (*HINT_MARKERS, "ANCIEN-CONTEXTE-M4-TEST", "éàç"):
        assert marker not in out, marker
    assert "item=web.backend" in out and '"tavily"' in out


def test_s05_context_stays_hidden_when_config_set_fails(tmp_path: Path, scout: dict[str, Any]) -> None:
    """A failing `config set` (whose error echoes the value) still prints nothing of the context."""
    result, _ = run_config_tasks(tmp_path, resolved(scout), {}, fail=["agent.environment_hint"])
    out = result.stdout + result.stderr
    assert result.returncode != 0
    for marker in HINT_MARKERS:
        assert marker not in out, marker
    assert "censored" in out


def test_s05_tasks_reading_the_profile_mask_per_key() -> None:
    """Both config tasks evaluate no_log per item against config_no_log."""
    tasks = {t["name"]: t for t in yaml.safe_load((TASKS / "profile.yml").read_text())}
    read = tasks["Read the config keys of profile {{ hermes_profile.name }}"]
    write = tasks["Set the config keys of profile {{ hermes_profile.name }}"]
    assert read["no_log"] == "{{ item.key in hermes_profile.config_no_log | default([]) }}"
    assert write["no_log"] == "{{ item.item.key in hermes_profile.config_no_log | default([]) }}"
    assert read["loop_control"]["label"] == "{{ item.key }}"


# --- Securite : outils ----------------------------------------------------------


def test_s06_tool_matrix_is_kafeines(scout: dict[str, Any], group_vars: dict[str, Any]) -> None:
    """Same least-privilege matrix as Kaféine (and Néo, D5, M3.3.1, until M7), on the four platforms."""
    cfg = scout["config"]
    allowed = set(cfg["platform_toolsets.telegram"]) - {"no_mcp"}
    denied = set(cfg["agent.disabled_toolsets"])
    assert allowed == ALLOWED
    assert (allowed | denied) <= HERMES_TOOLSETS
    assert SENSITIVE - {"browser"} <= denied
    assert {"terminal", "file", "code_execution", "cronjob", "kanban", "delegation", "computer_use"} <= denied
    assert "browser" not in denied and "browser" not in cfg["platform_toolsets.telegram"]
    for platform in PLATFORMS:
        assert cfg[f"platform_toolsets.{platform}"] == cfg["platform_toolsets.telegram"]
    for other in ("hermes_profile_cafe_ia",):
        assert cfg["agent.disabled_toolsets"] == group_vars[other]["config"]["agent.disabled_toolsets"]
        assert cfg["platform_toolsets.telegram"] == group_vars[other]["config"]["platform_toolsets.telegram"]
    assert cfg["skills.write_approval"] is True


LAB_DRIVER = r'''
import json, os, subprocess
CFG, SOUL, CHECKS, ALLOWED, DENIED, DRAFT = json.loads(os.environ["LAB_INPUT"])
def run(*argv, **kw):
    return subprocess.run(list(argv), capture_output=True, text=True, **kw)
os.makedirs("/tmp/data", exist_ok=True)
out = {"create": {n: run("hermes", "profile", "create", n, "--no-alias").returncode for n in ("job-search", "cafe-ia")}}
out["set"] = {k: run("hermes", "-p", "job-search", "config", "set", k, v).returncode for k, v in CFG.items()}
out["get"] = {k: run("hermes", "-p", "job-search", "config", "get", k, "--json").stdout for k in CFG}
with open("/tmp/data/profiles/job-search/SOUL.md", "w", encoding="utf-8") as f:
    f.write(SOUL)
home = "/tmp/data/profiles/job-search"
env = dict(os.environ, HERMES_HOME=home)
r = run("python3", "-c", CHECKS, "toolsets", ALLOWED, DENIED, "true", env=env, cwd="/opt/hermes")
out["check"] = [r.returncode, r.stdout.strip()]
probe = """
import json, logging
logging.disable(logging.CRITICAL)
from hermes_cli.config import load_config
from hermes_cli.tools_config import _get_platform_tools
from run_agent import AIAgent
from agent.system_prompt import build_system_prompt
from tools import web_tools
from cron.scheduler import _resolve_cron_enabled_toolsets, _resolve_cron_disabled_toolsets
cfg = load_config()
res = {"backend": web_tools._get_backend(), "tools": {}}
for p in ("telegram", "api_server", "cli", "cron"):
    agent = AIAgent(base_url="http://127.0.0.1:9/v1", api_key="x", model="deepseek-v4-flash", platform=p,
                    quiet_mode=True, enabled_toolsets=sorted(_get_platform_tools(cfg, p)),
                    disabled_toolsets=cfg["agent"]["disabled_toolsets"])
    res["tools"][p] = sorted(agent.valid_tool_names)
job = {"id": "abcdef012345", "name": "veille-emploi"}
agent = AIAgent(base_url="http://127.0.0.1:9/v1", api_key="x", model="deepseek-v4-flash", platform="cron",
                quiet_mode=True, enabled_toolsets=_resolve_cron_enabled_toolsets(job, cfg),
                disabled_toolsets=_resolve_cron_disabled_toolsets(cfg))
res["cron_run_tools"] = sorted(agent.valid_tool_names)
agent = AIAgent(base_url="http://127.0.0.1:9/v1", api_key="x", model="deepseek-v4-flash", platform="telegram",
                quiet_mode=True)
res["prompt"] = build_system_prompt(agent)
print("PROBE " + json.dumps(res))
"""
def probe_in(path):
    r = run("python3", "-c", probe, env=dict(os.environ, HERMES_HOME=path), cwd="/opt/hermes")
    line = next((x for x in r.stdout.splitlines() if x.startswith("PROBE ")), None)
    return json.loads(line.removeprefix("PROBE ")) if line else "ERROR " + r.stderr[-800:]
out["scout"] = probe_in(home)
out["others"] = {n: probe_in(p)["prompt"] if not isinstance(probe_in(p), str) else "ERROR"
                 for n, p in (("default", "/tmp/data"), ("cafe-ia", "/tmp/data/profiles/cafe-ia"))}
# --continuity (context_from: self), on the scheduler's own code: what reaches run N+1.
cont = """
import json, os, sys
from cron import scheduler as s
from cron.jobs import get_cron_output_dir
draft = sys.argv[1]
job = {"id": "abcdef012345", "name": "veille-emploi", "prompt": draft, "context_from": ["self"],
       "schedule_display": "0 7 * * 1"}
out_dir = get_cron_output_dir() / job["id"]
out_dir.mkdir(parents=True, exist_ok=True)
seen = []
for run_no in (1, 2, 3):
    prompt = s._build_job_prompt(job)
    seen.append([f"REPONSE-RUN-{n}" in prompt for n in (1, 2)])
    # Same layout as run_job's success output (cron/scheduler.py).
    text = f"# Cron Job: veille-emploi\\n\\n**Job ID:** {job['id']}\\n**Run Time:** 2026-10-2{run_no} 07:00:00\\n"
    text += f"**Schedule:** 0 7 * * 1\\n\\n## Prompt\\n\\n{prompt}\\n\\n## Response\\n\\nREPONSE-RUN-{run_no} offre X\\n"
    path = out_dir / f"run{run_no}.md"
    path.write_text(text, encoding="utf-8")
    os.utime(path, (run_no, run_no))
print("CONT " + json.dumps(seen))
"""
r = run("python3", "-c", cont, DRAFT, env=env, cwd="/opt/hermes")
line = next((x for x in r.stdout.splitlines() if x.startswith("CONT ")), None)
out["continuity"] = json.loads(line.removeprefix("CONT ")) if line else "ERROR " + r.stderr[-800:]
print("LAB_RESULT " + json.dumps(out))
'''


@pytest.fixture(scope="module")
def lab(scout: dict[str, Any]) -> dict[str, Any]:
    """Apply Scout's declaration (synthetic context, fake Tavily key) to a throwaway, offline image.

    Same commands as profile.yml; then what Hermes resolves: tools per platform, tools of a real cron
    run, the Telegram system prompt, and the scheduler's --continuity injection.
    """
    docker = shutil.which("docker")
    if (
        not docker
        or subprocess.run([docker, "image", "inspect", IMAGE], capture_output=True, check=False).returncode != 0
    ):
        pytest.skip(f"{IMAGE} not available locally")
    cfg = resolved(scout)["config"]
    payload = json.dumps(
        [
            {k: hp.hermes_config_arg(v) for k, v in cfg.items()},
            SOUL.read_text(),
            (ROLE / "files/hermes_checks.py").read_text(),
            ",".join(sorted(ALLOWED)),
            ",".join(cfg["agent.disabled_toolsets"]),
            yaml.safe_load(DRAFTS.read_text())["veille-emploi"]["prompt"],
        ]
    )
    result = subprocess.run(
        [docker, "run", "--rm", "-i", "--network", "none", "-u", "10000", "-w", "/tmp"]
        + ["-e", "HERMES_HOME=/tmp/data", "-e", "LAB_INPUT", "-e", f"TAVILY_API_KEY={FAKE_TAVILY_4}"]
        + ["--entrypoint", "python3", IMAGE, "-"],
        input=LAB_DRIVER,
        env={**os.environ, "LAB_INPUT": payload},
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    line = next((x for x in result.stdout.splitlines() if x.startswith("LAB_RESULT ")), None)
    assert line, result.stdout[-2000:] + result.stderr[-2000:]
    return json.loads(line.removeprefix("LAB_RESULT "))


def test_s07_lab_config_applies_and_converges(lab: dict[str, Any], scout: dict[str, Any]) -> None:
    """Real image: every key accepted, read back equal (the multi-line context included): no perpetual change."""
    assert lab["create"]["job-search"] == 0
    assert all(rc == 0 for rc in lab["set"].values()), lab["set"]
    for key, value in resolved(scout)["config"].items():
        assert hp.hermes_config_equal(lab["get"][key], value), key
    assert json.loads(lab["get"]["agent.environment_hint"]) == FAKE_HINT


@pytest.mark.parametrize("platform", PLATFORMS)
def test_s07_lab_web_search_and_web_extract_each_exposed(lab: dict[str, Any], platform: str) -> None:
    """M3.3.1 kept: web_search AND web_extract, each checked on its own, on every platform."""
    scout_lab = lab["scout"]
    assert not isinstance(scout_lab, str), scout_lab
    tools = set(scout_lab["tools"][platform])
    assert "web_search" in tools
    assert "web_extract" in tools


def test_s07_lab_exactly_the_nine_tools_everywhere(lab: dict[str, Any]) -> None:
    """Telegram, API, CLI and cron: exactly the nine allowed tools; no browser_*, terminal, file, code, cronjob, MCP."""
    for platform in PLATFORMS:
        tools = set(lab["scout"]["tools"][platform])
        assert tools == EXPECTED_TOOLS, platform
        assert not [t for t in tools if t.startswith(("browser_", "mcp_"))]
        assert not {"terminal", "process", "read_file", "write_file", "patch", "execute_code", "cronjob"} & tools
    assert lab["scout"]["backend"] == "tavily"


def test_s07_lab_cron_run_gets_web_without_memory_or_clarify(lab: dict[str, Any]) -> None:
    """The scheduler's own resolution for a Scout cron run: web tools kept; memory and clarify cut by Hermes policy."""
    assert set(lab["scout"]["cron_run_tools"]) == EXPECTED_TOOLS - {"memory", "clarify"}


def test_s07_lab_deploy_check_passes_tool_by_tool(lab: dict[str, Any]) -> None:
    """The profile.yml check (same script, same arguments) passes and names the nine tools."""
    rc, out = lab["check"]
    assert rc == 0, out
    assert out.split(" | tools: ")[1].split(", ") == sorted(EXPECTED_TOOLS)


def test_s07_lab_context_reaches_scout_only_without_file_tool(lab: dict[str, Any]) -> None:
    """Scout's Telegram system prompt carries its SOUL.md and the (synthetic) context; default's and Kaféine's do not."""
    prompt = lab["scout"]["prompt"]
    assert SOUL.read_text().splitlines()[0] in prompt
    for marker in HINT_MARKERS:
        assert marker in prompt, marker
    for name, other in lab["others"].items():
        assert not other.startswith("ERROR"), name
        assert "SYNTHETIQUE-M4-TEST" not in other and "Tu es **Scout**" not in other, name


def test_s07_lab_continuity_loses_the_previous_answer(lab: dict[str, Any]) -> None:
    """--continuity measured on the scheduler: run 2 sees run 1's answer, run 3 does NOT see run 2's.

    The output file starts with the whole built prompt (previous injection included) and the
    injection keeps its first 8000 characters: from run 3 on, only a stale fragment of an older
    answer survives. Why the drafts deduplicate with session_search instead (continuity: false).
    """
    seen = lab["continuity"]
    assert not isinstance(seen, str), seen
    assert seen[0] == [False, False]
    assert seen[1][0] is True
    assert seen[2][1] is False


# --- Crons emploi : brouillons ----------------------------------------------------

ORIGINAL_SCHEDULES = {"veille-emploi": "0 7 * * 1", "prospection-entreprises": "0 7 * * 3"}


@pytest.fixture(scope="module")
def drafts() -> dict[str, Any]:
    """The two cron drafts."""
    return yaml.safe_load(DRAFTS.read_text())


def test_s08_two_drafts_same_schedules_and_delivery(drafts: dict[str, Any], group_vars: dict[str, Any]) -> None:
    """Exactly the two job crons, default's UTC schedules kept, delivered to the allowlisted chat by Scout."""
    assert set(drafts) == set(ORIGINAL_SCHEDULES)
    for name, draft in drafts.items():
        assert draft["schedule"] == ORIGINAL_SCHEDULES[name]
        assert draft["deliver"] == f"telegram:{group_vars['hermes_telegram_allowed_users']}"
        assert draft["continuity"] is False
        assert set(draft) == {"schedule", "deliver", "continuity", "prompt"}


@pytest.mark.parametrize("name", list(ORIGINAL_SCHEDULES))
def test_s08_drafts_need_no_kandidat_shell_file_or_browser(drafts: dict[str, Any], name: str) -> None:
    """Only web_search/web_extract/session_search: no Kandidat tool, shell command, local path or script."""
    prompt = drafts[name]["prompt"]
    assert "web_search" in prompt and "web_extract" in prompt and "session_search" in prompt
    assert not re.search(
        r"mcp__|list_cibles|search_candidatures|create_cible|create_candidature|get_stats|"
        r"/opt/|\.py\b|\bcurl\b|\bpython3\b|playwright|chrome|sitemap|\bcd\b|write_file|read_file|terminal\s*:",
        prompt,
        re.IGNORECASE,
    )
    assert "Ne réponds jamais [SILENT]" in prompt
    assert "Ne crée et ne modifie aucun skill" in prompt


@pytest.mark.parametrize("name", list(ORIGINAL_SCHEDULES))
def test_s08_drafts_publish_no_private_fact(drafts: dict[str, Any], name: str) -> None:
    """Level, history and excluded companies come from the private context, never the public prompt."""
    assert not private_fact(drafts[name]["prompt"])
    assert "contexte professionnel" in drafts[name]["prompt"]


def test_s08_veille_keeps_its_logic(drafts: dict[str, Any]) -> None:
    """Families A/B/C, sources, 30-day freshness, geography, 2-3 offers, reasons and reserves."""
    prompt = drafts["veille-emploi"]["prompt"]
    for kept in (
        "A. DevOps",
        "B. Développeur Python",
        "C. Développeur Java",
        "remotefr.com",
        "free-work.com",
        "leremote.fr",
        "France Travail",
        "moins de 30 jours",
        "UNIQUEMENT en télétravail total",
        "Retiens 2 offres, 3 au maximum",
        "A avant B avant C",
        "N'invente jamais une URL",
        "réserves",
    ):
        assert kept in prompt, kept
    assert "Tu n'enregistres rien nulle part" in prompt
    assert "applique la grille de ton SOUL au niveau déclaré dans ton" in prompt
    assert "un axe de progression" in prompt


def test_s08_prospection_keeps_its_logic(drafts: dict[str, Any]) -> None:
    """Companies without offers, sourced signals, Guadeloupe or full remote, 3 to 8, approach; nothing created or sent."""
    prompt = drafts["prospection-entreprises"]["prompt"]
    for kept in (
        "même lorsqu'elles n'ont pas publié d'offre",
        "source vérifiable (URL)",
        "Guadeloupe (idéal)",
        "3 à 8",
        "recommandation d'approche",
        "Tu ne crées rien et tu ne contactes personne",
    ):
        assert kept in prompt, kept


def test_s08_drafts_are_read_by_nothing() -> None:
    """No playbook, task or template uses the drafts; no Scout path writes jobs.json or creates a cron."""
    ansible = HERMES / "ansible"
    for path in [*ansible.rglob("*.yml"), *ansible.rglob("*.j2")]:
        code = "\n".join(line for line in path.read_text().splitlines() if not line.lstrip().startswith("#"))
        assert "cron-drafts" not in code, path
    for path in (PREFLIGHT, ROLLBACK, BOT_CHECK):
        assert not re.search(r"\bcron\s+(create|add|edit|resume|pause|run)\b|jobs\.json", path.read_text()), path
    assert not [p for p in SCOUT_SRC.rglob("*") if "cron" in p.name or p.name.endswith("jobs.json")]


# --- Preflight M4 -------------------------------------------------------------

FAKE_DOCKER_M4 = FAKE_DOCKER_M3.replace(
    'while args and args[0] in ("-u", "-e"):\n    args = args[2:]',
    'while args and args[0] in ("-u", "-e", "-i"):\n'
    '    args = args[1:] if args[0] == "-i" else args[2:]\n'
    'if "bot-identity" in sys.argv:\n'
    '    Path(os.environ["FAKE_STDIN"]).write_text(sys.stdin.read())',
)
assert FAKE_DOCKER_M4 != FAKE_DOCKER_M3


@pytest.fixture
def m4_host(
    tmp_path: Path, data_dir: Path, fake_pve: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """hermes-30 as M4.3 should find it: default, cafe-ia and tech-watch up; no job-search; 8645 free."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("docker", "ss"):
        (bindir / name).write_text(FAKE_DOCKER_M4.replace("#!/usr/bin/env python3", f"#!{sys.executable}"))
        (bindir / name).chmod(0o755)
    host: dict[str, Any] = {
        "state": tmp_path / "state.json",
        "log": tmp_path / "calls.log",
        "stdin": tmp_path / "stdin.txt",
        "data": data_dir,
        "meminfo": tmp_path / "meminfo",
    }
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_STATE", str(host["state"]))
    monkeypatch.setenv("FAKE_LOG", str(host["log"]))
    monkeypatch.setenv("FAKE_DATA", str(data_dir))
    monkeypatch.setenv("FAKE_STDIN", str(host["stdin"]))
    host["meminfo"].write_text(meminfo(3333, 2123))
    set_m4_state(host)
    return host


def set_m4_state(host: dict[str, Any], job_search: str | None = None, listen: str = "", **extra: Any) -> None:
    """Describe the simulated container: three gateways up, job-search as given."""
    svstat = {
        "gateway-default": "up (pid 160) 99 seconds",
        "gateway-cafe-ia": "up (pid 5012) 99 seconds",
        "gateway-tech-watch": "up (pid 5203) 99 seconds",
    }
    if job_search is not None:
        svstat["gateway-job-search"] = job_search
    host["state"].write_text(json.dumps({"svstat": svstat, "listen": listen, **extra}))


def m4_vars(group_vars: dict[str, Any], host: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Extra vars of a candidate preflight run against the fake host."""
    return {
        "hermes_pf_profile": candidate,
        "hermes_data_dir": str(host["data"]),
        "hermes_telegram_enabled": True,
        "hermes_telegram_bot_token": FAKE_TOKEN,
        "hermes_telegram_allowed_users": "1111111111",
        # As M4.3 found them: tech-watch (8643) still declared on hermes-30.
        "hermes_profile_reserved_ports": group_vars["hermes_profile_reserved_ports"] | {"tech-watch": 8643},
        "hermes_pf_meminfo_path": str(host["meminfo"]),
    }


def candidate_preflight(
    run: RunTasks,
    group_vars: dict[str, Any],
    host: dict[str, Any],
    deployed: list[dict[str, Any]],
    candidate: dict[str, Any],
) -> Any:
    """Run the real profile_preflight.yml for job-search, cafe-ia and tech-watch in the inventory."""
    inventory = host["state"].parent / "inventory.yml"
    inventory.write_text(yaml.safe_dump({"all": {"hosts": {"localhost": {"hermes_profiles": deployed}}}}))
    return run("profile_preflight.yml", m4_vars(group_vars, host, candidate), "-i", str(inventory))


def secrets_of(deployed: list[dict[str, Any]]) -> tuple[str, ...]:
    """Every fake secret in play."""
    return (FAKE_TOKEN, FAKE_TOKEN_2, FAKE_TOKEN_3, FAKE_TOKEN_4, FAKE_TAVILY, FAKE_TAVILY_4, "tvly-x", *HINT_MARKERS)


def test_s09_preflight_playbook_order_and_target() -> None:
    """m4-preflight: default, the deployed profiles, the job-search candidate, then its getMe."""
    tasks = yaml.safe_load(PREFLIGHT.read_text())[0]["tasks"]
    assert [t["ansible.builtin.include_role"]["tasks_from"] for t in tasks] == [
        "preflight.yml",
        "deployed_profiles_preflight.yml",
        "profile_preflight.yml",
        "candidate_bot_identity.yml",
    ]
    assert tasks[1]["vars"] == {"hermes_pf_candidate_name": "job-search"}
    assert tasks[2]["vars"] == tasks[3]["vars"] == {"hermes_pf_profile": "{{ hermes_profile_job_search }}"}


def test_s09_deployed_profiles_probed_but_not_the_candidate(
    run_tasks: RunTasks, m4_host: dict[str, Any], deployed: list[dict[str, Any]]
) -> None:
    """GO: cafe-ia and tech-watch probed (Telegram, cron), job-search never; nothing written, no secret shown."""
    before = snapshot(m4_host["data"])
    result = run_tasks(
        "deployed_profiles_preflight.yml",
        {
            "hermes_pf_candidate_name": "job-search",
            "hermes_profiles": deployed,
            "hermes_data_dir": str(m4_host["data"]),
        },
    )
    assert result.returncode == 0, result.stdout
    assert snapshot(m4_host["data"]) == before
    probed = [" ".join(c) for c in calls(m4_host) if c[0] == "docker"]
    for name in ("cafe-ia", "tech-watch"):
        assert any(f"gateway-{name}" in c for c in probed), name
        assert any(f"HERMES_HOME=/opt/data/profiles/{name}" in c for c in probed), name
    assert not any("job-search" in c for c in probed)
    for secret in secrets_of(deployed):
        assert secret not in result.stdout + result.stderr


@pytest.mark.parametrize("where", ["", "profiles/cafe-ia/", "profiles/tech-watch/", "profiles/job-search/"])
def test_s09_emergency_stop_is_a_no_go(
    run_tasks: RunTasks, m4_host: dict[str, Any], deployed: list[dict[str, Any]], where: str
) -> None:
    """An ESTOP on default, a deployed profile or the candidate stops the deployment."""
    (m4_host["data"] / where).mkdir(parents=True, exist_ok=True)
    (m4_host["data"] / where / "ESTOP").write_text("")
    result = run_tasks(
        "deployed_profiles_preflight.yml",
        {
            "hermes_pf_candidate_name": "job-search",
            "hermes_profiles": deployed,
            "hermes_data_dir": str(m4_host["data"]),
        },
    )
    assert result.returncode != 0


def test_s09_candidate_go_on_a_blank_page(
    run_tasks: RunTasks,
    group_vars: dict[str, Any],
    m4_host: dict[str, Any],
    scout: dict[str, Any],
    deployed: list[dict[str, Any]],
) -> None:
    """GO: job-search absent, 8645 free, memory headroom; nothing written; no token nor context shown."""
    before = snapshot(m4_host["data"])
    result = candidate_preflight(run_tasks, group_vars, m4_host, deployed, resolved(scout))
    assert result.returncode == 0, result.stdout
    assert snapshot(m4_host["data"]) == before
    assert "job-search (port 8645)" in result.stdout
    for secret in secrets_of(deployed):
        assert secret not in result.stdout + result.stderr


@pytest.mark.parametrize("missing", ["token", "tavily", "context"])
def test_s09_candidate_no_go_while_a_prerequisite_is_missing(
    run_tasks: RunTasks,
    group_vars: dict[str, Any],
    m4_host: dict[str, Any],
    scout: dict[str, Any],
    deployed: list[dict[str, Any]],
    missing: str,
) -> None:
    """Each M4.3 prerequisite left as in Git (unresolved) is a NO-GO naming it."""
    candidate = resolved(scout)
    if missing == "token":
        candidate["telegram_bot_token"] = scout["telegram_bot_token"]
        expected = "vault_hermes_job_search_telegram_bot_token"
    elif missing == "tavily":
        candidate["env"] = scout["env"]
        expected = "vault_hermes_job_search_tavily_api_key"
    else:
        candidate["config"] = scout["config"]
        expected = "vault_hermes_job_search_environment_hint"
    result = candidate_preflight(run_tasks, group_vars, m4_host, deployed, candidate)
    assert result.returncode != 0
    assert expected in result.stdout + result.stderr


@pytest.mark.parametrize("token", [FAKE_TOKEN, FAKE_TOKEN_2, FAKE_TOKEN_3], ids=["default", "cafe-ia", "tech-watch"])
def test_s09_candidate_no_go_on_a_shared_token(
    run_tasks: RunTasks,
    group_vars: dict[str, Any],
    m4_host: dict[str, Any],
    scout: dict[str, Any],
    deployed: list[dict[str, Any]],
    token: str,
) -> None:
    """Telegram conflict: refused without printing the token."""
    assert_fails_quietly(candidate_preflight(run_tasks, group_vars, m4_host, deployed, resolved(scout, token=token)))


def test_s09_candidate_no_go_when_job_search_exists_or_port_is_taken(
    run_tasks: RunTasks,
    group_vars: dict[str, Any],
    m4_host: dict[str, Any],
    scout: dict[str, Any],
    deployed: list[dict[str, Any]],
) -> None:
    """A job-search directory, s6 slot or listener on 8645 means it is not a blank page."""
    set_m4_state(m4_host, listen="LISTEN 0 5 127.0.0.1:8645 0.0.0.0:*\n")
    assert_fails_quietly(candidate_preflight(run_tasks, group_vars, m4_host, deployed, resolved(scout)))
    set_m4_state(m4_host, job_search="down (exitcode 0) 5 seconds")
    assert_fails_quietly(candidate_preflight(run_tasks, group_vars, m4_host, deployed, resolved(scout)))
    set_m4_state(m4_host)
    (m4_host["data"] / "profiles/job-search").mkdir(parents=True)
    assert_fails_quietly(candidate_preflight(run_tasks, group_vars, m4_host, deployed, resolved(scout)))


def test_s09_memory_gate_unchanged_and_enforced(
    run_tasks: RunTasks,
    group_vars: dict[str, Any],
    m4_host: dict[str, Any],
    scout: dict[str, Any],
    deployed: list[dict[str, Any]],
) -> None:
    """The 1536 MiB gate is not lowered for Scout: 1200 MiB available is a NO-GO."""
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    assert defaults["hermes_pf_min_available_mib"] == 1536
    assert "min_available" not in PREFLIGHT.read_text()
    m4_host["meminfo"].write_text(meminfo(3333, 1200))
    assert candidate_preflight(run_tasks, group_vars, m4_host, deployed, resolved(scout)).returncode != 0


def test_s09_getme_reads_the_token_from_stdin_only(
    run_tasks: RunTasks, group_vars: dict[str, Any], m4_host: dict[str, Any], scout: dict[str, Any]
) -> None:
    """GO path: the token reaches the check on stdin, never in argv nor in the output; the bot name is passed."""
    result = run_tasks("candidate_bot_identity.yml", m4_vars(group_vars, m4_host, resolved(scout)))
    assert result.returncode == 0, result.stdout
    assert m4_host["stdin"].read_text().strip() == FAKE_TOKEN_4
    call = next(c for c in calls(m4_host) if "bot-identity" in c)
    assert call[call.index("bot-identity") + 1 :][:2] == ["-", FAKE_USERNAME]
    assert FAKE_TOKEN_4 not in m4_host["log"].read_text()
    assert FAKE_TOKEN_4 not in result.stdout + result.stderr
    assert recap(result)["changed"] == 0


def test_s09_getme_refusal_is_a_no_go(
    run_tasks: RunTasks, group_vars: dict[str, Any], m4_host: dict[str, Any], scout: dict[str, Any]
) -> None:
    """A token refused by Telegram or owned by another bot stops the deployment, quietly."""
    set_m4_state(m4_host, python_fails=["bot-identity"])
    result = run_tasks("candidate_bot_identity.yml", m4_vars(group_vars, m4_host, resolved(scout)))
    assert result.returncode != 0
    assert "NO-GO" in result.stdout
    assert FAKE_TOKEN_4 not in result.stdout + result.stderr


def test_s09_stdin_mode_of_the_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """`bot-identity -` reads the token from stdin; an empty one is refused before any network call."""
    sys.path.insert(0, str(ROLE / "files"))
    import io

    import hermes_checks as hc

    monkeypatch.setattr(sys, "stdin", io.StringIO("\n"))
    assert hc.main(["bot-identity", "-", FAKE_USERNAME]) == 1


# --- Rollback M4 --------------------------------------------------------------


def test_s10_rollback_playbook_targets_job_search_only() -> None:
    """m4-rollback: stop job-search, then re-check every other deployed profile (cafe-ia, tech-watch)."""
    tasks = yaml.safe_load(ROLLBACK.read_text())[0]["tasks"]
    assert tasks[0]["ansible.builtin.include_role"]["tasks_from"] == "profile_rollback.yml"
    assert tasks[0]["vars"] == {"hermes_rb_profile_name": "job-search"}
    assert tasks[1]["ansible.builtin.include_role"]["tasks_from"] == "profile_telegram_check.yml"
    assert "reject('eq', 'job-search')" in tasks[1]["loop"]
    assert tasks[1]["loop_control"]["loop_var"] == "hermes_tc_profile_name"


def test_s10_rollback_stops_job_search_only_and_keeps_its_data(
    run_tasks: RunTasks, group_vars: dict[str, Any], m4_host: dict[str, Any]
) -> None:
    """Only `-p job-search gateway stop` mutates; the others are only read; memories and sessions stay."""
    profile = m4_host["data"] / "profiles/job-search"
    (profile / "memories").mkdir(parents=True)
    (profile / "memories/MEMORY.md").write_text("souvenir de Scout\n")
    (profile / "sessions").mkdir()
    (profile / "sessions/s1.json").write_text("{}")
    (profile / "gateway_state.json").write_text(json.dumps({"desired_state": "running", "gateway_state": "running"}))
    set_m4_state(m4_host, job_search="up (pid 888) 60 seconds", listen="LISTEN 0 128 127.0.0.1:8645 0.0.0.0:*")
    before = set(snapshot(m4_host["data"]))
    result = run_tasks(
        "profile_rollback.yml",
        {
            "hermes_rb_profile_name": "job-search",
            "hermes_rb_stop_retries": 2,
            "hermes_rb_stop_delay": 1,
            "hermes_data_dir": str(m4_host["data"]),
            "hermes_profile_reserved_ports": group_vars["hermes_profile_reserved_ports"],
            "hermes_profiles": [],
            "hermes_telegram_enabled": True,
        },
    )
    assert result.returncode == 0, result.stdout
    mutating = [c for c in calls(m4_host) if "stop" in c]
    assert len(mutating) == 1 and mutating[0][-4:] == ["-p", "job-search", "gateway", "stop"]
    assert before <= set(snapshot(m4_host["data"]))
    assert (profile / "memories/MEMORY.md").read_text() == "souvenir de Scout\n"
    assert json.loads((profile / "gateway_state.json").read_text())["desired_state"] == "stopped"


@pytest.mark.parametrize("name", ["cafe-ia", "tech-watch"])
def test_s10_other_profiles_are_rechecked(run_tasks: RunTasks, m4_host: dict[str, Any], name: str) -> None:
    """profile_telegram_check.yml passes for a connected profile and fails for a disconnected one."""
    ok = run_tasks("profile_telegram_check.yml", {"hermes_tc_profile_name": name})
    assert ok.returncode == 0, ok.stdout
    assert recap(ok)["changed"] == 0
    set_m4_state(m4_host, python_fails=[f"gateway-{name}"])
    assert run_tasks("profile_telegram_check.yml", {"hermes_tc_profile_name": name}).returncode != 0


def test_s10_m4_operations_destroy_nothing() -> None:
    """No deletion, token revocation, restart, cron change, Terraform or Proxmox in the M4 operations."""
    for path in (PREFLIGHT, ROLLBACK, BOT_CHECK):
        body = "\n".join(line for line in path.read_text().splitlines() if not line.lstrip().startswith("#"))
        assert not re.search(
            r"state:\s*(absent|restarted)|\brm\b|profile\s+delete|- restart$|revoke|docker_compose|terraform|\bqm\b|"
            r"cron\s+(pause|resume|remove|create)",
            body,
            re.MULTILINE,
        ), path.name


def test_s10_getme_check_is_read_only() -> None:
    """candidate_bot_identity.yml writes nothing and hides the task that carries the token."""
    tasks = yaml.safe_load(BOT_CHECK.read_text())
    for task in tasks:
        assert not {"ansible.builtin.copy", "ansible.builtin.template", "ansible.builtin.file"} & task.keys()
    ask = tasks[0]
    assert ask["no_log"] is True and ask["changed_when"] is False and ask["check_mode"] is False
    assert "telegram_bot_token" in ask["ansible.builtin.command"]["stdin"]
    assert not any("telegram_bot_token" in str(a) for a in ask["ansible.builtin.command"]["argv"])


def test_s11_repo_stays_free_of_the_m41_prompt_copies() -> None:
    """The original default prompts (private scratchpad) are not committed anywhere in the repo."""
    tracked = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
    assert not [p for p in tracked if "m41-prompts" in p]
