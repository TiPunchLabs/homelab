"""What Scout may ask of ``cronjob_manage`` (pure: no Hermes import, the store and parser are passed in).

``evaluate`` returns a ``Decision``: ``allow`` (no confirmation: list, pause), ``refuse`` (with a French
reason the model can relay), or ``confirm`` (create, update, remove, resume: a verbatim proposal the
owner must approve). Every refusal is decided on the ARGUMENTS and the stored jobs, never on what the
model says about them.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .config import Limits
from .schedule import ScheduleError, daily_fields, format_fr, next_runs

FREE_ACTIONS = {"list", "pause"}
CONFIRMED_ACTIONS = {"create", "update", "remove", "resume"}
BLOCKED_ACTIONS = {"run", "run_now", "trigger"}

# Fields Scout may set, per action. Anything else carrying a value is refused.
ALLOWED_FIELDS: dict[str, set[str]] = {
    "list": {"action", "include_disabled"},
    "pause": {"action", "job_id", "reason"},
    "resume": {"action", "job_id"},
    "remove": {"action", "job_id"},
    "create": {"action", "name", "schedule", "prompt", "deliver"},
    "update": {"action", "job_id", "name", "schedule", "prompt", "deliver"},
}
# Stored job fields that make a job non-conforming (set by an operator, never by Scout).
_STORED_FORBIDDEN = ("script", "no_agent", "workdir", "monitor_script", "monitor_url", "context_from",
                     "skills", "skill", "attach_to_session", "pinned", "model", "provider", "base_url",
                     "failure_deliver", "interpreter", "reasoning_effort")
_DELIVER_OK = {None, "", "origin"}


@dataclass(frozen=True)
class Decision:
    kind: str  # "allow" | "refuse" | "confirm"
    message: str = ""
    proposal: str = ""  # full verbatim text posted before the approval card
    card: str = ""  # short text of the approval card (<= 450 chars)
    reserves_slot: bool = False  # a create that counts against the job cap until it settles
    meta: dict[str, Any] = field(default_factory=dict)


def refuse(reason: str) -> Decision:
    return Decision("refuse", message=f"Refusé par la politique de planification de Scout : {reason}")


def _present(value: Any) -> bool:
    """A value the model actually set (schema defaults such as None, '', False, [] are absent)."""
    if value is None or value is False:
        return False
    if isinstance(value, (str, list, tuple, dict)) and not value:
        return False
    return True


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _norm_name(name: Any) -> str:
    return " ".join(str(name or "").split()).casefold()


def deliver_is_owner(job: Mapping[str, Any], owners: frozenset[str]) -> bool:
    """True when a stored job delivers to the owner's private chat only."""
    deliver = job.get("deliver")
    origin = job.get("origin") or {}
    if deliver in (None, "", "origin"):
        return (str(origin.get("platform") or "") == "telegram"
                and str(origin.get("chat_id") or "") in owners)
    if isinstance(deliver, str) and deliver.startswith("telegram:"):
        parts = deliver.split(":")
        return len(parts) == 2 and parts[1] in owners
    return False


def conformity_issues(job: Mapping[str, Any], owners: frozenset[str]) -> list[tuple[str, str]]:
    """Why a stored job is outside Scout's policy, as (kind, French reason); empty = conforming.
    Kinds: ``field``, ``schedule``, ``deliver``."""
    issues = [("field", f"champ « {name} » défini") for name in _STORED_FORBIDDEN if _present(job.get(name))]
    if job.get("enabled_toolsets") is not None:
        issues.append(("field", "champ « enabled_toolsets » défini"))
    schedule = job.get("schedule") or {}
    if not isinstance(schedule, Mapping) or schedule.get("kind") != "cron":
        issues.append(("schedule", "planification non quotidienne (ni expression cron)"))
    else:
        try:
            daily_fields(str(schedule.get("expr") or ""))
        except ScheduleError as exc:
            issues.append(("schedule", f"planification : {exc}"))
    if not deliver_is_owner(job, owners):
        issues.append(("deliver", "livraison ailleurs que la conversation privée du propriétaire"))
    return issues


def conformity_errors(job: Mapping[str, Any], owners: frozenset[str]) -> list[str]:
    """French reasons only (empty = conforming)."""
    return [reason for _kind, reason in conformity_issues(job, owners)]


@dataclass(frozen=True)
class Context:
    owners: frozenset[str]
    limits: Limits
    tz: ZoneInfo  # the profile's scheduling timezone (Hermes parses cron expressions in it)
    display_tz: ZoneInfo
    now: datetime
    jobs: Sequence[Mapping[str, Any]]
    pending_creates: int
    parse_schedule: Callable[[str], Mapping[str, Any]]
    resolve_job: Callable[[str], Mapping[str, Any] | None]


def _schedule_lines(expr: str, ctx: Context) -> list[str]:
    runs = next_runs(expr, ctx.tz, ctx.now, 3)
    lines = [f"Expression : {expr} (fuseau de Scout : {ctx.tz.key})", "Prochains passages :"]
    utc = ZoneInfo("UTC")
    for run in runs:
        lines.append(f"  - {format_fr(run.astimezone(ctx.display_tz))} heure de Guadeloupe"
                     f" ({format_fr(run.astimezone(utc))} UTC)")
    return lines


def _check_schedule(text: Any, ctx: Context) -> tuple[str | None, Decision | None]:
    if not isinstance(text, str) or not text.strip():
        return None, refuse("la planification est obligatoire")
    try:
        parsed = ctx.parse_schedule(text)
    except Exception as exc:
        return None, refuse(f"planification illisible ({str(exc).splitlines()[0][:160]})")
    if not isinstance(parsed, Mapping) or parsed.get("kind") != "cron":
        return None, refuse("seules les tâches récurrentes à heure fixe sont permises "
                            "(ni intervalle, ni exécution unique)")
    expr = str(parsed.get("expr") or "")
    try:
        daily_fields(expr)
        if not next_runs(expr, ctx.tz, ctx.now, 1):
            return None, refuse("cette planification ne se déclenche jamais")
    except ScheduleError as exc:
        return None, refuse(str(exc))
    return expr, None


def _check_text_fields(args: Mapping[str, Any], ctx: Context, creating: bool) -> Decision | None:
    name, prompt = args.get("name"), args.get("prompt")
    if creating and not _present(name):
        return refuse("un nom de tâche est obligatoire")
    if _present(name):
        if not isinstance(name, str) or len(name.strip()) > ctx.limits.max_name_chars:
            return refuse(f"le nom dépasse {ctx.limits.max_name_chars} caractères")
    if creating and not _present(prompt):
        return refuse("les instructions de la tâche sont obligatoires")
    if _present(prompt):
        if not isinstance(prompt, str) or len(prompt) > ctx.limits.max_prompt_chars:
            return refuse(f"les instructions dépassent {ctx.limits.max_prompt_chars} caractères")
    deliver = args.get("deliver")
    if deliver not in _DELIVER_OK:
        return refuse("la livraison se fait uniquement dans cette conversation privée "
                      "(ne pas renseigner « deliver »)")
    return None


def _name_taken(name: str, ctx: Context, except_id: str | None = None) -> bool:
    wanted = _norm_name(name)
    return any(_norm_name(j.get("name")) == wanted and str(j.get("id")) != str(except_id) for j in ctx.jobs)


def _header(action_fr: str, name: str) -> list[str]:
    return [f"📋 Scout — proposition de tâche planifiée : {action_fr} « {name} »",
            "Rien n'est enregistré tant que vous n'avez pas approuvé avec le bouton qui suit.", ""]


def _delivery_line() -> str:
    return "Livraison : cette conversation privée, par le bot de Scout."


def _card(action_fr: str, name: str, detail: str) -> str:
    text = f"Scout — {action_fr} « {name} » : {detail}. Texte complet affiché juste au-dessus."
    return text[:450]


def evaluate(args: Mapping[str, Any], ctx: Context) -> Decision:
    """Decide a cronjob_manage call made from an owner's Telegram turn."""
    action = str(args.get("action") or "").strip().lower()
    if action in BLOCKED_ACTIONS:
        return refuse("l'exécution immédiate d'une tâche n'est pas permise à Scout")
    if action not in FREE_ACTIONS | CONFIRMED_ACTIONS:
        return refuse(f"action « {action or '?'} » non permise")
    extra = sorted(k for k, v in args.items() if k not in ALLOWED_FIELDS[action] and _present(v))
    if extra:
        return refuse(f"champs non permis pour « {action} » : {', '.join(extra)}")
    if action == "list":
        return Decision("allow")

    job = None
    if action != "create":
        ref = args.get("job_id")
        if not isinstance(ref, str) or not ref.strip():
            return refuse("identifiant de tâche obligatoire (lister d'abord)")
        try:
            job = ctx.resolve_job(ref)
        except Exception as exc:
            return refuse(f"tâche ambiguë ou illisible ({str(exc)[:120]})")
        if job is None:
            return refuse("tâche introuvable (lister d'abord)")
    if action == "pause":
        return Decision("allow")

    if action == "remove":
        name = str(job.get("name") or job.get("id"))
        lines = _header("supprimer", name) + [
            f"Identifiant : {job.get('id')}",
            f"Planification actuelle : {job.get('schedule_display') or (job.get('schedule') or {}).get('expr')}",
            "La tâche, son journal et sa liste d'offres déjà signalées seront supprimés."]
        return Decision("confirm", proposal="\n".join(lines),
                        card=_card("supprimer", name, f"id {job.get('id')}"),
                        meta={"action": action, "job_id": job.get("id")})

    if action == "resume":
        errors = conformity_errors(job, ctx.owners)
        if errors:
            return refuse("cette tâche ne respecte pas la politique de Scout (" + "; ".join(errors)
                          + ") : seul l'opérateur peut la reprendre")
        name = str(job.get("name") or job.get("id"))
        expr = str((job.get("schedule") or {}).get("expr"))
        lines = _header("reprendre", name) + [f"Identifiant : {job.get('id')}"] + _schedule_lines(expr, ctx) + [
            _delivery_line(), (f"Instructions enregistrées : {len(job.get('prompt') or '')} caractères, "
                               f"empreinte {_digest(str(job.get('prompt') or ''))} (inchangées).")]
        return Decision("confirm", proposal="\n".join(lines),
                        card=_card("reprendre", name, f"{expr}, empreinte {_digest(str(job.get('prompt') or ''))}"),
                        meta={"action": action, "job_id": job.get("id")})

    creating = action == "create"
    problem = _check_text_fields(args, ctx, creating)
    if problem:
        return problem
    if creating:
        if len(ctx.jobs) + ctx.pending_creates >= ctx.limits.max_jobs:
            return refuse(f"Scout a déjà {len(ctx.jobs)} tâche(s) (pauses comprises), "
                          f"plafond {ctx.limits.max_jobs} : mettre à jour ou supprimer une tâche existante")
        if _name_taken(args["name"], ctx):
            return refuse("une tâche porte déjà ce nom : la mettre à jour au lieu d'en créer une autre")
        expr, problem = _check_schedule(args.get("schedule"), ctx)
        if problem:
            return problem
        name, prompt = " ".join(args["name"].split()), args["prompt"]
        lines = _header("créer", name) + _schedule_lines(expr, ctx) + [
            _delivery_line(), f"Instructions enregistrées ({len(prompt)} caractères, empreinte {_digest(prompt)}) :",
            "-----", prompt, "-----"]
        return Decision("confirm", proposal="\n".join(lines), reserves_slot=True,
                        card=_card("créer", name, f"{expr}, {len(prompt)} caractères, empreinte {_digest(prompt)}"),
                        meta={"action": action, "name": name})

    # update
    # A new schedule replaces a non-conforming one; every other issue stays the operator's.
    errors = [reason for kind, reason in conformity_issues(job, ctx.owners)
              if not (kind == "schedule" and _present(args.get("schedule")))]
    if errors:
        return refuse("cette tâche ne respecte pas la politique de Scout (" + "; ".join(errors)
                      + ") : seul l'opérateur peut la modifier")
    changes: list[str] = []
    name = str(job.get("name") or job.get("id"))
    detail: list[str] = []
    if _present(args.get("name")) and " ".join(args["name"].split()) != name:
        new_name = " ".join(args["name"].split())
        if _name_taken(new_name, ctx, except_id=job.get("id")):
            return refuse("une autre tâche porte déjà ce nom")
        changes += [f"Nom : « {name} » → « {new_name} »"]
        detail.append("nom")
    expr = str((job.get("schedule") or {}).get("expr") or "")
    if _present(args.get("schedule")):
        new_expr, problem = _check_schedule(args.get("schedule"), ctx)
        if problem:
            return problem
        changes += [f"Planification : {job.get('schedule_display') or expr} → {new_expr}"]
        expr = new_expr
        detail.append(new_expr)
    if _present(args.get("prompt")):
        old, new = str(job.get("prompt") or ""), args["prompt"]
        changes += [f"Instructions : {len(old)} → {len(new)} caractères, empreinte {_digest(old)} → {_digest(new)}.",
                    "Nouvelles instructions complètes :", "-----", new, "-----"]
        detail.append(f"instructions {_digest(new)}")
    if not changes:
        return refuse("aucune modification demandée")
    lines = _header("mettre à jour", name) + [f"Identifiant : {job.get('id')}"] + changes + [""] + \
        _schedule_lines(expr, ctx) + [_delivery_line()]
    return Decision("confirm", proposal="\n".join(lines),
                    card=_card("mettre à jour", name, ", ".join(detail)),
                    meta={"action": action, "job_id": job.get("id")})


def split_for_telegram(text: str, limit: int = 3500) -> list[str]:
    """Split a proposal at line boundaries into chunks of at most ``limit`` characters."""
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    if len(chunks) > 1:
        chunks = [f"({i}/{len(chunks)}) {c}" for i, c in enumerate(chunks, start=1)]
    return chunks
