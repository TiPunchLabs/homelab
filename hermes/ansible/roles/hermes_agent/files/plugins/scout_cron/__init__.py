"""scout_cron — Scout manages its own scheduled tasks, under code-enforced guards.

Registered in Scout's profile only (``plugins.enabled`` of job-search). It adds:
- a ``pre_tool_call`` guard on Hermes' ``cronjob_manage``: owner's private Telegram chat only, never in a
  cron run; field, schedule (at most one run a day), delivery, size and job-count policy; for create,
  update, remove and resume, the exact text to be saved is posted by this code, then the call is sent
  to Hermes' approval gate with a single-use rule key (no tap, nothing saved). ``run`` is refused;
- the approval is BOUND to this tool call: the immutable job id, a fingerprint of the job shown, and the
  canonical arguments. ``cronjob_manage`` is replaced in Scout's profile only (operator grant
  ``tools.override``) by ``manage``, which runs after the tap and re-checks everything (context, /yolo,
  other plugins' veto, policy, binding, job cap) right before handing Hermes the canonical arguments;
  stale approval = nothing saved. A create's slot reservation belongs to its tool call;
- a cron-run tool-call cap (all tools, and web tools apart), per execution;
- the ``scout_task_record`` tool: in a cron run, the running job's journal (Hermes notepad, injected at
  the start of every run) and its ledger of vacancies already alerted; in the owner's chat, one action,
  ``feedback_add``, under the same approval;
- ``transform_tool_result``: next run in Guadeloupe time and UTC on cronjob_manage results;
- ``/taches-scout``: the owner's read-only view of the jobs, journals and ledger counts.
Fails closed: unreadable settings, an unknown context or a Hermes error refuse the call.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import policy
from .config import SettingsError, load_settings
from .hermes_port import HermesPort
from .ledger import Ledger, LedgerError
from .schedule import ScheduleError, format_fr, next_runs

logger = logging.getLogger("scout_cron")

PROFILE = "job-search"
TOOL = "scout_task_record"
CRON_TOOL = "cronjob_manage"
WEB_TOOLS = {"web_search", "web_extract"}
CRON_ACTIONS = {"journal_get", "journal_set", "check_alerted", "mark_alerted", "alerted_count"}
CHAT_ACTIONS = {"feedback_add"}
MAX_CHECK_URLS = 50
MAX_MARK_ITEMS = 20
PENDING_TTL_S = 900.0

MSG_SETTINGS = "Planification indisponible : réglages de sécurité illisibles (opérateur)."
MSG_PROFILE = "Planification réservée à Scout."
MSG_CRON = "Une exécution planifiée ne peut ni créer, ni modifier, ni supprimer de tâche."
MSG_CHANNEL = ("La gestion des tâches planifiées n'est possible que dans la conversation Telegram privée "
               "du propriétaire.")
MSG_BYPASS = ("Planification refusée : l'approbation automatique (/yolo ou approvals.mode: off) est active ; "
              "chaque tâche doit être approuvée explicitement.")
MSG_VETO = "Action refusée : un autre contrôle de sécurité bloque les outils dans cette conversation."
MSG_POST = "Impossible d'afficher la proposition complète : rien n'est enregistré."
MSG_ERROR = "Contrôle de planification en erreur : rien n'est enregistré."
MSG_UNSAFE_POST = ("Proposition refusée : Telegram ne l'afficherait pas telle quelle ({why}) ; rien n'est affiché "
                   "ni enregistré. Reformuler sans cette forme (tableau, liste de cases à cocher, <details>, $$, "
                   "ligne de ```).")
MSG_LONG_POST = ("Proposition refusée : elle ferait {size} caractères affichés, plus qu'un seul message Telegram "
                 "({budget}) ; rien n'est affiché ni enregistré. Raccourcir les instructions ou le nom.")
MSG_GUARD = ("Planification indisponible : la garde d'enregistrement n'est pas installée (opérateur : "
             "plugins.entries.scout_cron.granted_capabilities: [tools.override]).")
MSG_STALE = ("Rien n'est enregistré : l'approbation portait sur un état qui a changé depuis (tâche renommée, "
             "modifiée, supprimée, ou demande différente). Liste les tâches, puis refais la demande : une "
             "nouvelle proposition sera affichée.")
MSG_UNAPPROVED = "Rien n'est enregistré : aucune approbation valide pour cet appel (refais la demande)."
MSG_RECORD_CONTEXT = ("Le journal d'une tâche n'est accessible qu'à son exécution planifiée ; en conversation, "
                      "seule l'action feedback_add est permise au propriétaire.")

TOOL_SCHEMA = {
    "name": TOOL,
    "description": (
        "Journal et registre d'une tâche planifiée de Scout. Pendant une EXÉCUTION PLANIFIÉE seulement : le bloc "
        "« Job notepad » en tête de ta consigne contient le journal (journal) et les retours du propriétaire "
        "(feedback) : lis-le d'abord et ignore la commande CLI qu'il mentionne. check_alerted(urls) avant de "
        "signaler une offre ; mark_alerted(items : URL directe et intitulé) pour chaque offre signalée ; en fin "
        "d'exécution, journal_set(text) réécrit un journal court (problèmes récurrents, requête ou source en "
        "cause, ajustement testé et résultat) ; journal_get, alerted_count. Tes appels d'outils sont plafonnés : "
        "à la limite, termine et signale-le. En conversation avec le propriétaire seulement : "
        "feedback_add(job_id, text) ajoute un retour à une tâche, après son approbation."),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": sorted(CRON_ACTIONS | CHAT_ACTIONS)},
            "text": {"type": "string", "description": "journal_set : journal complet ; feedback_add : le retour."},
            "urls": {"type": "array", "items": {"type": "string"}, "description": "check_alerted : URL d'offres."},
            "items": {"type": "array", "items": {"type": "object", "properties": {
                "url": {"type": "string"}, "title": {"type": "string"}}, "required": ["url"]},
                "description": "mark_alerted : offres signalées (URL directe et intitulé)."},
            "job_id": {"type": "string", "description": "feedback_add : identifiant ou nom de la tâche."},
        },
        "required": ["action"],
    },
}


def _json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _block(message: str) -> dict:
    return {"action": "block", "message": message}


def _fail(message: str) -> str:
    return _json({"success": False, "error": message})


@dataclass
class _Binding:
    """What one approval covers: one tool call, one job version, one set of canonical arguments."""

    tool: str
    action: str
    job_id: str | None
    fingerprint: str | None
    dispatch: dict
    expect: dict | None
    hook_kwargs: dict
    reserves_slot: bool
    expiry: float


class _Plugin:
    def __init__(self, ctx: Any, home: Path, port: HermesPort | None = None,
                 settings_path: Path | None = None) -> None:
        self.ctx = ctx
        self.home = home
        self.port = port or HermesPort(ctx, home)
        self.settings = None
        self.error: str | None = None
        try:
            self.settings = load_settings(settings_path or Path(__file__).with_name("settings.json"))
        except SettingsError as exc:
            self.error = str(exc)
            logger.warning("scout_cron settings invalid: %s", exc)
        if self.settings is not None and not self.settings.enabled:
            self.error = "disabled"
        self.ledger = None
        if self.settings is not None:
            lim = self.settings.limits
            self.ledger = Ledger(home / "plugin-data" / "scout_cron" / "ledger", lim.ledger_days, lim.ledger_max)
        self._lock = threading.RLock()
        self._bindings: dict[str, _Binding] = {}  # by tool_call_id
        self._runs: dict[str, list[int]] = {}
        self.guard_installed = False  # set by register() once the cronjob_manage override is in place

    # ---- context --------------------------------------------------------------------------------

    def _usable(self) -> bool:
        return self.error is None and self.settings is not None

    def _profile_ok(self) -> bool:
        try:
            return self.port.profile_name() == PROFILE
        except Exception:
            return False

    def _execution(self) -> tuple[bool, Any]:
        """(in_cron, execution). An unreadable context counts as a cron run (fail closed)."""
        try:
            execution = self.port.cron_execution()
            marker = self.port.session("HERMES_CRON_SESSION")
        except Exception:
            return True, None
        in_cron = execution is not None or marker.strip().lower() not in ("", "0", "false", "no")
        return in_cron, execution

    def _owner_chat(self) -> bool:
        try:
            platform = self.port.session("HERMES_SESSION_PLATFORM")
            chat_type = self.port.session("HERMES_SESSION_CHAT_TYPE")
            user = self.port.session("HERMES_SESSION_USER_ID")
            chat = self.port.session("HERMES_SESSION_CHAT_ID")
        except Exception:
            return False
        owners = self.settings.owner_user_ids
        return platform == "telegram" and chat_type == "dm" and user in owners and chat in owners

    def _context(self) -> policy.Context:
        lim = self.settings.limits
        return policy.Context(
            owners=self.settings.owner_user_ids, limits=lim, tz=self.port.timezone(),
            display_tz=ZoneInfo(self.settings.display_timezone), now=self.port.now(),
            jobs=self.port.jobs(), pending_creates=self._pending_count(),
            parse_schedule=self.port.parse_schedule, resolve_job=self.port.resolve_job)

    def _pending_count(self) -> int:
        """Live create reservations (each owned by one tool call); expired bindings are dropped."""
        now = time.monotonic()
        with self._lock:
            for call_id, binding in list(self._bindings.items()):
                if binding.expiry < now:
                    self._bindings.pop(call_id, None)
            return sum(1 for b in self._bindings.values() if b.reserves_slot)

    def _release(self, call_id: str) -> _Binding | None:
        """Drop the binding (and reservation) of ``call_id`` only."""
        if not call_id:
            return None
        with self._lock:
            return self._bindings.pop(call_id, None)

    # ---- confirmation -----------------------------------------------------------------------------

    def _confirm(self, decision: policy.Decision, call_id: str) -> dict:
        """Post the verbatim proposal (only if no other hook vetoes), then ask Hermes' approval gate.
        The binding of ``call_id`` was stored by the caller; any refusal here drops it."""
        binding = self._bindings.get(call_id)
        try:
            if binding is None or self.port.other_hooks_veto(self, binding.hook_kwargs):
                self._release(call_id)
                return _block(MSG_VETO)
            # One message, checked whole before it is posted; never split (review 4, F9).
            policy.check_post(decision.proposal)
            if not self.port.post(decision.proposal):
                self._release(call_id)
                return _block(MSG_POST)
        except policy.UnsafePost as exc:
            self._release(call_id)
            if exc.size is not None:
                return _block(MSG_LONG_POST.format(size=exc.size, budget=policy.POST_BUDGET))
            return _block(MSG_UNSAFE_POST.format(why=exc))
        except Exception:
            logger.warning("scout_cron confirmation failed; refusing", exc_info=True)
            self._release(call_id)
            return _block(MSG_ERROR)
        # A fresh key per call: a "session" or "always" answer can never pre-approve another call.
        return {"action": "approve", "message": decision.card, "rule_key": f"scout_cron:{secrets.token_hex(8)}"}

    def _bind(self, call_id: str, tool: str, decision: policy.Decision, hook_kwargs: dict) -> None:
        meta = decision.meta
        self._bindings[call_id] = _Binding(
            tool=tool, action=str(meta["dispatch"].get("action") or ""), job_id=meta.get("job_id"),
            fingerprint=meta.get("fingerprint"), dispatch=dict(meta["dispatch"]), expect=meta.get("expect"),
            hook_kwargs=dict(hook_kwargs), reserves_slot=decision.reserves_slot,
            expiry=time.monotonic() + PENDING_TTL_S)

    def _common_gate(self) -> dict | None:
        if not self._usable():
            return _block(MSG_SETTINGS)
        if not self._profile_ok():
            return _block(MSG_PROFILE)
        in_cron, _execution = self._execution()
        if in_cron:
            return _block(MSG_CRON)
        if not self._owner_chat():
            return _block(MSG_CHANNEL)
        try:
            if self.port.approval_bypass_active():
                return _block(MSG_BYPASS)
        except Exception:
            return _block(MSG_ERROR)
        return None

    def _guard_cronjob(self, args: dict, ids: dict) -> dict | None:
        refused = self._common_gate()
        if refused:
            return refused
        if not self.guard_installed:
            return _block(MSG_GUARD)
        call_id = str(ids.get("tool_call_id") or "")
        try:
            with self.port.scope(), self._lock:
                decision = policy.evaluate(args, self._context())
                if decision.kind == "confirm":
                    if not call_id:
                        return _block(MSG_ERROR)
                    self._bind(call_id, CRON_TOOL, decision, {"tool_name": CRON_TOOL, "args": args, **ids})
        except Exception:
            logger.warning("scout_cron policy evaluation failed; refusing", exc_info=True)
            return _block(MSG_ERROR)
        if decision.kind == "refuse":
            return _block(decision.message)
        if decision.kind == "allow":
            return None
        return self._confirm(decision, call_id)

    def _guard_feedback(self, args: dict, ids: dict) -> dict | None:
        refused = self._common_gate()
        if refused:
            return refused
        extra = sorted(k for k, v in args.items() if k not in {"action", "job_id", "text"} and v is not None)
        if extra:
            return _block(f"Champs non permis pour feedback_add : {', '.join(extra)}")
        text = args.get("text")
        limit = self.settings.limits.feedback_chars
        if not isinstance(text, str) or not text.strip() or policy.display_size(text) > limit:
            return _block(f"Le retour doit faire entre 1 et {limit} caractères (affichés dans Telegram).")
        shapes = policy.unsafe_shapes(text)
        if shapes:
            return _block(f"Le retour contient une forme que Telegram n'afficherait pas telle quelle "
                          f"({', '.join(shapes)}) : reformuler sans.")
        call_id = str(ids.get("tool_call_id") or "")
        if not call_id:
            return _block(MSG_ERROR)
        try:
            with self.port.scope(), self._lock:
                job = self.port.resolve_job(str(args.get("job_id") or ""))
                if job is None or not job.get("id"):
                    return _block("Tâche introuvable : lister d'abord.")
                ctx = self._context()
                name, jid = str(job.get("name") or job.get("id")), str(job["id"])
                # The unchanged instructions in full when the post still fits one message, else their size and
                # fingerprint (review 4: one message, never split).
                for full in (True, False):
                    proposal = "\n".join([
                        f"📋 Scout — retour à ajouter au journal d'une tâche (id {jid})",
                        "Il sera lu par chaque exécution suivante. Rien n'est enregistré sans votre approbation.", "",
                        "Tâche concernée :", *policy.verbatim(name), *policy.job_snapshot(job, ctx, instructions=full),
                        "", f"Retour à ajouter ({len(text)} caractères) :", *policy.verbatim(text)])
                    try:
                        policy.check_post(proposal)
                        break
                    except policy.UnsafePost as exc:
                        if exc.size is None:
                            break  # a shape problem: _confirm refuses it with its reason
                decision = policy.Decision(
                    "confirm", proposal=proposal,
                    card=f"Scout — retour pour « {name} » : {len(text)} caractères. "
                         "Texte complet affiché juste au-dessus."[:450],
                    meta={"job_id": jid, "fingerprint": policy.fingerprint(job),
                          "dispatch": {"action": "feedback_add", "job_id": jid, "text": text}})
                self._bind(call_id, TOOL, decision, {"tool_name": TOOL, "args": args, **ids})
        except Exception:
            return _block("Tâche ambiguë ou illisible : lister d'abord.")
        return self._confirm(decision, call_id)

    def _count_run_call(self, tool_name: str, execution: Any) -> dict | None:
        if self.settings is None:
            # The cap cannot be known: an unattended run gets no tool rather than an unbounded one.
            return _block(MSG_SETTINGS)
        lim = self.settings.limits
        key = str(getattr(execution, "execution_id", "") or "")
        if not key:
            return _block(MSG_ERROR)
        with self._lock:
            counts = self._runs.setdefault(key, [0, 0])
            if len(self._runs) > 200:
                for old in list(self._runs)[:100]:
                    self._runs.pop(old, None)
            is_web = tool_name in WEB_TOOLS
            if counts[0] >= lim.run_tool_calls:
                return _block(f"Plafond de {lim.run_tool_calls} appels d'outils atteint pour cette exécution : "
                              "termine avec ce que tu as et signale la limite.")
            if is_web and counts[1] >= lim.run_web_calls:
                return _block(f"Plafond de {lim.run_web_calls} recherches ou lectures Web atteint pour cette "
                              "exécution : termine avec ce que tu as et signale la limite.")
            counts[0] += 1
            if is_web:
                counts[1] += 1
        return None

    # ---- hooks ----------------------------------------------------------------------------------

    def pre_tool_call(self, tool_name: str = "", args: Any = None, **kw: Any) -> dict | None:
        try:
            args = args if isinstance(args, dict) else {}
            ids = {k: v for k, v in kw.items() if k != "tool_name"}
            if tool_name == CRON_TOOL:
                return self._guard_cronjob(args, ids)
            in_cron, execution = self._execution()
            if tool_name == TOOL:
                if not self._usable():
                    return _block(MSG_SETTINGS)
                action = str(args.get("action") or "")
                if in_cron:
                    if action not in CRON_ACTIONS:
                        return _block(MSG_RECORD_CONTEXT)
                    return self._count_run_call(tool_name, execution)
                if action in CHAT_ACTIONS:
                    return self._guard_feedback(args, ids)
                return _block(MSG_RECORD_CONTEXT)
            if in_cron and execution is not None:
                return self._count_run_call(tool_name, execution)
            return None
        except Exception:
            logger.warning("scout_cron pre_tool_call error; refusing", exc_info=True)
            return _block(MSG_ERROR)

    def post_tool_call(self, tool_name: str = "", args: Any = None, result: Any = None, tool_call_id: Any = "",
                       **_: Any) -> None:
        """Terminal outcome of a call (saved, denied, timed out, blocked, failed): only ITS binding goes."""
        if tool_name not in (CRON_TOOL, TOOL):
            return
        self._release(str(tool_call_id or ""))
        if tool_name != CRON_TOOL or not isinstance(args, dict):
            return
        action = str(args.get("action") or "").strip().lower()
        if action == "remove" and self.ledger is not None:
            try:
                data = json.loads(result) if isinstance(result, str) else {}
                job_id = ((data or {}).get("removed_job") or {}).get("id") if data.get("success") else None
                if job_id:
                    self.ledger.delete(str(job_id))
            except (ValueError, AttributeError, LedgerError):
                logger.warning("scout_cron: ledger of a removed job not deleted")
        return

    # ---- cronjob_manage override (runs after the approval, at the real save) -------------------------

    def manage(self, args: Any, **kw: Any) -> str:
        """Scout's cronjob_manage: re-check the approved call, then hand Hermes the canonical arguments."""
        args = args if isinstance(args, dict) else {}
        binding = self._release(self._call_id())
        if not self._usable():
            return _fail(MSG_SETTINGS)
        if not self._profile_ok():
            return _fail(MSG_PROFILE)
        refused = self._common_gate()
        if refused:
            return _fail(refused["message"])
        try:
            builtin = self.port.builtin_cronjob(self)
            with self.port.scope(), self._lock:
                # The call's own reservation is already released: the count below is the atomic check.
                decision = policy.evaluate(args, self._context())
                if decision.kind == "refuse":
                    return _fail(decision.message)
                if decision.kind == "allow":
                    result = builtin(dict(decision.meta["dispatch"]), **kw)
                    if decision.meta["dispatch"].get("action") == "pause":
                        self._notify_pause(decision.meta["job_id"], result)
                    return result
                problem = self._stale(binding, CRON_TOOL, decision.meta)
                if problem:
                    return _fail(problem)
                result = builtin(dict(binding.dispatch), **kw)
                return self._verify_saved(binding, result, builtin, kw)
        except Exception:
            logger.warning("scout_cron manage failed; nothing saved by this plugin", exc_info=True)
            return _fail(MSG_ERROR)

    def _notify_pause(self, job_id: str, result: Any) -> None:
        """Pause needs no approval (it only stops runs); the owner is still told, in the chat (review 2, F7)."""
        try:
            data = json.loads(result) if isinstance(result, str) else {}
            if not (isinstance(data, dict) and data.get("success")):
                return
            job = self.port.get_job(job_id) or {}
            reason = str(job.get("paused_reason") or "")
            text = "\n".join([f"⏸️ Scout a mis en pause une tâche planifiée (id {job_id}) :",
                              *policy.verbatim(str(job.get("name") or job_id))]
                             + (["Motif :", *policy.verbatim(reason)] if reason else [])
                             + ["Reprise : demander à Scout (approbation requise)."])
            try:
                policy.check_post(text)
            except policy.UnsafePost:
                text = (f"⏸️ Scout a mis en pause la tâche id {job_id} (nom et motif non affichables tels quels "
                        "dans un message : /taches-scout).")
            self.port.post(text)
        except Exception:
            logger.warning("scout_cron: pause notice not posted", exc_info=True)

    def _call_id(self) -> str:
        try:
            return self.port.current_tool_call_id()
        except Exception:
            return ""

    def _stale(self, binding: _Binding | None, tool: str, meta: dict) -> str | None:
        """Why the approval no longer covers this mutation (None = it does). Re-checks the other plugins'
        veto (a session tainted while the card was pending) at this boundary."""
        if binding is None or binding.tool != tool or binding.expiry < time.monotonic():
            return MSG_UNAPPROVED
        if (binding.job_id, binding.fingerprint, binding.dispatch) != (
                meta.get("job_id"), meta.get("fingerprint"), meta.get("dispatch")):
            return MSG_STALE
        if self.port.other_hooks_veto(self, binding.hook_kwargs):
            return MSG_VETO
        return None

    def _verify_saved(self, binding: _Binding, result: Any, builtin: Any, kw: dict) -> Any:
        """The stored job must be what the owner approved and conform; otherwise it is paused at once."""
        if binding.expect is None:
            return result
        try:
            data = json.loads(result) if isinstance(result, str) else {}
        except ValueError:
            return result
        if not isinstance(data, dict) or not data.get("success"):
            return result
        job_id = binding.job_id or str(data.get("job_id") or "")
        job = self.port.get_job(job_id) if job_id else None
        problems = ["tâche introuvable après l'enregistrement"] if job is None else policy.conformity_errors(
            job, self.settings.owner_user_ids, self.settings.limits)
        if job is not None:
            seen = {"name": job.get("name"), "prompt": job.get("prompt"),
                    "expr": (job.get("schedule") or {}).get("expr")}
            problems += [f"{k} enregistré différent de la proposition" for k, v in binding.expect.items()
                         if seen.get(k) != v]
        if not problems:
            return result
        logger.warning("scout_cron: saved job %s differs from the approval: %s", job_id, problems)
        if job is not None:
            builtin({"action": "pause", "job_id": job_id, "reason": "scout_cron : différente de l'approbation"}, **kw)
        return _fail("Enregistrement différent de la proposition approuvée (" + "; ".join(problems)
                     + ") : la tâche a été mise en pause, prévenir l'opérateur.")

    def transform_tool_result(self, tool_name: str = "", result: Any = None, **_: Any) -> str | None:
        if tool_name != CRON_TOOL or not isinstance(result, str) or self.settings is None:
            return None
        try:
            data = json.loads(result)
        except ValueError:
            return None
        display = ZoneInfo(self.settings.display_timezone)

        def annotate(node: Any) -> None:
            if isinstance(node, dict):
                value = node.get("next_run_at")
                if isinstance(value, str) and value:
                    try:
                        instant = datetime.fromisoformat(value)
                        if instant.tzinfo is not None:
                            node["next_run_guadeloupe"] = format_fr(instant.astimezone(display))
                            node["next_run_utc"] = format_fr(instant.astimezone(ZoneInfo("UTC")))
                    except ValueError:
                        pass
                for child in node.values():
                    annotate(child)
            elif isinstance(node, list):
                for child in node:
                    annotate(child)

        annotate(data)
        return _json(data)

    # ---- tool -----------------------------------------------------------------------------------

    def tool(self, args: Any, **_: Any) -> str:
        args = args if isinstance(args, dict) else {}
        action = str(args.get("action") or "")
        if not self._usable() or not self._profile_ok():
            return _json({"success": False, "error": MSG_SETTINGS})
        in_cron, execution = self._execution()
        try:
            if in_cron:
                if execution is None or action not in CRON_ACTIONS:
                    return _json({"success": False, "error": MSG_RECORD_CONTEXT})
                return self._cron_action(action, args, str(execution.job_id))
            if action in CHAT_ACTIONS and self._owner_chat():
                return self._feedback(args)
            return _json({"success": False, "error": MSG_RECORD_CONTEXT})
        except LedgerError as exc:
            return _json({"success": False, "error": f"Registre des offres indisponible ({exc}) : "
                                                      "signale-le dans ton compte rendu."})
        except Exception:
            logger.warning("scout_task_record failed", exc_info=True)
            return _json({"success": False, "error": "Journal indisponible : signale-le dans ton compte rendu."})

    def _cron_action(self, action: str, args: dict, job_id: str) -> str:
        lim = self.settings.limits
        today = self.port.now().astimezone(ZoneInfo(self.settings.display_timezone)).date()
        with self.port.scope():
            if action == "journal_get":
                return _json({"success": True, "journal": self.port.note_get(job_id, "journal") or ""})
            if action == "journal_set":
                text = args.get("text")
                if not isinstance(text, str) or len(text) > lim.journal_chars:
                    return _json({"success": False,
                                  "error": f"Journal limité à {lim.journal_chars} caractères : résume-le."})
                self.port.note_set(job_id, "journal", text)
                return _json({"success": True, "chars": len(text)})
            if action == "check_alerted":
                urls = args.get("urls")
                if not isinstance(urls, list) or not urls or len(urls) > MAX_CHECK_URLS:
                    return _json({"success": False, "error": f"urls : 1 à {MAX_CHECK_URLS} URL."})
                return _json({"success": True, **self.ledger.check(job_id, [str(u) for u in urls], today)})
            if action == "mark_alerted":
                items = args.get("items")
                if not isinstance(items, list) or not items or len(items) > MAX_MARK_ITEMS or \
                        not all(isinstance(i, dict) for i in items):
                    return _json({"success": False, "error": f"items : 1 à {MAX_MARK_ITEMS} offres {{url, title}}."})
                return _json({"success": True, **self.ledger.mark(job_id, items, today)})
            return _json({"success": True, "count": self.ledger.count(job_id, today)})

    def _feedback(self, args: dict) -> str:
        """Runs only after the owner approved THIS call (binding); everything is re-checked here."""
        binding = self._release(self._call_id())
        text = args.get("text")
        limit = self.settings.limits.feedback_chars
        if not isinstance(text, str) or not text.strip() or policy.display_size(text) > limit:
            return _fail(f"Retour limité à {limit} caractères (affichés dans Telegram).")
        refused = self._common_gate()
        if refused:
            return _fail(refused["message"])
        today = self.port.now().astimezone(ZoneInfo(self.settings.display_timezone)).date().isoformat()
        with self.port.scope(), self._lock:
            job = self.port.resolve_job(str(args.get("job_id") or ""))
            meta = {"job_id": str(job["id"]) if job and job.get("id") else None,
                    "fingerprint": policy.fingerprint(job) if job else None,
                    "dispatch": {"action": "feedback_add", "job_id": str(job["id"]) if job else None, "text": text}}
            problem = self._stale(binding, TOOL, meta)
            if problem:
                return _fail(problem)
            job_id = str(job["id"])
            line = f"{today} : {' '.join(text.split())}"
            lines = [x for x in (self.port.note_get(job_id, "feedback") or "").split("\n") if x] + [line]
            while lines and len("\n".join(lines)) > limit:
                lines.pop(0)
            self.port.note_set(job_id, "feedback", "\n".join(lines))
        return _json({"success": True, "job_id": job_id, "feedback_entries": len(lines)})

    # ---- command --------------------------------------------------------------------------------

    def command(self, raw_args: str = "", source: Any = None, **_: Any) -> str:
        if not self._usable():
            return MSG_SETTINGS
        platform = str(getattr(getattr(source, "platform", None), "value", getattr(source, "platform", "")) or "")
        owners = self.settings.owner_user_ids
        if not (platform == "telegram" and str(getattr(source, "chat_type", "")) == "dm"
                and str(getattr(source, "user_id", "")) in owners and str(getattr(source, "chat_id", "")) in owners):
            return MSG_CHANNEL
        display = ZoneInfo(self.settings.display_timezone)
        wanted = (raw_args or "").strip()
        try:
            with self.port.scope():
                jobs = self.port.jobs()
                tz, now = self.port.timezone(), self.port.now()
                lines = [f"🗓️ Tâches planifiées de Scout : {len(jobs)} / {self.settings.limits.max_jobs}"]
                bodies: tuple[int, int, str] | None = None  # where the journal/feedback bodies are, and a summary
                for job in jobs:
                    expr = str((job.get("schedule") or {}).get("expr") or job.get("schedule_display") or "?")
                    state = "en pause" if (job.get("state") == "paused" or not job.get("enabled", True)) else "active"
                    try:
                        nxt = next_runs(expr, tz, now, 1)
                        when = (f"{format_fr(nxt[0].astimezone(display))} Guadeloupe" if nxt else "aucun")
                    except ScheduleError:
                        when = f"hors politique ({job.get('next_run_at')})"
                    issues = policy.conformity_errors(job, owners, self.settings.limits)
                    code = policy._code(expr)
                    lines += [f"• id {job.get('id')} — {state} — prochain : {when}", *policy.verbatim(
                        str(job.get("name") or ""))]
                    lines += [f"  Planification : {code}"] if code else ["  Planification :", *policy.verbatim(expr)]
                    if issues:
                        lines += ["  ⚠️ Hors politique :", *policy.verbatim("; ".join(issues))]
                    if wanted and wanted.casefold() in (str(job.get("id")).casefold(),
                                                        str(job.get("name") or "").casefold()):
                        jid = str(job["id"])
                        prompt = str(job.get("prompt") or "")
                        journal = self.port.note_get(jid, "journal") or ""
                        feedback = self.port.note_get(jid, "feedback") or ""
                        lines += [f"  Instructions : {len(prompt)} caractères, empreinte {policy._digest(prompt)}",
                                  f"  Offres déjà signalées : {self.ledger.count(jid, now.astimezone(display).date())}"]
                        start = len(lines)
                        lines += ["  Journal :", *policy.verbatim(journal or "(vide)"),
                                  "  Retours :", *policy.verbatim(feedback or "(aucun)")]
                        bodies = (start, len(lines), f"  Journal : {len(journal)} caractères ; retours : "
                                  f"{len(feedback)} caractères (trop longs pour un seul message, non affichés)")
        except Exception:
            logger.warning("/taches-scout failed", exc_info=True)
            return "Lecture des tâches impossible (journal d'erreurs de la gateway)."
        if not jobs:
            lines.append("Aucune tâche.")
        # One reply, one message, never split: the full view, else without journal and feedback bodies.
        views = [lines] + ([lines[:bodies[0]] + [bodies[2]] + lines[bodies[1]:]] if bodies else [])
        for text in ("\n".join(view) for view in views):
            try:
                policy.check_post(text)
                return text
            except policy.UnsafePost:
                continue
        logger.warning("/taches-scout: list not shown verbatim in one message, refused")
        return "Liste trop longue ou non affichable telle quelle en un message (opérateur : journal de la gateway)."


def register(ctx: Any) -> None:
    """Hermes entry point: three hooks, two tools (one replaces cronjob_manage here only), one command."""
    from hermes_constants import get_hermes_home

    plugin = _Plugin(ctx, Path(get_hermes_home()))
    try:
        schema, check = HermesPort.cronjob_schema()
        handle = ctx.register_tool(name=CRON_TOOL, toolset="cronjob", schema=schema, handler=plugin.manage,
                                   check_fn=check, description=schema.get("description", ""), emoji="⏰",
                                   override=True)
        plugin.guard_installed = handle is not None
    except Exception as exc:  # no tools.override grant: every scheduling change is refused (fail closed)
        logger.warning("scout_cron: cronjob_manage override not installed (%s); scheduling refused", exc)
    if not plugin.guard_installed:
        logger.warning("scout_cron: cronjob_manage override missing; scheduling refused")
    ctx.register_hook("pre_tool_call", plugin.pre_tool_call)
    ctx.register_hook("post_tool_call", plugin.post_tool_call)
    ctx.register_hook("transform_tool_result", plugin.transform_tool_result)
    ctx.register_tool(name=TOOL, toolset=TOOL, schema=TOOL_SCHEMA, handler=plugin.tool,
                      description=TOOL_SCHEMA["description"], emoji="🗒️")
    ctx.register_command("taches-scout", handler=plugin.command,
                         description="Tâches planifiées de Scout, leur journal et leur registre (lecture seule)",
                         args_hint="[nom ou id]")


__all__ = ["TOOL_SCHEMA", "_Plugin", "register"]
