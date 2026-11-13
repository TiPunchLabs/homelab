# 🏗️ ADR — Hermes (VM 9031)

> **Document vivant** — Ce fichier regroupe les Architecture Decision Records (ADR) du sous-projet hermes.
> Chaque decision est numerotee, datee et immutable une fois acceptee. Pour revenir sur une decision, on en cree une nouvelle qui la remplace.

------

## 📖 Table des matieres

- [ADR-001 : Kandidat, reference de Scout, par deux entrees MCP a autorisation distincte](#adr-001--kandidat-reference-de-scout-par-deux-entrees-mcp-a-autorisation-distincte)

------

## ADR-001 : Kandidat, reference de Scout, par deux entrees MCP a autorisation distincte

| | |
|---|---|
| **Date** | 2026-11-12 |
| **Statut** | Propose (MR SCOUT-03, fusion par le proprietaire) |
| **Decideurs** | xgueret |

### Contexte

Scout (profil `job-search`) a ete deploye en M4.3 sans aucun serveur MCP. Sans historique, il a repropose en
novembre 2026 des entreprises deja suivies ou deja candidatees : sa seule memoire etait `session_search`, qui
ne voit que ses propres conversations. L'ancien bot emploi (profil `default` avant Nora) dedoublonnait dans
Kandidat, avec les 23 outils MCP actifs, dont `delete_cible` (cascade sur les candidatures).

Kandidat n'a aucune authentification : l'API (`:8000`) et le serveur MCP (`:3001`) sont joignables depuis le
LAN. Le serveur MCP est un proxy semantique, il ne filtre rien. Hermes v0.22.5 offre deux mecanismes par
serveur MCP et par profil : `tools.include` (liste blanche ; un outil hors liste n'est jamais enregistre) et
`trust: untrusted` (toute invocation d'un outil sans `readOnlyHint=true` demande l'approbation de
l'utilisateur, a chaque appel, refusee d'office sans personne pour repondre : cron, `-q`).

La politique approuvee distingue des ecritures automatiques (ajouter une offre verifiee, non candidatee) et
des ecritures a confirmer (changement de statut, nouvelle entreprise, exclusion), et interdit suppressions,
operations de masse, envois, administration.

### Decision

**Kandidat devient la reference de Scout pour les entreprises, offres, candidatures et leur historique. Il y
accede par deux entrees MCP vers le meme serveur, une par niveau d'autorisation, sans adaptateur ni
modification de Kandidat :**

- `kandidat` (`trust: full`) : `list_cibles`, `get_cible_detail`, `list_candidatures`, `get_candidature`,
  `get_candidature_history`, `search_candidatures`, `get_stats` : lectures seules ;
- `kandidat_confirm` (`trust: untrusted`) : `create_candidature`, `create_cible`, `update_candidature`,
  `update_cible`, chacun approuve par l'utilisateur a chaque appel ;
- aucun autre outil ; `kandidat_confirm` absent de la plateforme cron ; `no_mcp` maintenu pour Nora et
  Kaféine.

### Justification

| Critere | Deux entrees MCP (choisi) | Une entree `untrusted` | Adaptateur MCP dedie |
|---------|---------------------------|------------------------|----------------------|
| Ecriture automatique d'une offre neutre | Non (Kandidat ne sait pas creer une offre neutre, voir plus bas) | Non | Oui, si l'adaptateur corrige la semantique |
| Statuts et nouvelles entreprises | Approbation par appel (Hermes) | Idem | A coder |
| Code nouveau a maintenir | Aucun cote Kandidat ; un controle de deploiement | Aucun | Un service, son image, son deploiement |
| Doublon d'entreprise au rejeu | Evite : `create_cible` toujours approuve | Idem | A coder |
| Restriction par champ / statut | Non (approbation humaine a la place) | Non | Oui |
| Cron : lectures seules, aucun outil d'ecriture expose | Oui (`kandidat` seul en cron) | Non, outils d'ecriture exposes puis refuses | Oui |
| Controle de deploiement : lectures sans annotation d'ecriture, ecritures toutes sous approbation | Oui, un serveur par niveau | Non, verdict melange | A coder |

`create_candidature` ne peut pas etre automatique non plus : a Kandidat `a0cf66ea`
(`services/candidature.py`), il force `brouillon` mais pose `date_candidature` a la date du jour et passe la
cible en `contactee`. Une insertion sans accord marquerait l'entreprise contactee : contraire a la politique
(« jamais candidatee »). L'ecriture automatique d'une offre est donc **non livree** ; elle demande d'abord une
creation neutre cote Kandidat (sans date, sans `contactee`). Revue Codex, passe 3.
`create_cible` n'a aucun controle de doublon cote API : il ne peut pas etre automatique. `update_candidature`
accepte tout champ et tout statut valide : le filtrage par champ n'existe ni dans Hermes ni dans Kandidat ;
l'approbation humaine par appel le remplace, ce qui est plus strict que la politique pour les faits declares
par l'utilisateur (une approbation de plus).

### Consequences

- Le controle de deploiement `hermes_checks.py mcp` connecte les serveurs avec le code de Hermes et echoue si
  un outil hors liste est expose, si une ecriture echappe a l'approbation (annotations relues en direct), si
  la configuration derive, ou si un autre profil a un serveur MCP actif.
- Second verrou local sur `kandidat_confirm` : `tool_costs` (2 par outil) au-dessus de `spend_limit` (1). Hermes
  demande alors l'approbation a chaque appel meme si le serveur annoncait un jour ces outils en lecture seule
  (le verrou `untrusted` depend de `readOnlyHint`, fourni par le serveur). Revue Codex, constat 3.
- L'invite d'approbation de Hermes nomme l'outil, le serveur et le cout, pas les arguments : approuver,
  c'est autoriser « un `create_candidature` », pas une fiche donnee. La correspondance entre la modification
  decrite et l'appel envoye releve du comportement (SOUL : modification exacte ecrite juste avant, une seule
  ecriture a la fois), pas d'une autorisation liee aux arguments. Ce que Hermes impose, prouve en labo v0.22.5
  par la vraie file d'approbation de la gateway : une invite par appel ; rien n'est retenu apres `once`,
  `session` ou `always` ; deux ecritures paralleles dans une meme conversation recoivent deux invites (le
  verrou par conversation du second verrou les serialise) ; une autre conversation ne peut pas repondre a
  l'invite de Scout ; `/yolo` ne touche pas ce verrou.
- Garder une piste sans la dater ni marquer l'entreprise contactee est impossible par `create_candidature` :
  Scout la garde dans sa reponse. Une creation neutre releve d'une mission Kandidat distincte.
- Kandidat ne garde qu'une fiche par nom d'entreprise : une deuxieme offre prend un nom qualifie
  (« Acme DevOps »), convention deja en usage dans Kandidat.
- La frontiere borne l'agent, pas le LAN : tout poste du LAN peut toujours ecrire dans Kandidat. Une
  authentification de Kandidat reste a decider a part.
- Les dates d'historique de statut sont des dates d'enregistrement : un fait passe sans date garde ses dates
  vides et sa provenance dans le commentaire.
- Si Kandidat ne repond pas, les outils manquent ou echouent : Scout cherche sur le Web en le disant et
  n'ecrit rien. Hermes ne rejoue pas une ecriture au resultat incertain.
