"""M6.6.D.1: hermes-30 (VMID 9030, 192.168.10.30) was destroyed in M6.6.C.

Guards against its return as an ACTIVE declaration: inventory, host_vars, group_vars, role
defaults, the Caddy routes, the hermes-31 Terraform code and CI. Comments, docs and historical
playbooks may still name it. Also runs, for real on localhost: the guard that keeps the
historical v0.20.4 playbooks off a multiplexed host, and the komodo_periphery Server name check.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import REPO, ROLE, ROLES

ANSIBLE_DIR = REPO / "hermes/ansible"
RETIRED = re.compile(r"hermes-30|192\.168\.10\.30\b|\b9030\b")
LEGACY_PLAYBOOKS = sorted(
    [*ANSIBLE_DIR.glob("m[1-5]-*.yml"), ANSIBLE_DIR / "profiles-preflight.yml"], key=lambda p: p.name
)


def yaml_values(path: Path) -> str:
    """The parsed YAML of `path` as JSON: values only, comments dropped."""
    return json.dumps(yaml.safe_load(path.read_text()), ensure_ascii=False)


def active_yaml() -> list[Path]:
    """YAML files whose values are live configuration (vault files excluded: encrypted)."""
    files = [
        ANSIBLE_DIR / "inventory.yml",
        *ANSIBLE_DIR.glob("host_vars/*/*.yml"),
        *ANSIBLE_DIR.glob("group_vars/hermes/all/*.yml"),
        *ROLES.glob("*/defaults/main.yml"),
        *(REPO / "caddy/ansible/group_vars").rglob("*.yml"),
        *(REPO / "pihole/ansible/group_vars").rglob("*.yml"),
        REPO / ".gitlab-ci.yml",
    ]
    return [p for p in files if "vault" not in p.parts]


@pytest.mark.parametrize("path", active_yaml(), ids=lambda p: str(p.relative_to(REPO)))
def test_no_active_yaml_value_names_hermes_30(path: Path) -> None:
    """No inventory, variable, route or CI value points at the destroyed VM (comments may)."""
    assert not RETIRED.findall(yaml_values(path))


def test_hermes_31_terraform_code_does_not_reference_hermes_30() -> None:
    """Only comments of hermes/terraform-31 may name hermes-30; no argument does."""
    for tf in (REPO / "hermes/terraform-31").glob("*.tf"):
        code = [line for line in tf.read_text().splitlines() if not line.strip().startswith(("#", "//"))]
        assert not RETIRED.findall("\n".join(code)), tf.name


def test_hermes_30_root_and_host_vars_are_gone_from_git() -> None:
    """No tracked file left in hermes/terraform or host_vars/hermes-30; CI no longer validates the root."""
    tracked = subprocess.run(
        ["git", "ls-files", "hermes/terraform/", "hermes/ansible/host_vars/hermes-30/"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.split()
    assert tracked == []
    assert "hermes/terraform &&" not in (REPO / ".gitlab-ci.yml").read_text()
    assert "hermes/terraform-31 &&" in (REPO / ".gitlab-ci.yml").read_text()


def test_inventory_lists_hermes_31_alone() -> None:
    """The hermes group holds hermes-31 only, through its SSH alias."""
    hosts = yaml.safe_load((ANSIBLE_DIR / "inventory.yml").read_text())["all"]["children"]["hermes"]["hosts"]
    assert hosts == {"hermes-31": {"ansible_host": "hermes-31"}}


# --- Historical v0.20.4 playbooks: refused on a multiplexed host ------------------------------


def test_thirteen_historical_playbooks_are_kept() -> None:
    """m1 to m5 preflight/backup/rollback and profiles-preflight stay, for history and their offline tests."""
    assert [p.name for p in LEGACY_PLAYBOOKS] == [
        "m1-backup.yml", "m1-preflight.yml", "m1-rollback.yml", "m2-preflight.yml", "m2-rollback.yml",
        "m3-preflight.yml", "m3-rollback.yml", "m4-preflight.yml", "m4-rollback.yml", "m5-backup.yml",
        "m5-preflight.yml", "m5-rollback.yml", "profiles-preflight.yml",
    ]


@pytest.mark.parametrize("path", LEGACY_PLAYBOOKS, ids=lambda p: p.name)
def test_historical_playbook_runs_the_guard_first(path: Path) -> None:
    """One play; its first pre_task is the guard, under any --tags; the tasks themselves are unchanged."""
    plays = yaml.safe_load(path.read_text())
    assert len(plays) == 1
    first = plays[0]["pre_tasks"][0]
    assert first["ansible.builtin.include_role"] == {"name": "hermes_agent", "tasks_from": "legacy_v0204_guard.yml"}
    assert first["tags"] == ["always"]
    assert "hermes-30" not in plays[0]["name"]


def test_deploy_playbook_does_not_run_the_legacy_guard() -> None:
    """deploy.yml serves hermes-31: the guard would refuse it."""
    assert "legacy_v0204_guard" not in (ANSIBLE_DIR / "deploy.yml").read_text()


def run_play(tmp_path: Path, tasks: list[dict[str, Any]], hosts: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Run `tasks` on local fake hosts; the PLAY RECAP line of each host."""
    (tmp_path / "play.yml").write_text(
        yaml.safe_dump([{"hosts": "all", "connection": "local", "gather_facts": False, "tasks": tasks}])
    )
    (tmp_path / "inventory.yml").write_text(yaml.safe_dump({"all": {"hosts": hosts}}))
    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    result = subprocess.run(
        [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "inventory.yml", "play.yml",
         "-e", f"ansible_python_interpreter={sys.executable}"],
        cwd=tmp_path, env={**os.environ, "ANSIBLE_CONFIG": str(tmp_path / "ansible.cfg"), "ANSIBLE_NOCOLOR": "1"},
        capture_output=True, text=True, check=False,
    )
    lines = {line.split()[0]: line for line in result.stdout.splitlines() if " : ok=" in line}
    assert set(lines) == set(hosts), result.stdout
    return lines


def test_legacy_guard_refuses_a_multiplexed_host_only(tmp_path: Path) -> None:
    """Real task file: multiplex true is refused; false, absent or a string "false" pass."""
    tasks = yaml.safe_load((ROLE / "tasks/legacy_v0204_guard.yml").read_text())
    lines = run_play(tmp_path, tasks, {
        "multiplexed": {"hermes_gateway_multiplex": True},
        "multiplexed-str": {"hermes_gateway_multiplex": "true"},
        "standalone": {"hermes_gateway_multiplex": False},
        "role-default": {},
    })
    assert "failed=1" in lines["multiplexed"] and "failed=1" in lines["multiplexed-str"]
    assert "failed=0" in lines["standalone"] and "failed=0" in lines["role-default"]


def test_legacy_guard_refuses_hermes_31_as_declared() -> None:
    """hermes-31's host_vars turn multiplex on: every historical playbook would stop at the guard."""
    host_31 = yaml.safe_load((ANSIBLE_DIR / "host_vars/hermes-31/main.yml").read_text())
    assert host_31["hermes_gateway_multiplex"] is True


# --- komodo_periphery: no default Server name -------------------------------------------------


KOMODO = ROLES / "komodo_periphery"


def test_komodo_server_name_has_no_default_and_is_declared_per_host() -> None:
    """Empty role default, nothing at group level, hermes-31 declares its own name."""
    assert yaml.safe_load((KOMODO / "defaults/main.yml").read_text())["komodo_connect_as"] == ""
    assert "komodo_connect_as" not in yaml.safe_load((ANSIBLE_DIR / "group_vars/hermes/all/main.yml").read_text())
    host_31 = yaml.safe_load((ANSIBLE_DIR / "host_vars/hermes-31/main.yml").read_text())
    assert host_31["komodo_connect_as"] == "hermes-31"


def test_komodo_name_check_runs_first_and_refuses_an_empty_name(tmp_path: Path) -> None:
    """Real first task of the role, before any write: empty or missing refused, a name passes."""
    first = yaml.safe_load((KOMODO / "tasks/main.yml").read_text())[0]
    assert "ansible.builtin.assert" in first
    lines = run_play(tmp_path, [first], {
        "empty": {"komodo_connect_as": ""},
        "missing": {},
        "named": {"komodo_connect_as": "hermes-31"},
    })
    assert "failed=1" in lines["empty"] and "failed=1" in lines["missing"]
    assert "failed=0" in lines["named"]
