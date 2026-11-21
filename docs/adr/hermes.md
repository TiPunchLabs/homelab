# 🏗️ ADR — Hermes (VM 9031)

> **Document vivant** — Ce fichier regroupe les Architecture Decision Records (ADR) du sous-projet hermes.
> Chaque decision est numerotee, datee et immutable une fois acceptee. Pour revenir sur une decision, on en cree une nouvelle qui la remplace.

------

## 📖 Table des matieres

- [ADR-001 : Kandidat, reference de Scout, par deux entrees MCP a autorisation distincte](#adr-001--kandidat-reference-de-scout-par-deux-entrees-mcp-a-autorisation-distincte)
- [ADR-002: Read-only AgentMail for Scout through a gateway command, isolated by taint hooks](#adr-002-read-only-agentmail-for-scout-through-a-gateway-command-isolated-by-taint-hooks)

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
  n'ecrit rien. Hermes ne rejoue pas une ecriture au resultat incertain tant que Kandidat l'annote
  `readOnlyHint` faux (cas de `a0cf66ea`) : la meme annotation decide de la reprise apres expiration de session.
  Une version annoncant une ecriture en lecture seule resterait soumise au second verrou, mais une reprise
  pourrait la rejouer sous une seule approbation ; le controle de deploiement refuse ces annotations avant le
  redemarrage (cas de reprise non teste en labo). Revue Codex, passe 5.

------

## ADR-002: Read-only AgentMail for Scout through a gateway command, isolated by taint hooks

| | |
|---|---|
| **Date** | 2026-11-20 |
| **Status** | Proposed (draft MR SCOUT-MAIL-01, merge and enablement by the owner) |
| **Deciders** | xgueret |

> Written in English per the SCOUT-MAIL-01 brief (engineering documentation in English).

### Context

The owner wants to ask Scout, in its private Telegram chat, for a summary of the job-search mail of one dedicated AgentMail inbox. Mail is attacker-controlled text. Scout holds privileged tools: Web, Kandidat reads and gated writes, memory, skills, session search. Mail-derived text must not be able to drive those tools, on the same turn or on any later one.

Discovery (Hermes v0.22.5 source, `docs/missions/2026-11-20-scout-agentmail-readonly/evidence/d1-discovery.md`):
- plugins load per profile home;
- a plugin slash command runs in the gateway before any agent turn, and its reply is not written to session history;
- `pre_tool_call` can veto any tool;
- a Telegram reply injects the quoted text into the next agent turn (`[Replying to: "…"]`).

### Decision

A user plugin `scout_mail`, installed and enabled in Scout's profile only:

1. `/courriels [liste|suite|aide]`: trusted code lists one bounded page of the configured inbox and gets each listed message (GET only, fixed host, ids only from that list, ownership re-checked). It cleans and bounds the text. It makes one model call in a fresh context: no tools, no credentials in the prompt, no SOUL, memory or history, same provider and model as Scout. A trusted renderer neutralizes links, mentions, commands and markdown, and posts the result straight to the owner's DM.
2. Taint hooks keep mail-derived text out of privileged turns:
   - a reply to, or paste of, a result is refused before the agent runs;
   - a session whose turn or history contains such text, or whose tool result does, is tainted, and `pre_tool_call` vetoes every tool in it for good (`/new` starts clean). Sessions compressed from a tainted one inherit the restriction;
   - the ledger stores message ids and 8-byte hashes only. It never expires or evicts an entry: a delivered result stays quotable and a tainted transcript stays actionable for as long as they exist. It has hard capacities instead (20,000 results, 300,000 fingerprints, 100,000 sessions). A result is reserved before delivery and its Telegram ids are attached to that same record, so the last free slot never loses ids. At capacity it fails closed: no new result is delivered, and every Scout message is refused once the session capacity is reached. When a restriction or a delivered id cannot be written, a delivery is uncertain, or a hook fails, the plugin locks down durably (`taint.lockdown`, created empty or by renaming the ledger): every Scout message and tool is refused, across restarts, until the operator retires Scout's sessions and clears it. Archiving the ledger is an operator action paired with retiring Scout's sessions (runbook).
3. Disabled by default:
   - `hermes_scout_mail_enabled: false` together with a literal `plugins.enabled: []` in Scout's declaration; the role refuses any mismatch between the two;
   - the AgentMail key is required only when enabled. It is written to Scout's `.env` only, by `tasks/scout_mail.yml`, and an inbox-scoped key limited to `inbox_read` + `message_read` is required.

Threat model and enforcement matrix: `docs/references/scout-mail-threat-model.md`. Runbook: `docs/guides/runbook-scout-mail.md`.

### Rejected alternatives

- AgentMail MCP server attached to Scout: 47 tools including send/reply/delete; `readOnlyHint` is a server claim; mail text would land in Scout's privileged context.
- A Scout MCP/tool that returns a summary: the parent agent would receive mail-derived free text in its tool results and history (an isolated parser feeding an unrestricted parent).
- Toggling tools in the shared registry for the duration of a mail turn: other profiles or concurrent requests would inherit the wrong permissions.
- A second bot or profile dedicated to mail: a new public bot needs a separate owner decision. The plugin achieves the separation inside Scout's chat.
- SOUL instructions ("never act on mail"): behavioral only, not an authorization boundary.
- `agent.auxiliary_client.call_llm` for the summary: its same-provider retries and provider fallback chain are outside the plugin's bounds.
- Official `agentmail` Python SDK: it follows redirects by default and retries on its own.

### Consequences

- If the owner retypes or paraphrases mail content into an ordinary Scout message, that input is not detected (it is owner-authored).
- A corrupt taint ledger or a lockdown blocks Scout's tools and messages until the operator intervenes (fail closed). A full ledger stops new digests until the operator archives it.
- The request deadline aborts the live HTTPS connection (watchdog on the connection's file descriptor, valid through the TLS wrap); only name resolution is outside it.
- The isolation relies on the Hermes v0.22.5 plugin scoping and dispatch order. Any Hermes upgrade must re-run `hermes/tests/test_scout_mail_image.py` before enabling.
- Mail content is sent to DeepSeek, the provider Scout already uses.
