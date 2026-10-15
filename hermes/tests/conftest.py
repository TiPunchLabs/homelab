"""Shared fixtures: run the real hermes_agent task files with ansible-playbook.

The role's host-side tasks (env_keys.yml, soul_seed.yml, profile_content.yml,
validate.yml) are executed for real, against localhost and a throwaway
directory under tmp_path standing in for /opt/hermes/data. Nothing touches
hermes-30, and every token is a fake.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
ROLES = REPO / "hermes/ansible/roles"
ROLE = ROLES / "hermes_agent"
ANSIBLE_PLAYBOOK = Path(sys.executable).parent / "ansible-playbook"

# Shaped like a BotFather token, obviously fake.
FAKE_TOKEN = "123456789:FAKE-token-for-tests-ONLY-aaaaaaaaaaaa"
FAKE_TOKEN_2 = "987654321:FAKE-token-for-tests-ONLY-bbbbbbbbbbbb"

RunTasks = Callable[..., subprocess.CompletedProcess[str]]


@pytest.fixture
def run_tasks(tmp_path: Path) -> RunTasks:
    """Return a runner that includes one hermes_agent task file on localhost."""
    if not ANSIBLE_PLAYBOOK.exists():
        pytest.skip("ansible-playbook not installed in this environment")
    cfg = tmp_path / "ansible.cfg"
    cfg.write_text("[defaults]\n")

    def run(tasks_from: str, variables: dict[str, Any], *extra_args: str) -> subprocess.CompletedProcess[str]:
        """Run `tasks_from` with `variables`; return the completed process."""
        variables = {
            "hermes_puid": os.getuid(),
            "hermes_pgid": os.getgid(),
            "ansible_python_interpreter": sys.executable,
            **variables,
        }
        (tmp_path / "vars.json").write_text(json.dumps(variables))
        (tmp_path / "play.yml").write_text(
            "- hosts: localhost\n"
            "  connection: local\n"
            "  gather_facts: false\n"
            "  tasks:\n"
            "    - ansible.builtin.include_role:\n"
            "        name: hermes_agent\n"
            f"        tasks_from: {tasks_from}\n"
        )
        env = {
            **os.environ,
            "ANSIBLE_CONFIG": str(cfg),
            "ANSIBLE_ROLES_PATH": str(ROLES),
            "ANSIBLE_LOCAL_TEMP": str(tmp_path / ".ansible-tmp"),
            "ANSIBLE_NOCOLOR": "1",
            "ANSIBLE_RETRY_FILES_ENABLED": "0",
        }
        return subprocess.run(
            [str(ANSIBLE_PLAYBOOK), "-i", "localhost,", "play.yml", "-e", "@vars.json", *extra_args],
            cwd=tmp_path,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )

    return run


def recap(result: subprocess.CompletedProcess[str]) -> dict[str, int]:
    """Parse the PLAY RECAP counters for localhost."""
    for line in result.stdout.splitlines():
        if line.startswith("localhost"):
            return {k: int(v) for k, v in (pair.split("=") for pair in line.split(":", 1)[1].split())}
    raise AssertionError(f"no recap in output:\n{result.stdout}\n{result.stderr}")
