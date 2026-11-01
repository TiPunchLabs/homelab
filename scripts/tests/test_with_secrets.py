"""scripts/with-secrets with a fake `pass` on PATH and fake values only: never the real store.

Run: uv run pytest scripts/tests -q
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = Path(os.environ.get("WITH_SECRETS_SCRIPT", REPO / "scripts/with-secrets"))
FAKE = "FAKE-SECRET-{}"

FAKE_PASS = """#!/usr/bin/env bash
# Fake pass: logs the variable names it inherits, prints a fake value, fails on demand.
env | cut -d= -f1 >>"$FAKE_LOG"
[[ $1 == show ]] || exit 2
if [[ ,${FAKE_FAIL:-}, == *,$2,* ]]; then
  echo "gpg: decryption failed: No secret key" >&2
  exit 2
fi
[[ ,${FAKE_EMPTY:-}, == *,$2,* ]] && { echo; exit 0; }
printf 'FAKE-SECRET-%s\\nsecond line\\n' "$2"
"""

ENTRIES = [
    "proxmox/terraform-token-id", "proxmox/terraform-token-secret", "proxmox/lxc-root-password",
    "github/terraform-token", "gitlab/terraform-token", "gitlab/tipunchlabs-group-id",
    "github/gitlab-push-mirror-tipunchlabs", "tipunchlabs/ovh/application_key",
    "tipunchlabs/ovh/application_secret", "tipunchlabs/ovh/consumer_key",
    "tipunchlabs/ovh/dynhost_password", "tipunchlabs/ovh/portail_public_ip", "ansible/vault",
]

SECRET_VARS = {
    "proxmox": {"TF_VAR_pm_api_token_id", "TF_VAR_pm_api_token_secret"},
    "lxc": {"TF_VAR_pm_api_token_id", "TF_VAR_pm_api_token_secret", "TF_VAR_ct_root_password"},
    "github": {"TF_VAR_github_token"},
    "gitlab": {"TF_VAR_gitlab_token", "TF_VAR_gitlab_namespace_id", "TF_VAR_github_mirror_token"},
    "ovh": {"TF_VAR_ovh_application_key", "TF_VAR_ovh_application_secret", "TF_VAR_ovh_consumer_key",
            "TF_VAR_dynhost_password", "TF_VAR_portail_current_ip"},
    "tfstate": {"TF_HTTP_PASSWORD"},
    "vault": {"ANSIBLE_VAULT_PASSWORD"},
}
ALL_SECRET_VARS = set().union(*SECRET_VARS.values())


@pytest.fixture
def sandbox(tmp_path: Path) -> dict[str, str]:
    """A fake store holding every entry the script knows, and a PATH whose `pass` is the fake."""
    store = tmp_path / "store"
    for entry in ENTRIES:
        (store / f"{entry}.gpg").parent.mkdir(parents=True, exist_ok=True)
        (store / f"{entry}.gpg").write_text("not a real gpg file\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "pass").write_text(FAKE_PASS)
    (bin_dir / "pass").chmod(0o755)
    return {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "PASSWORD_STORE_DIR": str(store),
        "FAKE_LOG": str(tmp_path / "pass-env.log"),
        "TF_HTTP_USERNAME": "fake-user",
    }


def run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    """Run with-secrets with exactly `env`."""
    return subprocess.run([str(SCRIPT), *args], env=env, capture_output=True, text=True, check=False)


def child_vars(stdout: str) -> dict[str, str]:
    """The secret variables seen by the child `env`."""
    pairs = (line.split("=", 1) for line in stdout.splitlines() if "=" in line)
    return {k: v for k, v in pairs if k in ALL_SECRET_VARS}


@pytest.mark.parametrize("profile", sorted(SECRET_VARS))
def test_each_profile_gives_the_child_its_variables_only(sandbox: dict[str, str], profile: str) -> None:
    """Valid profile: the child sees exactly that profile's variables, first line of each entry."""
    result = run(sandbox, profile, "--", "env")
    assert result.returncode == 0, result.stderr
    seen = child_vars(result.stdout)
    assert set(seen) == SECRET_VARS[profile]
    assert all(v.startswith("FAKE-SECRET-") and "\n" not in v for v in seen.values())
    assert result.stderr == ""


def test_documented_combination_for_dockhost(sandbox: dict[str, str]) -> None:
    """proxmox,tfstate, as in dockhost/README.md, merges both profiles."""
    result = run(sandbox, "proxmox,tfstate", "--", "env")
    assert result.returncode == 0, result.stderr
    assert set(child_vars(result.stdout)) == SECRET_VARS["proxmox"] | SECRET_VARS["tfstate"]


def test_arguments_and_exit_code_pass_through(sandbox: dict[str, str]) -> None:
    """Existing calls (sh -c '...' presence checks) keep their arguments and exit code."""
    ok = run(sandbox, "proxmox", "--", "sh", "-c", 'test -n "$TF_VAR_pm_api_token_id" && echo present')
    assert (ok.returncode, ok.stdout) == (0, "present\n")
    assert run(sandbox, "proxmox", "--", "sh", "-c", "exit 7").returncode == 7


def test_pass_never_inherits_already_loaded_secrets(sandbox: dict[str, str]) -> None:
    """Secrets are exported only after every pass call."""
    assert run(sandbox, "lxc,gitlab,ovh", "--", "true").returncode == 0
    inherited = set(Path(sandbox["FAKE_LOG"]).read_text().split())
    assert not inherited & ALL_SECRET_VARS


def test_calling_environment_is_not_modified(sandbox: dict[str, str]) -> None:
    """The secrets live in the child only; a following command in the same env sees none."""
    run(sandbox, "proxmox", "--", "true")
    after = subprocess.run(["env"], env=sandbox, capture_output=True, text=True, check=True)
    assert not child_vars(after.stdout)


@pytest.mark.parametrize("args", [[], ["proxmox"], ["proxmox", "true"], ["proxmox", "-x", "true"]])
def test_bad_usage_exits_2_with_the_profile_map(sandbox: dict[str, str], args: list[str]) -> None:
    """Missing `--` or command: usage with the profile-to-root map, nothing run."""
    result = run(sandbox, *args)
    assert result.returncode == 2
    assert "usage: with-secrets" in result.stderr and "ovh-dns-terraform" in result.stderr


@pytest.mark.parametrize("profiles", ["nope", "proxmox,nope", "", "proxmox,,ovh"])
def test_unknown_profile_runs_nothing(sandbox: dict[str, str], profiles: str, tmp_path: Path) -> None:
    """Unknown or empty profile name: exit 2 before the command runs."""
    marker = tmp_path / "ran"
    result = run(sandbox, profiles, "--", "touch", str(marker))
    assert result.returncode == 2
    assert "unknown profile" in result.stderr or "no profile given" in result.stderr
    assert not marker.exists()
    assert "FAKE-SECRET" not in result.stderr + result.stdout


def test_missing_entry_is_named_without_any_value(sandbox: dict[str, str], tmp_path: Path) -> None:
    """Absent entry, after others were read: named, distinct from a read error, no value leaked."""
    Path(sandbox["PASSWORD_STORE_DIR"], "proxmox/lxc-root-password.gpg").unlink()
    marker = tmp_path / "ran"
    result = run(sandbox, "lxc", "--", "touch", str(marker))
    assert result.returncode == 1
    assert "missing pass entry: proxmox/lxc-root-password" in result.stderr
    assert "FAKE-SECRET" not in result.stderr + result.stdout
    assert not marker.exists()


def test_pass_read_error_is_named_without_any_value(sandbox: dict[str, str], tmp_path: Path) -> None:
    """pass/gpg failure: entry named, gpg message kept, no value leaked, command not run."""
    marker = tmp_path / "ran"
    result = run({**sandbox, "FAKE_FAIL": "gitlab/tipunchlabs-group-id"}, "gitlab", "--", "touch", str(marker))
    assert result.returncode == 1
    assert "cannot read pass entry: gitlab/tipunchlabs-group-id" in result.stderr
    assert "decryption failed" in result.stderr
    assert "FAKE-SECRET" not in result.stderr + result.stdout
    assert not marker.exists()


def test_empty_entry_is_refused(sandbox: dict[str, str]) -> None:
    """An entry whose first line is empty is an error, not an empty variable."""
    result = run({**sandbox, "FAKE_EMPTY": "ansible/vault"}, "vault", "--", "true")
    assert result.returncode == 1
    assert "empty pass entry: ansible/vault" in result.stderr


def test_tfstate_requires_the_username_from_envrc(sandbox: dict[str, str]) -> None:
    """Without TF_HTTP_USERNAME the backend would fail late and vaguely: refuse early."""
    env = {k: v for k, v in sandbox.items() if k != "TF_HTTP_USERNAME"}
    result = run(env, "proxmox,tfstate", "--", "true")
    assert result.returncode == 1
    assert "TF_HTTP_USERNAME is not set" in result.stderr
    assert "FAKE-SECRET" not in result.stderr


def test_script_never_enables_tracing() -> None:
    """No `set -x` / `set -o xtrace` that would print the assignments."""
    code = [line for line in SCRIPT.read_text().splitlines() if not line.lstrip().startswith("#")]
    assert not any("set -x" in line or "xtrace" in line for line in code)


@pytest.mark.parametrize("path", ["gitlab-terraform/tfplan", "dockhost/terraform/tfplan.9090", "caddy/terraform/x.tfplan"])
def test_saved_plans_are_ignored_by_git(path: str) -> None:
    """Saved plans hold sensitive inputs in clear text: git must ignore the usual names."""
    assert subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=REPO, check=False).returncode == 0


def test_envrc_example_exports_no_secret_name() -> None:
    """.envrc.example exports none of the variables with-secrets owns."""
    example = (REPO / ".envrc.example").read_text()
    assert not any(f"export {var}=" in example for var in ALL_SECRET_VARS)
