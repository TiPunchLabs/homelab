"""Guard the dns_resolver role against a cloud-init instance-id change.

Proxmox derives the NoCloud instance-id from the cloud-init content, so any
`qm set` on cloud-init options makes the next boot look like a new instance.
These tests pin the two cloud.cfg.d files that keep such a boot from undoing
the role, and the scope that keeps them away from templates. Run from the
repo root:
    uv run pytest hermes/tests -q
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import REPO, ROLES

TASKS = ROLES / "dns_resolver/tasks/main.yml"
CFG_DIR = "/etc/cloud/cloud.cfg.d"
NETWORK_CFG = f"{CFG_DIR}/99-disable-network-config.cfg"
SSH_CFG = f"{CFG_DIR}/99-preserve-ssh-host-keys.cfg"


def load_tasks() -> list[dict[str, Any]]:
    """Return the dns_resolver task list."""
    return yaml.safe_load(TASKS.read_text())


def task_writing(dest: str) -> tuple[int, dict[str, Any]]:
    """Return the index and the copy task that writes `dest`."""
    matches = [
        (i, t) for i, t in enumerate(load_tasks()) if t.get("ansible.builtin.copy", {}).get("dest") == dest
    ]
    assert len(matches) == 1, f"expected exactly one task writing {dest}, got {len(matches)}"
    return matches[0]


def task_index(name: str) -> int:
    """Return the position of the task called `name`."""
    return next(i for i, t in enumerate(load_tasks()) if t["name"] == name)


@pytest.mark.parametrize(
    ("dest", "expected"),
    [
        (NETWORK_CFG, {"network": {"config": "disabled"}}),
        (SSH_CFG, {"ssh_deletekeys": False}),
    ],
)
def test_guard_file_content_is_exact(dest: str, expected: dict[str, Any]) -> None:
    """Each guard file parses to exactly its one setting, with the right types."""
    _, task = task_writing(dest)
    assert yaml.safe_load(task["ansible.builtin.copy"]["content"]) == expected


@pytest.mark.parametrize("dest", [NETWORK_CFG, SSH_CFG])
def test_guard_file_is_root_owned_and_world_readable(dest: str) -> None:
    """cloud-init runs as root but `cloud-init query` and status read as users."""
    _, task = task_writing(dest)
    copy = task["ansible.builtin.copy"]
    assert (copy["owner"], copy["group"], copy["mode"]) == ("root", "root", "0644")


@pytest.mark.parametrize("dest", [NETWORK_CFG, SSH_CFG])
def test_guard_is_unconditional(dest: str) -> None:
    """No `when`: the guard must also be laid when the netplan strip is a no-op."""
    _, task = task_writing(dest)
    assert "when" not in task


@pytest.mark.parametrize("dest", [NETWORK_CFG, SSH_CFG])
def test_guard_is_laid_before_netplan_is_touched(dest: str) -> None:
    """A failure later in the play must not leave a stripped netplan unguarded."""
    index, _ = task_writing(dest)
    assert index < task_index("Strip the nameservers from the cloud-init netplan")
    assert index < task_index("Point the system resolver at dnsmasq")


def test_role_is_only_applied_to_hermes() -> None:
    """The guard is per existing VM: only hermes/ansible/deploy.yml applies the role."""
    users = sorted(
        str(p.relative_to(REPO))
        for p in REPO.rglob("*.yml")
        if ".git" not in p.parts
        and ".venv" not in p.parts
        and "dns_resolver" not in p.parts
        and "dns_resolver" in p.read_text(errors="ignore")
    )
    assert users == ["hermes/ansible/deploy.yml"]

    plays = yaml.safe_load((REPO / "hermes/ansible/deploy.yml").read_text())
    hosting = [play["hosts"] for play in plays if any(r["role"] == "dns_resolver" for r in play.get("roles", []))]
    assert hosting == [["hermes"]]


def test_template_build_does_not_ship_the_guard() -> None:
    """Template 9001 keeps the cloud-init defaults: fresh network and host keys per clone."""
    template_tasks = (REPO / "proxmox/ansible/roles/configure/tasks/tasks_generate_vm_template.yml").read_text()
    for marker in ("99-disable-network-config", "99-preserve-ssh-host-keys", "ssh_deletekeys", "config: disabled"):
        assert marker not in template_tasks


@pytest.mark.skipif(shutil.which("cloud-init") is None, reason="cloud-init not installed")
def test_ssh_guard_passes_the_cloud_config_schema(tmp_path: Path) -> None:
    """`ssh_deletekeys` is a cloud-config key: let cloud-init itself validate it.

    `network` is system-only config, which `cloud-init schema` rejects as
    user-data, hence the exact-parse test above instead.
    """
    _, task = task_writing(SSH_CFG)
    cfg = tmp_path / "ssh.cfg"
    cfg.write_text("#cloud-config\n" + task["ansible.builtin.copy"]["content"])
    result = subprocess.run(
        ["cloud-init", "schema", "-c", str(cfg)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
