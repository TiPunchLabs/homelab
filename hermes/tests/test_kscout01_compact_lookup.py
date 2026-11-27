"""KANDIDAT-SCOUT-01 — Scout looks Kandidat up with the compact, targeted and paged reads of Kandidat ADR-009.

The Kandidat side (`tipunchlabs/kandidat`, branch feat/scout-compact-retrieval) is tested there and with Hermes'
own MCP client against a copy of production data (private evidence). Here: what the HomeLab declaration changes,
offline. The SOUL must be deployed only after that Kandidat release (README, "Compact Kandidat lookups").
"""

from __future__ import annotations

import hashlib
import subprocess
from typing import Any

import pytest
import yaml
from conftest import REPO, ROLE
from test_m2_cafe_ia import GROUP_VARS

SOUL = ROLE / "files/profiles/job-search/SOUL.md"
M43_SOUL = "f712d3359f8a9bcb3a1eb4481435d11e5c17c31cabac9c61e6ca3f4e3f0382fa"
SCOUT03_SOUL = "777470b3fcaced3a4f7e7322e30aed238bc61907bb56d8b4eb16d2c0ab5b2fc1"
SCOUT04_SOUL = "7fb4915a7c8951e60df769a40c6bd6aff1e4380db1b84b8abe94676bfd7073a9"
READS = {
    "list_cibles", "get_cible_detail", "list_candidatures", "get_candidature", "get_candidature_history",
    "search_candidatures", "get_stats",
}


@pytest.fixture(scope="module")
def scout() -> dict[str, Any]:
    """Scout's declaration, as written."""
    return yaml.safe_load(GROUP_VARS.read_text())["hermes_profile_job_search"]


def test_c01_predecessors_add_the_deployed_scout04_soul(scout: dict[str, Any]) -> None:
    """The guard replaces M4.3, SCOUT-03 or SCOUT-04 (6565906, live on hermes-31 since 2026-11-13), nothing else."""
    # SCOUT-CRON appends the KANDIDAT-SCOUT-01 SOUL, live on hermes-31 on 2026-11-24.
    assert scout["soul_predecessor_sha256"][:3] == [M43_SOUL, SCOUT03_SOUL, SCOUT04_SOUL]
    assert scout["soul_predecessor_sha256"][3:] == ["7dc753fe06306cb334bb2c25f7fb4cb26aa6ca317d8e12fb6f7cd98607a4fd0a"]
    previous = subprocess.run(
        ["git", "show", "6565906:hermes/ansible/roles/hermes_agent/files/profiles/job-search/SOUL.md"],
        cwd=REPO, capture_output=True, check=False,
    )
    if previous.returncode != 0:
        pytest.skip("commit 6565906 not in this checkout: SCOUT-04 SOUL provenance not checked")
    assert hashlib.sha256(previous.stdout).hexdigest() == SCOUT04_SOUL
    assert hashlib.sha256(SOUL.read_bytes()).hexdigest() not in scout["soul_predecessor_sha256"]


def test_c01_permissions_unchanged(scout: dict[str, Any]) -> None:
    """Same automatic reads, same per-call writes, no file or terminal tool, no MCP budget raised."""
    cfg = scout["config"]
    assert set(cfg["mcp_servers.kandidat"]["tools"]["include"]) == READS
    assert set(cfg["mcp_servers.kandidat_confirm"]["tools"]["include"]) == {
        "create_candidature", "create_cible", "update_candidature", "update_cible",
    }
    assert cfg["mcp_servers.kandidat_confirm"]["trust"] == "untrusted"
    assert cfg["skills.creation_nudge_interval"] == 0
    assert not [k for k in cfg if k.startswith("tool_budget")]
    for platform in ("telegram", "api_server", "cli", "cron"):
        assert not {"file", "terminal", "code_execution"} & set(cfg[f"platform_toolsets.{platform}"]), platform


@pytest.mark.parametrize(
    "rule",
    [
        '`list_cibles` et `list_candidatures` : toujours avec `fields: "compact"`',
        "`search_candidatures` et `limit: 20`",
        "**un seul mot distinctif** du nom, sans ponctuation",
        "`q` = le domaine de son site s'il est connu",
        "ne cherche jamais un nom composé entier",
        "Si le nom n'a pas de mot distinctif (sigle court, mots courants), c'est « non vérifiable »",
        "jamais de liste complète sans lui",
        "`list_candidatures` avec `url` = lien direct de l'offre",
        "Aucun résultat ne prouve pas qu'elle est nouvelle",
        "`list_cibles` puis `list_candidatures`, chacun avec `q`",
        "Casse et accents sont ignorés, pas les espaces ni la ponctuation",
        "Tant que `has_more` est vrai, demande la page suivante (`offset` = `next_offset`)",
        "**déjà suivie** : même URL à l'étape 1, ou même identifiant ATS lu dans la fiche",
        "**correspondance à vérifier**",
        "**entreprise suivie, offre absente**",
        "**absente de Kandidat** : seulement si les étapes 1 et 2 sont faites (mot distinctif, et domaine s'il est connu), toutes les pages lues",
        "**présence dans Kandidat non vérifiable** : erreur, page non lue, nom sans mot distinctif, ou réponse sans `total` ni `has_more`",
        "4. **Kandidat** : classement ci-dessus, statut",
        # Kept from SCOUT-03/04.
        "Deux offres de la même entreprise restent deux offres",
        "À un nouveau message, avant toute nouvelle recommandation ou proposition d'écriture, relis les fiches",
        "**Recherche bornée**",
        "présence physique programmée et récurrente hors de Guadeloupe",
    ],
)
def test_c02_soul_rules(rule: str) -> None:
    """The targeted lookup protocol and its five outcomes are in Scout's SOUL.md."""
    assert rule in SOUL.read_text()


@pytest.mark.parametrize(
    "obsolete",
    ["persisted-output", "au plus une fois par demande", "respecte la casse", "`get_candidature` avec le slug probable"],
)
def test_c02_obsolete_workarounds_removed(obsolete: str) -> None:
    """The preview and case-sensitivity workarounds of SCOUT-04 are gone, proven fixed in Kandidat ADR-009."""
    assert obsolete not in SOUL.read_text()
