"""M3 — Néo (profile tech-watch): declaration, identity, tools, context, preflight, rollback.

Prepared in M3.2, activated in M3.3 by its entry in hermes_profiles. Everything runs against throwaway directories, fake
tokens and a fake `docker`/`ss` on PATH; nothing reaches hermes-30. The context
tests also run the real Hermes image, offline and throwaway, when it is present
locally: they prove what Hermes actually loads, not that a file exists.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import test_m2_cafe_ia as m2
import yaml
from conftest import FAKE_TOKEN, FAKE_TOKEN_2, ROLE, RunTasks, recap
from test_m2_cafe_ia import (
    FAKE_DOCKER,
    FAKE_TAVILY,
    FAKE_TOKEN_3,
    GROUP_VARS,
    HERMES,
    HERMES_TOOLSETS,
    SENSITIVE,
    STOCK_SOUL,
    TASKS,
    assert_fails_quietly,
    calls,
    meminfo,
    snapshot,
    validate,
)

sys.path.insert(0, str(ROLE / "filter_plugins"))

import hermes_profiles as hp

# M2 fixtures reused as is: a lived-in default plus a created cafe-ia, and the fake Proxmox API.
data_dir = m2.data_dir
fake_pve = m2.fake_pve

NEO_SRC = ROLE / "files/profiles/tech-watch"
SOUL = NEO_SRC / "SOUL.md"
PREFLIGHT = HERMES / "ansible/m3-preflight.yml"
ROLLBACK = HERMES / "ansible/m3-rollback.yml"
# Obviously fake, but shaped like the D2 convention (neo_<6 alphanumerics>_bot).
FAKE_USERNAME = "neo_FAKE00_bot"
ALLOWED = {"web", "skills", "memory", "session_search", "todo", "clarify"}
CONTEXT_FACTS = (
    "RTX 4060 Laptop",
    "8 Go de VRAM",
    "32 Go de RAM",
    "16 Go de RAM physique",
    "Ubuntu 24.04",
    "Ollama",
    "Open WebUI",
    "Kubernetes",
    "Terraform",
    "Ansible",
)


@pytest.fixture(scope="module")
def group_vars() -> dict[str, Any]:
    """The hermes group_vars, as written (vault references left unresolved)."""
    return yaml.safe_load(GROUP_VARS.read_text())


@pytest.fixture(scope="module")
def neo(group_vars: dict[str, Any]) -> dict[str, Any]:
    """The prepared tech-watch declaration."""
    return group_vars["hermes_profile_tech_watch"]


@pytest.fixture(scope="module")
def cafe(group_vars: dict[str, Any]) -> dict[str, Any]:
    """The deployed cafe-ia declaration, fake secrets in place of vault references."""
    return group_vars["hermes_profile_cafe_ia"] | {
        "telegram_bot_token": FAKE_TOKEN_2,
        "env": {"TAVILY_API_KEY": FAKE_TAVILY},
    }


def resolved(neo: dict[str, Any], token: str = FAKE_TOKEN_3, username: str = FAKE_USERNAME) -> dict[str, Any]:
    """The tech-watch declaration with fakes in place of the vault keys and the M3.3 bot name."""
    return neo | {
        "telegram_bot_token": token,
        "telegram_bot_username": username,
        "env": {"TAVILY_API_KEY": "tvly-x"},
    }


def config(neo: dict[str, Any]) -> dict[str, Any]:
    """The config keys Ansible sets in the profile's config.yaml."""
    return neo["config"]


# --- Identite -----------------------------------------------------------------


def test_n01_identity_and_port(group_vars: dict[str, Any], neo: dict[str, Any]) -> None:
    """Néo keeps the technical id tech-watch and its reserved port 8643."""
    assert neo["name"] == "tech-watch"
    assert neo["description"].startswith("Néo — veille technique")
    assert neo["api_server_port"] == group_vars["hermes_profile_reserved_ports"]["tech-watch"] == 8643


def test_n01_activated_after_cafe_ia(group_vars: dict[str, Any]) -> None:
    """M3.3: tech-watch is appended after cafe-ia; no other profile (daily-life, job-search) yet."""
    assert group_vars["hermes_profiles"] == ["{{ hermes_profile_cafe_ia }}", "{{ hermes_profile_tech_watch }}"]


def test_n02_no_functional_alex_or_veille_left(neo: dict[str, Any]) -> None:
    """The former names (Alex, Veille) are gone from what defines and runs tech-watch."""
    texts = [
        json.dumps(neo, ensure_ascii=False),
        SOUL.read_text(),
        PREFLIGHT.read_text(),
        ROLLBACK.read_text(),
    ]
    for text in texts:
        assert not re.search(r"\balex\b|Tu es \*\*Veille", text, re.IGNORECASE)
    block = GROUP_VARS.read_text().split("hermes_profile_tech_watch:")[0].split("# Néo —")[1]
    assert "Alex" not in block


# --- Telegram : getMe et prerequis M3.3 ----------------------------------------


def test_n03_bot_username_is_declared_once_behind_mandatory(group_vars: dict[str, Any], neo: dict[str, Any]) -> None:
    """The BotFather name lives in one variable, Néo's own, and `mandatory` still fails hard if it goes away."""
    assert "hermes_tech_watch_telegram_bot_username" in neo["telegram_bot_username"]
    assert "mandatory(" in neo["telegram_bot_username"]
    username = group_vars["hermes_tech_watch_telegram_bot_username"]
    assert re.fullmatch(r"neo_[A-Za-z0-9]{6}_bot", username)
    assert username != group_vars["hermes_profile_cafe_ia"]["telegram_bot_username"]
    declared = [
        path
        for path in (HERMES / "ansible").rglob("*.yml")
        if re.search(r"^\s*hermes_tech_watch_telegram_bot_username\s*:", path.read_text(), re.MULTILINE)
    ]
    assert declared == [HERMES / "ansible/group_vars/hermes/all/main.yml"]


def test_n03_missing_bot_name_blocks_instead_of_skipping_getme(
    run_tasks: RunTasks, group_vars: dict[str, Any], neo: dict[str, Any]
) -> None:
    """A bare undefined reference would read as "no username": validate passes and getMe is skipped.

    With `mandatory`, the declaration fails loudly and names the missing prerequisite.
    """
    raw = neo | {
        "telegram_bot_token": FAKE_TOKEN_3,
        "env": {"TAVILY_API_KEY": "tvly-x"},
    }
    result = validate(run_tasks, group_vars, [raw])
    assert result.returncode != 0
    assert "PREREQUIS M3.3" in result.stdout + result.stderr
    assert FAKE_TOKEN_3 not in result.stdout + result.stderr


def test_n03_getme_runs_once_the_bot_name_is_set(
    run_tasks: RunTasks, group_vars: dict[str, Any], neo: dict[str, Any]
) -> None:
    """With the bot name filled in, the declaration passes and profile.yml's getMe check applies."""
    assert validate(run_tasks, group_vars, [resolved(neo)]).returncode == 0
    getme = next(t for t in yaml.safe_load((TASKS / "profile.yml").read_text()) if "token belongs" in t["name"])
    assert "hermes_profile.telegram_bot_username is defined" in getme["when"]
    assert_fails_quietly(validate(run_tasks, group_vars, [resolved(neo, username="neo_bot")]))


def test_n03_tokens_are_vault_references_only(neo: dict[str, Any], group_vars: dict[str, Any]) -> None:
    """Dedicated vault keys, never Kaféine's nor default's; no secret value in clear."""
    assert neo["telegram_bot_token"] == "{{ vault_hermes_tech_watch_telegram_bot_token }}"
    assert neo["env"] == {"TAVILY_API_KEY": "{{ vault_hermes_tech_watch_tavily_api_key }}"}
    cafe_raw = group_vars["hermes_profile_cafe_ia"]
    assert neo["telegram_bot_token"] not in (
        cafe_raw["telegram_bot_token"],
        group_vars["hermes_telegram_bot_token"],
    )
    assert neo["env"]["TAVILY_API_KEY"] != cafe_raw["env"]["TAVILY_API_KEY"]
    text = GROUP_VARS.read_text()
    assert not re.search(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b|tvly-[A-Za-z0-9]", text)


def test_n03_no_telegram_conflict_with_the_deployed_bots(
    run_tasks: RunTasks,
    group_vars: dict[str, Any],
    neo: dict[str, Any],
    cafe: dict[str, Any],
) -> None:
    """Three gateways together: Néo can reuse neither default's token nor Kaféine's."""
    assert validate(run_tasks, group_vars, [cafe, resolved(neo)]).returncode == 0
    assert_fails_quietly(validate(run_tasks, group_vars, [cafe, resolved(neo, token=FAKE_TOKEN)]))
    assert_fails_quietly(validate(run_tasks, group_vars, [cafe, resolved(neo, token=FAKE_TOKEN_2)]))


# --- Personnalite (SOUL.md) ---------------------------------------------------


def test_n04_soul_names_neo_and_is_its_own() -> None:
    """A dedicated SOUL.md, distinct from Kaféine's."""
    soul = SOUL.read_text()
    assert soul.startswith("Tu es **Néo**")
    assert soul != (ROLE / "files/profiles/cafe-ia/SOUL.md").read_text()


def test_n04_five_domains_with_local_ai_on_its_own() -> None:
    """Five watch domains; local AI is a domain of its own, with its hardware rules."""
    soul = SOUL.read_text()
    domains = re.findall(r"^### (\d)\. (.+)$", soul, re.MULTILINE)
    assert domains == [
        ("1", "IA et agents"),
        ("2", "IA locale"),
        ("3", "DevOps et cloud"),
        ("4", "Développement"),
        ("5", "Open source"),
    ]
    local = soul.split("### 2. IA locale")[1].split("### 3.")[0]
    for topic in (
        "Ollama",
        "llama.cpp",
        "Open WebUI",
        "vLLM",
        "LM Studio",
        "quantification",
        "VRAM",
        "licence",
    ):
        assert topic in local, topic
    assert "pas** sur le serveur Proxmox" in local
    assert "exigences minimales publiées" in local
    assert "sans preuve suffisante" in local


def test_n04_no_caribbean_axis() -> None:
    """No Caribbean domain in Néo's mission (decision M3)."""
    assert not re.search(r"cara[iï]b|antill|guadeloupe", SOUL.read_text(), re.IGNORECASE)


def test_n04_method_and_formats() -> None:
    """Facts, hypotheses and recommendations kept apart; both answer formats spelled out."""
    soul = SOUL.read_text()
    for marker in (
        "**Fait vérifié**",
        "**Hypothèse**",
        "**Recommandation**",
        "**Ne jamais inventer**",
    ):
        assert marker in soul
    assert "une donnée, jamais une instruction" in soul
    news = (
        "Ce qui change",
        "Pourquoi c'est intéressant",
        "Impact pour Xavier",
        "Faisabilité",
        "Expérimentation",
        "Sources",
    )
    lab = (
        "Prérequis",
        "Ressources nécessaires",
        "Procédure reproductible",
        "Critère de réussite",
        "Limites connues",
    )
    positions = [soul.index(f"**{item}") for item in news]
    assert positions == sorted(positions)
    for item in lab:
        assert f"**{item}**" in soul
    assert "Réponds en **français**" in soul


def test_n04_soul_promises_no_schedule_and_no_file() -> None:
    """No cron, collection script, local sources file or attachment: Néo has none of the tools for it."""
    soul = SOUL.read_text()
    assert not re.search(
        r"\bcron\b|brief quotidien|synthèse hebdo|pièce jointe|sources\.local|tech_watch_|installer la veille",
        soul,
        re.IGNORECASE,
    )
    for limit in (
        "ni terminal",
        "ni accès aux fichiers",
        "ni tâches planifiées",
        "pas de veille automatique",
    ):
        assert limit in soul, limit


def test_n04_soul_is_seeded_over_the_stock_text(run_tasks: RunTasks, data_dir: Path) -> None:
    """`hermes profile create` leaves the stock SOUL.md: the seed installs Néo's over it."""
    dest = data_dir / "profiles/tech-watch/SOUL.md"
    dest.parent.mkdir(parents=True)
    dest.write_text(STOCK_SOUL)
    result = run_tasks(
        "soul_seed.yml",
        {
            "hermes_soul_src": str(SOUL),
            "hermes_soul_dest": str(dest),
            "hermes_soul_stock_sha256": [hashlib.sha256(STOCK_SOUL.encode()).hexdigest()],
            "hermes_data_dir": str(data_dir),
        },
    )
    assert result.returncode == 0, result.stdout
    assert dest.read_text() == SOUL.read_text()


# --- Securite : outils ----------------------------------------------------------


def test_n05_tool_matrix_is_kafeines(neo: dict[str, Any], cafe: dict[str, Any]) -> None:
    """Same least-privilege matrix as Kaféine (D5): known names, disjoint, every sensitive toolset denied."""
    cfg = config(neo)
    allowed = set(cfg["platform_toolsets.telegram"]) - {"no_mcp"}
    denied = set(cfg["agent.disabled_toolsets"])
    assert allowed == ALLOWED
    assert "no_mcp" in cfg["platform_toolsets.telegram"]
    assert (allowed | denied) <= HERMES_TOOLSETS
    assert not allowed & denied
    assert SENSITIVE - {"browser"} <= denied
    assert not SENSITIVE & allowed
    assert {
        "terminal",
        "file",
        "code_execution",
        "cronjob",
        "kanban",
        "delegation",
    } <= denied
    assert denied == set(cafe["config"]["agent.disabled_toolsets"])
    for platform in ("cron", "api_server", "cli"):
        assert cfg[f"platform_toolsets.{platform}"] == cfg["platform_toolsets.telegram"]
    assert cfg["skills.write_approval"] is True


def test_n05_no_mcp_and_no_kandidat(neo: dict[str, Any]) -> None:
    """No MCP server declared, and Kandidat named nowhere for Néo."""
    assert not any(key.startswith("mcp") for key in config(neo))
    assert "kandidat" not in json.dumps(neo).lower()
    assert "kandidat" not in SOUL.read_text().lower()


def test_n05_restrictions_are_verified_before_the_gateway_starts(
    neo: dict[str, Any],
) -> None:
    """profile.yml re-resolves the toolsets only when a denylist is declared: Néo declares one."""
    check = next(t for t in yaml.safe_load((TASKS / "profile.yml").read_text()) if "tool restrictions" in t["name"])
    assert "'agent.disabled_toolsets' in (hermes_profile.config | default({}))" in check["when"]
    assert "agent.disabled_toolsets" in config(neo)


def test_n05_env_isolation(run_tasks: RunTasks, group_vars: dict[str, Any], neo: dict[str, Any]) -> None:
    """Only its own web key in its .env; no allowlist, API or Telegram override of its own."""
    assert set(neo["env"]) == {"TAVILY_API_KEY"}
    assert "telegram_allowed_users" not in neo
    assert "API_SERVER_HOST" not in json.dumps(neo)
    bad = resolved(neo)
    bad["env"] = bad["env"] | {"TELEGRAM_ALLOWED_USERS": "1"}
    assert_fails_quietly(validate(run_tasks, group_vars, [bad]))


# --- Configuration --------------------------------------------------------------


def test_n06_web_backend_and_no_cron(neo: dict[str, Any]) -> None:
    """Tavily as web backend; no cron key (mirror_delivery dropped), cronjob denied."""
    cfg = config(neo)
    assert cfg["web.backend"] == "tavily"
    assert not any(key.startswith("cron") for key in cfg)
    assert "cronjob" in cfg["agent.disabled_toolsets"]


@pytest.mark.parametrize(
    "key",
    [
        "web.backend",
        "platform_toolsets.telegram",
        "agent.disabled_toolsets",
        "skills.write_approval",
        "agent.environment_hint",
    ],
)
def test_n06_config_values_converge(neo: dict[str, Any], key: str) -> None:
    """What `config set` stores reads back equal (`config get --json`): no perpetual change."""
    value = config(neo)[key]
    arg = hp.hermes_config_arg(value)
    # environment_hint is string-typed in Hermes: `config set` stores it raw.
    stored = arg if key == "agent.environment_hint" else yaml.safe_load(arg)
    assert stored == value
    assert hp.hermes_config_equal(json.dumps(stored), value)


def test_n07_collection_scripts_stay_inactive(neo: dict[str, Any]) -> None:
    """The scripts are shipped for later, but nothing runs them: no cron, no task, no playbook calls them."""
    assert (NEO_SRC / "scripts/tech_watch_collect.py").exists()
    for path in [*TASKS.glob("*.yml"), *(ROLE / "templates").glob("*"), *(HERMES / "ansible").glob("*.yml")]:
        assert not re.search(r"tech_watch_(daily|weekly|collect)", path.read_text()), path.name
    # m1_backup/m1_rollback legitimately save and restore default's jobs.json: not on Néo's path.
    for path in [
        *TASKS.glob("profile*.yml"),
        TASKS / "deployed_profiles_preflight.yml",
        PREFLIGHT,
        ROLLBACK,
    ]:
        assert not re.search(r"\bcron\s+(create|add|edit|resume)\b|jobs\.json", path.read_text()), path.name
    shipped = sorted(
        str(p.relative_to(NEO_SRC)) for p in NEO_SRC.rglob("*") if p.is_file() and "__pycache__" not in p.parts
    )
    assert not [p for p in shipped if p.startswith("cron") or p.endswith("jobs.json")]
    denied = set(config(neo)["agent.disabled_toolsets"])
    assert {"cronjob", "terminal", "code_execution", "file"} <= denied


def test_n07_host_tasks_create_no_cron_and_copy_nothing_from_others(run_tasks: RunTasks, data_dir: Path) -> None:
    """Deploying Néo's content writes under profiles/tech-watch only: no jobs.json, nothing from default or cafe-ia."""
    profile = data_dir / "profiles/tech-watch"
    profile.mkdir(parents=True)
    others = {k: v for k, v in snapshot(data_dir).items() if not k.startswith("profiles/tech-watch/")}
    result = run_tasks(
        "profile_content.yml",
        {"hermes_content_src": str(NEO_SRC), "hermes_content_dest": str(profile)},
    )
    assert result.returncode == 0, result.stdout
    assert {k: v for k, v in snapshot(data_dir).items() if not k.startswith("profiles/tech-watch/")} == others
    deployed = snapshot(profile)
    assert not [p for p in deployed if "cron" in p or p.endswith("jobs.json")]
    blob = b"".join(deployed.values())
    for leaked in (b"souvenir de default", b"ai-coffee-scout", FAKE_TOKEN.encode()):
        assert leaked not in blob


# --- Contexte technique (agent.environment_hint) ------------------------------


def test_n08_context_carries_the_known_facts(neo: dict[str, Any]) -> None:
    """The context Néo gets: laptop, GPU, HomeLab size, OS, local AI and infra tools."""
    hint = config(neo)["agent.environment_hint"]
    for fact in CONTEXT_FACTS:
        assert fact in hint, fact
    assert "sans GPU" in hint and "seule machine avec un GPU" in hint
    assert "ne les présente pas comme des mesures actuelles" in hint
    assert "n'ouvrent aucun accès" in hint


def test_n08_context_holds_no_secret_nor_address(neo: dict[str, Any]) -> None:
    """No IP, no token, no Telegram id, no credential-looking value."""
    hint = config(neo)["agent.environment_hint"]
    assert not re.search(
        r"\b\d{1,3}(\.\d{1,3}){3}\b|\b\d{9,10}\b|tvly-|sk-|glpat-|password|token",
        hint,
        re.IGNORECASE,
    )


def test_n08_context_is_per_profile_config_never_managed(neo: dict[str, Any]) -> None:
    """Set in the profile's config.yaml through profile.yml, never in the managed layer (shared by all)."""
    assert "agent.environment_hint" in config(neo)
    managed = (ROLE / "templates/config.yaml.j2").read_text()
    assert "environment_hint" not in managed
    assert "environment_hint" not in (ROLE / "templates/hermes.env.j2").read_text()
    assert "HERMES_ENVIRONMENT_HINT" not in (ROLE / "templates/docker-compose.yml.j2").read_text()


IMAGE = "{}:{}".format(
    *(yaml.safe_load((ROLE / "defaults/main.yml").read_text())[k] for k in ("hermes_image", "hermes_image_tag"))
)

LAB_DRIVER = r'''
import json, os, subprocess
CFG, SOUL, CHECKS, ALLOWED, DENIED = json.loads(os.environ["LAB_INPUT"])
def run(*argv, **kw):
    return subprocess.run(list(argv), capture_output=True, text=True, **kw)
os.makedirs("/tmp/data", exist_ok=True)
out = {"create": run("hermes", "profile", "create", "tech-watch", "--no-alias").returncode}
out["set"] = {k: run("hermes", "-p", "tech-watch", "config", "set", k, v).returncode for k, v in CFG.items()}
out["get"] = {k: run("hermes", "-p", "tech-watch", "config", "get", k, "--json").stdout for k in CFG}
with open("/tmp/data/profiles/tech-watch/SOUL.md", "w", encoding="utf-8") as f:
    f.write(SOUL)
home = {"tech-watch": "/tmp/data/profiles/tech-watch", "default": "/tmp/data"}
r = run("python3", "-c", CHECKS, "toolsets", ALLOWED, DENIED, "true", env=dict(os.environ, HERMES_HOME=home["tech-watch"]))
out["toolsets"] = [r.returncode, r.stdout]
probe = """
import json
from run_agent import AIAgent
from agent.system_prompt import build_system_prompt
agent = AIAgent(base_url="http://127.0.0.1:9/v1", api_key="x", model="deepseek-v4-flash", platform="telegram", quiet_mode=True)
print(json.dumps(build_system_prompt(agent)))
"""
out["prompt"] = {}
for name, path in home.items():
    r = run("python3", "-c", probe, env=dict(os.environ, HERMES_HOME=path), cwd="/opt/hermes")
    out["prompt"][name] = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else "ERROR " + r.stderr[-800:]
print("LAB_RESULT " + json.dumps(out))
'''


@pytest.fixture(scope="module")
def lab(neo: dict[str, Any]) -> dict[str, Any]:
    """Apply Néo's declaration to a throwaway, offline container of the deployed image.

    Same commands as profile.yml (`profile create --no-alias`, `config set` with
    hermes_config_arg), then read back what Hermes resolves. Skipped when Docker
    or the image is not available locally.
    """
    docker = shutil.which("docker")
    if (
        not docker
        or subprocess.run([docker, "image", "inspect", IMAGE], capture_output=True, check=False).returncode != 0
    ):
        pytest.skip(f"{IMAGE} not available locally")
    cfg = {k: hp.hermes_config_arg(v) for k, v in config(neo).items()}
    allowed = ",".join(sorted(set(config(neo)["platform_toolsets.telegram"]) - {"no_mcp"}))
    denied = ",".join(config(neo)["agent.disabled_toolsets"])
    payload = json.dumps(
        [
            cfg,
            SOUL.read_text(),
            (ROLE / "files/hermes_checks.py").read_text(),
            allowed,
            denied,
        ]
    )
    result = subprocess.run(
        [
            docker,
            "run",
            "--rm",
            "-i",
            "--network",
            "none",
            "-u",
            "10000",
            "-w",
            "/tmp",
            "-e",
            "HERMES_HOME=/tmp/data",
            "-e",
            "LAB_INPUT",
            "--entrypoint",
            "python3",
            IMAGE,
            "-",
        ],
        input=LAB_DRIVER,
        env={**os.environ, "LAB_INPUT": payload},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    line = next((x for x in result.stdout.splitlines() if x.startswith("LAB_RESULT ")), None)
    assert line, result.stdout[-2000:] + result.stderr[-2000:]
    return json.loads(line.removeprefix("LAB_RESULT "))


def test_n08_lab_profile_config_applies_and_converges(lab: dict[str, Any], neo: dict[str, Any]) -> None:
    """Real image: every key is accepted and reads back equal, so a second run changes nothing."""
    assert lab["create"] == 0
    assert all(rc == 0 for rc in lab["set"].values()), lab["set"]
    for key, value in config(neo).items():
        assert hp.hermes_config_equal(lab["get"][key], value), key


def test_n08_lab_context_reaches_the_telegram_system_prompt(
    lab: dict[str, Any],
) -> None:
    """Real image: Néo's Telegram system prompt carries its SOUL.md and the context; default's has neither."""
    prompt = lab["prompt"]["tech-watch"]
    assert not prompt.startswith("ERROR"), prompt
    assert SOUL.read_text().splitlines()[0] in prompt
    for fact in CONTEXT_FACTS:
        assert fact in prompt, fact
    other = lab["prompt"]["default"]
    assert not other.startswith("ERROR"), other
    assert "RTX 4060 Laptop" not in other and "Tu es **Néo**" not in other


def test_n08_lab_tool_restrictions_are_effective(lab: dict[str, Any]) -> None:
    """Real image, gateway code path: telegram, cron, api_server and cli expose only the allowed toolsets."""
    rc, out = lab["toolsets"]
    assert rc == 0, out
    assert set(out.strip().removeprefix("toolsets restricted to: ").split(" | tools: ")[0].split(", ")) == ALLOWED


# --- Preflight M3 -------------------------------------------------------------

FAKE_DOCKER_M3 = FAKE_DOCKER.replace(
    'elif cmd[:1] == ["python3"]:\n    print("telegram connected (gateway pid 162)")',
    'elif cmd[:1] == ["python3"]:\n'
    '    failing = [m for m in state.get("python_fails", []) if any(m in a for a in sys.argv)]\n'
    "    if failing:\n"
    '        print("NO-GO: " + failing[0])\n'
    "        sys.exit(1)\n"
    '    print("telegram connected (gateway pid 162)")',
)
assert FAKE_DOCKER_M3 != FAKE_DOCKER


@pytest.fixture
def m3_host(
    tmp_path: Path,
    data_dir: Path,
    fake_pve: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """hermes-30 as M3 finds it: default and cafe-ia up, no tech-watch, port 8643 free, 2 GiB available."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("docker", "ss"):
        (bindir / name).write_text(FAKE_DOCKER_M3.replace("#!/usr/bin/env python3", f"#!{sys.executable}"))
        (bindir / name).chmod(0o755)
    host: dict[str, Any] = {
        "state": tmp_path / "state.json",
        "log": tmp_path / "calls.log",
        "data": data_dir,
    }
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_STATE", str(host["state"]))
    monkeypatch.setenv("FAKE_LOG", str(host["log"]))
    monkeypatch.setenv("FAKE_DATA", str(data_dir))
    host["meminfo"] = tmp_path / "meminfo"
    host["meminfo"].write_text(meminfo(3333, 2123))
    set_m3_state(host)
    return host


def set_m3_state(host: dict[str, Any], tech_watch: str | None = None, listen: str = "", **extra: Any) -> None:
    """Describe the simulated container: default and cafe-ia up, tech-watch as given."""
    svstat = {
        "gateway-default": "up (pid 160) 99 seconds",
        "gateway-cafe-ia": "up (pid 555) 99 seconds",
    }
    if tech_watch is not None:
        svstat["gateway-tech-watch"] = tech_watch
    host["state"].write_text(json.dumps({"svstat": svstat, "listen": listen, **extra}))


def deployed_preflight(run: RunTasks, host: dict[str, Any], cafe: dict[str, Any]) -> Any:
    """Run the real deployed_profiles_preflight.yml with cafe-ia deployed, tech-watch as candidate."""
    return run(
        "deployed_profiles_preflight.yml",
        {
            "hermes_pf_candidate_name": "tech-watch",
            "hermes_profiles": [cafe],
            "hermes_data_dir": str(host["data"]),
        },
    )


def profile_preflight(
    run: RunTasks,
    group_vars: dict[str, Any],
    host: dict[str, Any],
    cafe: dict[str, Any],
    candidate: dict[str, Any],
) -> Any:
    """Run the real profile_preflight.yml for tech-watch, cafe-ia already in hermes_profiles.

    hermes_profiles goes in the inventory, as group_vars do on hermes-30: as an
    extra var it would outrank the list profile_preflight.yml composes with the
    candidate, and validate.yml would never see tech-watch.
    """
    inventory = host["state"].parent / "inventory.yml"
    inventory.write_text(yaml.safe_dump({"all": {"hosts": {"localhost": {"hermes_profiles": [cafe]}}}}))
    return run(
        "profile_preflight.yml",
        {
            "hermes_pf_profile": candidate,
            "hermes_data_dir": str(host["data"]),
            "hermes_telegram_enabled": True,
            "hermes_telegram_bot_token": FAKE_TOKEN,
            "hermes_telegram_allowed_users": "1111111111",
            "hermes_profile_reserved_ports": group_vars["hermes_profile_reserved_ports"],
            "hermes_pf_meminfo_path": str(host["meminfo"]),
        },
        "-i",
        str(inventory),
    )


def test_n09_preflight_playbook_order_and_target() -> None:
    """m3-preflight: default first, then the deployed profiles, then the tech-watch candidate."""
    tasks = yaml.safe_load(PREFLIGHT.read_text())[0]["tasks"]
    assert [t["ansible.builtin.include_role"]["tasks_from"] for t in tasks] == [
        "preflight.yml",
        "deployed_profiles_preflight.yml",
        "profile_preflight.yml",
    ]
    assert tasks[1]["vars"] == {"hermes_pf_candidate_name": "tech-watch"}
    assert tasks[2]["vars"] == {"hermes_pf_profile": "{{ hermes_profile_tech_watch }}"}


def test_n09_deployed_profiles_go_when_cafe_ia_is_connected(
    run_tasks: RunTasks, m3_host: dict[str, Any], cafe: dict[str, Any]
) -> None:
    """GO: cafe-ia connected, no cron due, no ESTOP; only cafe-ia is probed, nothing is written."""
    before = snapshot(m3_host["data"])
    result = deployed_preflight(run_tasks, m3_host, cafe)
    assert result.returncode == 0, result.stdout
    assert snapshot(m3_host["data"]) == before
    probed = [c for c in calls(m3_host) if c[0] == "docker"]
    assert probed and all("tech-watch" not in " ".join(c) for c in probed)
    assert any("gateway-cafe-ia" in c for c in probed)
    assert any("HERMES_HOME=/opt/data/profiles/cafe-ia" in c for c in probed)
    for secret in (FAKE_TOKEN_2, FAKE_TAVILY):
        assert secret not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "failing",
    ["gateway-cafe-ia", "HERMES_HOME=/opt/data/profiles/cafe-ia"],
    ids=["telegram", "cron"],
)
def test_n09_deployed_profiles_no_go(
    run_tasks: RunTasks, m3_host: dict[str, Any], cafe: dict[str, Any], failing: str
) -> None:
    """NO-GO when Kaféine is disconnected or one of its cron jobs could fire."""
    set_m3_state(m3_host, python_fails=[failing])
    result = deployed_preflight(run_tasks, m3_host, cafe)
    assert result.returncode != 0
    assert "NO-GO" in result.stdout


@pytest.mark.parametrize(
    "where",
    ["", "profiles/cafe-ia/", "profiles/tech-watch/"],
    ids=["default", "cafe-ia", "candidate"],
)
def test_n09_emergency_stop_is_a_no_go(
    run_tasks: RunTasks, m3_host: dict[str, Any], cafe: dict[str, Any], where: str
) -> None:
    """An ESTOP on default, a deployed profile or the candidate stops the deployment."""
    (m3_host["data"] / where).mkdir(parents=True, exist_ok=True)
    (m3_host["data"] / where / "ESTOP").write_text("")
    assert deployed_preflight(run_tasks, m3_host, cafe).returncode != 0


def test_n09_candidate_preflight_go_on_a_blank_page(
    run_tasks: RunTasks,
    group_vars: dict[str, Any],
    m3_host: dict[str, Any],
    neo: dict[str, Any],
    cafe: dict[str, Any],
) -> None:
    """GO: tech-watch absent, port 8643 free, memory headroom at the floor; nothing written, no secret shown."""
    before = snapshot(m3_host["data"])
    result = profile_preflight(run_tasks, group_vars, m3_host, cafe, resolved(neo))
    assert result.returncode == 0, result.stdout
    assert snapshot(m3_host["data"]) == before
    assert "tech-watch (port 8643)" in result.stdout
    assert "port                   : libre" in result.stdout
    for secret in (FAKE_TOKEN, FAKE_TOKEN_2, FAKE_TOKEN_3, FAKE_TAVILY, "tvly-x"):
        assert secret not in result.stdout + result.stderr


def test_n09_candidate_preflight_no_go_without_the_bot_name(
    run_tasks: RunTasks,
    group_vars: dict[str, Any],
    m3_host: dict[str, Any],
    neo: dict[str, Any],
    cafe: dict[str, Any],
) -> None:
    """The prerequisite M3.3 is enforced by the preflight itself."""
    raw = neo | {
        "telegram_bot_token": FAKE_TOKEN_3,
        "env": {"TAVILY_API_KEY": "tvly-x"},
    }
    result = profile_preflight(run_tasks, group_vars, m3_host, cafe, raw)
    assert result.returncode != 0
    assert "PREREQUIS M3.3" in result.stdout + result.stderr


def test_n09_candidate_preflight_no_go_when_vault_keys_are_missing(
    run_tasks: RunTasks,
    group_vars: dict[str, Any],
    m3_host: dict[str, Any],
    neo: dict[str, Any],
    cafe: dict[str, Any],
) -> None:
    """Bot name set but vault keys unresolved: NO-GO naming the tech-watch vault key."""
    raw = neo | {"telegram_bot_username": FAKE_USERNAME}
    result = profile_preflight(run_tasks, group_vars, m3_host, cafe, raw)
    assert result.returncode != 0
    assert "vault_hermes_tech_watch_" in result.stdout + result.stderr


@pytest.mark.parametrize("token", [FAKE_TOKEN, FAKE_TOKEN_2], ids=["default", "cafe-ia"])
def test_n09_candidate_preflight_no_go_on_a_shared_token(
    run_tasks: RunTasks,
    group_vars: dict[str, Any],
    m3_host: dict[str, Any],
    neo: dict[str, Any],
    cafe: dict[str, Any],
    token: str,
) -> None:
    """Telegram conflict: `--replace` would kill the other bot's gateway; refused without printing the token."""
    assert_fails_quietly(profile_preflight(run_tasks, group_vars, m3_host, cafe, resolved(neo, token=token)))


def test_n09_candidate_preflight_no_go_when_tech_watch_exists_or_port_is_taken(
    run_tasks: RunTasks,
    group_vars: dict[str, Any],
    m3_host: dict[str, Any],
    neo: dict[str, Any],
    cafe: dict[str, Any],
) -> None:
    """A tech-watch directory, s6 slot or listener on 8643 means it is not a blank page."""
    set_m3_state(m3_host, listen="LISTEN 0 5 127.0.0.1:8643 0.0.0.0:*\n")
    assert_fails_quietly(profile_preflight(run_tasks, group_vars, m3_host, cafe, resolved(neo)))
    set_m3_state(m3_host, tech_watch="down (exitcode 0) 5 seconds")
    assert_fails_quietly(profile_preflight(run_tasks, group_vars, m3_host, cafe, resolved(neo)))
    set_m3_state(m3_host)
    (m3_host["data"] / "profiles/tech-watch").mkdir(parents=True)
    assert_fails_quietly(profile_preflight(run_tasks, group_vars, m3_host, cafe, resolved(neo)))


def test_n09_candidate_preflight_no_go_without_memory_headroom(
    run_tasks: RunTasks,
    group_vars: dict[str, Any],
    m3_host: dict[str, Any],
    neo: dict[str, Any],
    cafe: dict[str, Any],
) -> None:
    """The M2 memory gate (1536 MiB now and at the balloon floor) applies to the third gateway too."""
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    assert defaults["hermes_pf_min_available_mib"] == 1536
    m3_host["meminfo"].write_text(meminfo(3333, 1200))
    assert profile_preflight(run_tasks, group_vars, m3_host, cafe, resolved(neo)).returncode != 0


def test_n09_new_preflight_is_read_only() -> None:
    """deployed_profiles_preflight.yml and profile_telegram_check.yml only read."""
    write_modules = {
        "ansible.builtin.copy",
        "ansible.builtin.template",
        "ansible.builtin.file",
        "ansible.builtin.lineinfile",
    }
    for name in ("deployed_profiles_preflight.yml", "profile_telegram_check.yml"):
        for task in yaml.safe_load((TASKS / name).read_text()):
            assert not write_modules & task.keys(), task["name"]
            if "ansible.builtin.command" in task:
                assert task["changed_when"] is False and task["check_mode"] is False, task["name"]


# --- Preflight d'une mise a jour (M3.3.1) : tous les profils deja deployes -----

PROFILES_PREFLIGHT = HERMES / "ansible/profiles-preflight.yml"


def update_preflight(run: RunTasks, host: dict[str, Any], cafe: dict[str, Any], neo: dict[str, Any]) -> Any:
    """Run the real deployed_profiles_preflight.yml with no candidate: cafe-ia and tech-watch both deployed."""
    return run(
        "deployed_profiles_preflight.yml",
        {"hermes_profiles": [cafe, resolved(neo)], "hermes_data_dir": str(host["data"])},
    )


def test_n11_profiles_preflight_playbook_has_no_candidate() -> None:
    """profiles-preflight: default, then every deployed profile; no candidate, no blank-page check."""
    tasks = yaml.safe_load(PROFILES_PREFLIGHT.read_text())[0]["tasks"]
    assert [t["ansible.builtin.include_role"]["tasks_from"] for t in tasks] == [
        "preflight.yml",
        "deployed_profiles_preflight.yml",
    ]
    assert "vars" not in tasks[1]


def test_n11_update_preflight_probes_every_deployed_profile(
    run_tasks: RunTasks, m3_host: dict[str, Any], cafe: dict[str, Any], neo: dict[str, Any]
) -> None:
    """GO, read-only: without a candidate, both cafe-ia AND tech-watch are probed (Telegram, cron)."""
    before = snapshot(m3_host["data"])
    result = update_preflight(run_tasks, m3_host, cafe, neo)
    assert result.returncode == 0, result.stdout
    assert snapshot(m3_host["data"]) == before
    probed = [" ".join(c) for c in calls(m3_host) if c[0] == "docker"]
    for name in ("cafe-ia", "tech-watch"):
        assert any(f"gateway-{name}" in c for c in probed), name
        assert any(f"HERMES_HOME=/opt/data/profiles/{name}" in c for c in probed), name


@pytest.mark.parametrize(
    "failing",
    ["gateway-tech-watch", "HERMES_HOME=/opt/data/profiles/tech-watch", "gateway-cafe-ia"],
    ids=["neo-telegram", "neo-cron", "cafe-telegram"],
)
def test_n11_update_preflight_no_go(
    run_tasks: RunTasks, m3_host: dict[str, Any], cafe: dict[str, Any], neo: dict[str, Any], failing: str
) -> None:
    """NO-GO when a deployed profile, tech-watch included, is disconnected or has a cron job due."""
    set_m3_state(m3_host, python_fails=[failing])
    result = update_preflight(run_tasks, m3_host, cafe, neo)
    assert result.returncode != 0
    assert "NO-GO" in result.stdout


def test_n11_update_preflight_estop_on_tech_watch_is_a_no_go(
    run_tasks: RunTasks, m3_host: dict[str, Any], cafe: dict[str, Any], neo: dict[str, Any]
) -> None:
    """An ESTOP on the now-deployed tech-watch still stops the update."""
    (m3_host["data"] / "profiles/tech-watch").mkdir(parents=True, exist_ok=True)
    (m3_host["data"] / "profiles/tech-watch/ESTOP").write_text("")
    assert update_preflight(run_tasks, m3_host, cafe, neo).returncode != 0


# --- Rollback M3 --------------------------------------------------------------


def test_n10_rollback_playbook_targets_tech_watch_only() -> None:
    """m3-rollback: stop tech-watch, then re-check every other deployed profile."""
    tasks = yaml.safe_load(ROLLBACK.read_text())[0]["tasks"]
    assert tasks[0]["ansible.builtin.include_role"]["tasks_from"] == "profile_rollback.yml"
    assert tasks[0]["vars"] == {"hermes_rb_profile_name": "tech-watch"}
    assert tasks[1]["ansible.builtin.include_role"]["tasks_from"] == "profile_telegram_check.yml"
    assert "reject('eq', 'tech-watch')" in tasks[1]["loop"]
    assert tasks[1]["loop_control"]["loop_var"] == "hermes_tc_profile_name"


def test_n10_rollback_stops_tech_watch_only_and_keeps_its_data(
    run_tasks: RunTasks, group_vars: dict[str, Any], m3_host: dict[str, Any]
) -> None:
    """Only `-p tech-watch gateway stop` mutates; default and cafe-ia are only read; no file removed."""
    profile = m3_host["data"] / "profiles/tech-watch"
    (profile / "memories").mkdir(parents=True)
    (profile / "memories/MEMORY.md").write_text("souvenir de Néo\n")
    (profile / "gateway_state.json").write_text(json.dumps({"desired_state": "running", "gateway_state": "running"}))
    set_m3_state(
        m3_host,
        tech_watch="up (pid 777) 60 seconds",
        listen="LISTEN 0 128 127.0.0.1:8643 0.0.0.0:*",
    )
    before = set(snapshot(m3_host["data"]))
    result = run_tasks(
        "profile_rollback.yml",
        {
            "hermes_rb_profile_name": "tech-watch",
            "hermes_rb_stop_retries": 2,
            "hermes_rb_stop_delay": 1,
            "hermes_data_dir": str(m3_host["data"]),
            "hermes_profile_reserved_ports": group_vars["hermes_profile_reserved_ports"],
            "hermes_profiles": [],
            "hermes_telegram_enabled": True,
        },
    )
    assert result.returncode == 0, result.stdout
    mutating = [c for c in calls(m3_host) if "stop" in c]
    assert len(mutating) == 1 and mutating[0][-4:] == [
        "-p",
        "tech-watch",
        "gateway",
        "stop",
    ]
    assert before <= set(snapshot(m3_host["data"]))
    assert (profile / "memories/MEMORY.md").read_text() == "souvenir de Néo\n"
    assert json.loads((profile / "gateway_state.json").read_text())["desired_state"] == "stopped"


def test_n10_cafe_ia_is_rechecked_after_the_rollback(run_tasks: RunTasks, m3_host: dict[str, Any]) -> None:
    """profile_telegram_check.yml passes for a connected cafe-ia and fails for a disconnected one."""
    ok = run_tasks("profile_telegram_check.yml", {"hermes_tc_profile_name": "cafe-ia"})
    assert ok.returncode == 0, ok.stdout
    assert recap(ok)["changed"] == 0
    assert any("gateway-cafe-ia" in c for c in calls(m3_host))
    set_m3_state(m3_host, python_fails=["gateway-cafe-ia"])
    assert run_tasks("profile_telegram_check.yml", {"hermes_tc_profile_name": "cafe-ia"}).returncode != 0


def test_n10_m3_operations_destroy_nothing() -> None:
    """No deletion, no token revocation, no restart, no Terraform or Proxmox in the M3 operations."""
    for path in (
        PREFLIGHT,
        ROLLBACK,
        TASKS / "deployed_profiles_preflight.yml",
        TASKS / "profile_telegram_check.yml",
    ):
        body = "\n".join(line for line in path.read_text().splitlines() if not line.lstrip().startswith("#"))
        assert not re.search(
            r"state:\s*(absent|restarted)|\brm\b|profile\s+delete|- restart$|revoke|docker_compose|terraform|\bqm\b",
            body,
            re.MULTILINE,
        ), path.name
