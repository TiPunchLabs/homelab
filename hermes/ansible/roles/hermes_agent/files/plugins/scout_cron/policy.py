"""What Scout may ask of ``cronjob_manage`` (pure: no Hermes import, the store and parser are passed in).

``evaluate`` returns a ``Decision``: ``allow`` (no confirmation: list, pause), ``refuse`` (with a French
reason the model can relay), or ``confirm`` (create, update, remove, resume: a verbatim proposal the
owner must approve). Every refusal is decided on the ARGUMENTS and the stored jobs, never on what the
model says about them.

A decision also carries what is BOUND to the owner's approval (``meta``): the immutable job id, a
fingerprint of the stored job the proposal describes, and the canonical arguments (``dispatch``) that are
the only ones ever handed to Hermes. The plugin re-evaluates at the real mutation and refuses when any of
the three changed (stale approval).

Telegram (review 2, F6): every post goes through Hermes' TelegramAdapter.send, which renders Markdown as
MarkdownV2 (``format_message``), or sends raw Markdown to Telegram's rich renderer when the text contains a
table separator, a task list, ``<details>`` or ``$$``. So text that comes from the model or an operator
(name, instructions, feedback, journal, a stored schedule or delivery) is only ever posted inside a code
fence (``verbatim``), which ``format_message`` never converts; a line that could close the fence or select
the rich path is refused in new text (``unsafe_shapes``) and visibly marked in stored text.
"""

from __future__ import annotations

import hashlib
import json
import re
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

# Fields Scout may set, per action. Any other key must be absent or carry a neutral value.
ALLOWED_FIELDS: dict[str, set[str]] = {
    "list": {"action", "include_disabled"},
    "pause": {"action", "job_id", "reason"},
    "resume": {"action", "job_id"},
    "remove": {"action", "job_id"},
    "create": {"action", "name", "schedule", "prompt", "deliver"},
    "update": {"action", "job_id", "name", "schedule", "prompt", "deliver"},
}
# Values Hermes v0.22.5 treats as "not set" for a key Scout may not set (tools/cronjob_tools.py). None is
# neutral for every key. Everything else is a real value and is refused, empty or false included:
# enabled_toolsets [] = zero-tool override (stored); skills/skill [] and script, workdir, failure_deliver,
# monitor*, context_from '' = clear on update; pinned, no_agent, attach_to_session, continuity False =
# stored; repeat 0 = normalised count; paused_reason needs paused.
_NEUTRAL: dict[str, tuple[Any, ...]] = {
    "paused": (False,),  # _cronjob_handler reads args.get("paused", False); create forwards it only if not False
    "include_disabled": (True, False),  # read by action "list" only
}
# Stored job fields that make a job non-conforming (set by an operator, never by Scout).
_STORED_FORBIDDEN = ("script", "no_agent", "workdir", "monitor_script", "monitor_url", "context_from",
                     "skills", "skill", "attach_to_session", "pinned", "model", "provider", "base_url",
                     "failure_deliver", "interpreter", "reasoning_effort")
_DELIVER_OK = {None, "", "origin"}
# What the approval is bound to. Run bookkeeping (next_run_at, last_*, repeat.completed, an "error"
# state) moves on its own and is left out; everything that decides what a run does is in.
_FINGERPRINT_FIELDS = ("id", "name", "prompt", "deliver", "enabled_toolsets", *_STORED_FORBIDDEN)

MSG_UPDATE_KEEPS = "Instructions enregistrées (inchangées)"
MAX_REASON_CHARS = 200  # pause reason (review 2, F7)

FENCE = "```"
# Line shapes that would close the fence (Hermes: a line starting with ``` toggles its table pass and a
# line of only ``` closes a fence) or select Telegram's rich renderer (TelegramAdapter._needs_rich_rendering).
_UNSAFE_LINES = (
    (re.compile(r"^\s*```"), "ligne commençant par ```"),
    (re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*){1,}\|?\s*$"), "ligne de séparation de tableau"),
    (re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+"), "case à cocher"),
    (re.compile(r"^(?:<details\b|</details>|<summary\b|</summary>)"), "balise <details> ou <summary>"),
)
_MARK = "· "


def _unsafe_line(line: str) -> bool:
    return any(rx.search(line) for rx, _ in _UNSAFE_LINES)


class UnsafePost(ValueError):
    """A Telegram post that Hermes would not show verbatim (review 3, F8): never posted."""


def unsafe_shapes(text: str) -> list[str]:
    """Shapes in ``text`` that Telegram would not show verbatim inside a code fence (empty = safe)."""
    found = [why for line in text.split("\n") for rx, why in _UNSAFE_LINES if rx.search(line)]
    if "$$" in text:
        found.append("« $$ »")
    if "\r" in text:
        found.append("retour chariot")
    return sorted(set(found))


def verbatim(text: str) -> list[str]:
    """``text`` as fenced lines that Telegram shows character for character. A stored line with an unsafe
    shape (never in text Scout saved: refused at creation) is shown with a leading « · », and said so."""
    lines, marked = [FENCE], str(text).count("\r")
    for line in str(text).replace("\r", "␍").split("\n"):
        if "$$" in line:
            line, marked = re.sub(r"\$(?=\$)", "$ ", line), marked + 1
        if _unsafe_line(line):
            line, marked = _MARK + line, marked + 1
        lines.append(line)
    lines.append(FENCE)
    if marked:
        lines.append(f"({marked} marque(s) d'affichage : « · » en tête de ligne, « $ $ », « ␍ » ; texte "
                     "enregistré tel quel, que Telegram aurait interprété)")
    return lines


def _code(text: str) -> str | None:
    """Inline code for a short token known to hold no backtick (cron expressions)."""
    return f"`{text}`" if text and re.fullmatch(r"[0-9A-Za-z*/,\- ]+", text) else None


@dataclass(frozen=True)
class Decision:
    kind: str  # "allow" | "refuse" | "confirm"
    message: str = ""
    proposal: str = ""  # full verbatim text posted before the approval card
    card: str = ""  # short text of the approval card (<= 450 chars)
    reserves_slot: bool = False  # a create that counts against the job cap until it settles
    meta: dict[str, Any] = field(default_factory=dict)  # job_id, fingerprint, dispatch, expect


def refuse(reason: str) -> Decision:
    return Decision("refuse", message=f"Refusé par la politique de planification de Scout : {reason}")


def _present(value: Any) -> bool:
    """A non-empty value (used for STORED fields: an operator job with ``script: ''`` runs no script)."""
    if value is None or value is False:
        return False
    if isinstance(value, (str, list, tuple, dict)) and not value:
        return False
    return True


def _set(key: str, value: Any) -> bool:
    """True when an ARGUMENT carries a real value for Hermes (see ``_NEUTRAL``)."""
    return value is not None and not any(value is n or (type(value) is type(n) and value == n)
                                         for n in _NEUTRAL.get(key, ()))


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _norm_name(name: Any) -> str:
    return " ".join(str(name or "").split()).casefold()


def _expr(job: Mapping[str, Any]) -> str:
    schedule = job.get("schedule") or {}
    return str(schedule.get("expr") or "") if isinstance(schedule, Mapping) else ""


def _paused(job: Mapping[str, Any]) -> bool:
    return job.get("state") == "paused" or not job.get("enabled", True)


def fingerprint(job: Mapping[str, Any]) -> str:
    """Digest of everything in a stored job that decides what its runs do (and whether they happen)."""
    schedule = job.get("schedule") if isinstance(job.get("schedule"), Mapping) else {"raw": job.get("schedule")}
    origin = job.get("origin") if isinstance(job.get("origin"), Mapping) else {}
    payload = {name: job.get(name) for name in _FINGERPRINT_FIELDS}
    payload |= {"schedule": {k: schedule.get(k) for k in ("kind", "expr", "minutes", "run_at", "raw")},
                "origin": {k: origin.get(k) for k in ("platform", "chat_id", "thread_id")},
                "paused": _paused(job), "repeat": (job.get("repeat") or {}).get("times")
                if isinstance(job.get("repeat"), Mapping) else job.get("repeat")}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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


def conformity_issues(job: Mapping[str, Any], owners: frozenset[str],
                      limits: Limits) -> list[tuple[str, str]]:
    """Why a stored job is outside Scout's policy, as (kind, French reason); empty = conforming.
    Kinds: ``field``, ``schedule``, ``deliver``, ``prompt``, ``name``."""
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
    prompt, name = job.get("prompt"), job.get("name")
    if not isinstance(prompt, str) or len(prompt) > limits.max_prompt_chars:
        issues.append(("prompt", f"instructions absentes ou de plus de {limits.max_prompt_chars} caractères"))
    if name is not None and (not isinstance(name, str) or len(name.strip()) > limits.max_name_chars):
        issues.append(("name", f"nom de plus de {limits.max_name_chars} caractères"))
    return issues


def conformity_errors(job: Mapping[str, Any], owners: frozenset[str], limits: Limits) -> list[str]:
    """French reasons only (empty = conforming)."""
    return [reason for _kind, reason in conformity_issues(job, owners, limits)]


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


def schedule_lines(expr: str, ctx: Context) -> list[str]:
    """The expression and its next three runs, Guadeloupe time and UTC."""
    runs = next_runs(expr, ctx.tz, ctx.now, 3)
    lines = [f"Planification : {_code(expr)} (fuseau de Scout : {ctx.tz.key})", "Prochains passages :"]
    utc = ZoneInfo("UTC")
    for run in runs:
        lines.append(f"  - {format_fr(run.astimezone(ctx.display_tz))} heure de Guadeloupe"
                     f" ({format_fr(run.astimezone(utc))} UTC)")
    return lines


def _job_schedule_lines(job: Mapping[str, Any], ctx: Context, paused: bool) -> list[str]:
    """A stored job's schedule; one that is not a daily cron expression is shown as stored."""
    try:
        daily_fields(_expr(job))
        lines = schedule_lines(_expr(job), ctx)
    except ScheduleError:
        return ["Planification actuelle (hors politique) :", *verbatim(str(job.get("schedule_display")
                                                                         or job.get("schedule")))]
    return lines + (["(en pause : aucun passage tant qu'elle n'est pas reprise)"] if paused else [])


def delivery_lines(job: Mapping[str, Any] | None, owners: frozenset[str]) -> list[str]:
    if job is None or deliver_is_owner(job, owners):
        return ["Livraison : cette conversation privée uniquement, par le bot de Scout."]
    return ["Livraison actuelle (hors politique) :",
            *verbatim(f"deliver={job.get('deliver')!r} origin={job.get('origin')!r}")]


def _instructions(prompt: str, label: str) -> list[str]:
    return [f"{label} ({len(prompt)} caractères, empreinte {_digest(prompt)}) :", *verbatim(prompt)]


def _name_lines(name: str, label: str = "Nom de la tâche") -> list[str]:
    return [f"{label} :", *verbatim(name)]


def job_snapshot(job: Mapping[str, Any], ctx: Context) -> list[str]:
    """Everything a run of this stored job does: schedule (Guadeloupe and UTC), delivery, instructions."""
    return (_job_schedule_lines(job, ctx, _paused(job)) + delivery_lines(job, ctx.owners)
            + _instructions(str(job.get("prompt") or ""), "Instructions enregistrées"))


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


def _text_args(args: Mapping[str, Any], ctx: Context, creating: bool
               ) -> tuple[str | None, str | None, Decision | None]:
    """(name, prompt) as they will be saved: None = unchanged (update only; Hermes would CLEAR a stored
    prompt on '', so a blank one is never forwarded)."""
    name, prompt, deliver = args.get("name"), args.get("prompt"), args.get("deliver")
    for key, value in (("name", name), ("prompt", prompt), ("schedule", args.get("schedule"))):
        if value is not None and not isinstance(value, str):
            return None, None, refuse(f"« {key} » doit être un texte")
    name = " ".join(name.split()) if name else None
    prompt = prompt.strip() if prompt else None
    if creating and not name:
        return None, None, refuse("un nom de tâche est obligatoire")
    if name and len(name) > ctx.limits.max_name_chars:
        return None, None, refuse(f"le nom dépasse {ctx.limits.max_name_chars} caractères")
    if creating and not prompt:
        return None, None, refuse("les instructions de la tâche sont obligatoires")
    if prompt and len(prompt) > ctx.limits.max_prompt_chars:
        return None, None, refuse(f"les instructions dépassent {ctx.limits.max_prompt_chars} caractères")
    for label, value in (("le nom", name), ("les instructions", prompt)):
        shapes = unsafe_shapes(value or "")
        if shapes:
            return None, None, refuse(f"{label} contiennent une forme que Telegram n'afficherait pas telle quelle "
                                      f"({', '.join(shapes)}) : reformuler sans")
    if deliver not in _DELIVER_OK:
        return None, None, refuse("la livraison se fait uniquement dans cette conversation privée "
                                  "(ne pas renseigner « deliver »)")
    return name, prompt, None


def _name_taken(name: str, ctx: Context, except_id: str | None = None) -> bool:
    wanted = _norm_name(name)
    return any(_norm_name(j.get("name")) == wanted and str(j.get("id")) != str(except_id) for j in ctx.jobs)


def _header(action_fr: str, name: str) -> list[str]:
    """The name comes from the model or an operator: fenced, never inline."""
    return [f"📋 Scout — proposition de tâche planifiée : {action_fr}",
            "Rien n'est enregistré tant que vous n'avez pas approuvé avec le bouton qui suit.", "",
            *_name_lines(name)]


def _card(action_fr: str, name: str, detail: str) -> str:
    text = f"Scout — {action_fr} « {name} » : {detail}. Texte complet affiché juste au-dessus."
    return text[:450]


def _bound(job: Mapping[str, Any], dispatch: dict[str, Any], expect: dict[str, Any] | None = None) -> dict:
    return {"job_id": str(job["id"]), "fingerprint": fingerprint(job), "dispatch": dispatch, "expect": expect}


def evaluate(args: Mapping[str, Any], ctx: Context) -> Decision:
    """Decide a cronjob_manage call made from an owner's Telegram turn."""
    action = str(args.get("action") or "").strip().lower()
    if action in BLOCKED_ACTIONS:
        return refuse("l'exécution immédiate d'une tâche n'est pas permise à Scout")
    if action not in FREE_ACTIONS | CONFIRMED_ACTIONS:
        return refuse(f"action « {action or '?'} » non permise")
    extra = sorted(k for k, v in args.items() if k not in ALLOWED_FIELDS[action] and _set(k, v))
    if extra:
        return refuse(f"champs non permis pour « {action} » (les omettre, même vides) : {', '.join(extra)}")
    if action == "list":
        include = args.get("include_disabled")
        return Decision("allow", meta={"dispatch": {"action": "list", "include_disabled": include is not False}})

    job = None
    if action != "create":
        ref = args.get("job_id")
        if not isinstance(ref, str) or not ref.strip():
            return refuse("identifiant de tâche obligatoire (lister d'abord)")
        try:
            job = ctx.resolve_job(ref)
        except Exception as exc:
            return refuse(f"tâche ambiguë ou illisible ({str(exc)[:120]})")
        if job is None or not job.get("id"):
            return refuse("tâche introuvable (lister d'abord)")
        name = str(job.get("name") or job.get("id"))
        jid = str(job["id"])
    if action == "pause":
        reason = args.get("reason")
        if reason is not None and (not isinstance(reason, str) or len(reason) > MAX_REASON_CHARS):
            return refuse(f"motif de pause : un texte de {MAX_REASON_CHARS} caractères au plus")
        dispatch = {"action": "pause", "job_id": jid} | ({"reason": reason} if reason else {})
        return Decision("allow", meta=_bound(job, dispatch))

    if action == "remove":
        lines = _header("supprimer", name) + [f"Identifiant : {jid}"] + job_snapshot(job, ctx) + [
            "La tâche, son journal et sa liste d'offres déjà signalées seront supprimés."]
        return Decision("confirm", proposal="\n".join(lines), card=_card("supprimer", name, f"id {jid}"),
                        meta=_bound(job, {"action": "remove", "job_id": jid}))

    if action == "resume":
        errors = conformity_errors(job, ctx.owners, ctx.limits)
        if errors:
            return refuse("cette tâche ne respecte pas la politique de Scout (" + "; ".join(errors)
                          + ") : seul l'opérateur peut la reprendre")
        if len(ctx.jobs) + ctx.pending_creates > ctx.limits.max_jobs:
            return refuse(f"Scout a {len(ctx.jobs)} tâche(s), plafond {ctx.limits.max_jobs} : en supprimer "
                          "avant d'en reprendre une")
        prompt = str(job.get("prompt") or "")
        lines = _header("reprendre", name) + [f"Identifiant : {jid}"] + schedule_lines(_expr(job), ctx) + \
            delivery_lines(job, ctx.owners) + _instructions(prompt, MSG_UPDATE_KEEPS)
        return Decision("confirm", proposal="\n".join(lines),
                        card=_card("reprendre", name, f"{_expr(job)}, empreinte {_digest(prompt)}"),
                        meta=_bound(job, {"action": "resume", "job_id": jid},
                                    {"name": job.get("name"), "prompt": prompt, "expr": _expr(job)}))

    creating = action == "create"
    new_name, new_prompt, problem = _text_args(args, ctx, creating)
    if problem:
        return problem
    if creating:
        if len(ctx.jobs) + ctx.pending_creates >= ctx.limits.max_jobs:
            return refuse(f"Scout a déjà {len(ctx.jobs)} tâche(s) (pauses comprises), "
                          f"plafond {ctx.limits.max_jobs} : mettre à jour ou supprimer une tâche existante")
        if _name_taken(new_name, ctx):
            return refuse("une tâche porte déjà ce nom : la mettre à jour au lieu d'en créer une autre")
        expr, problem = _check_schedule(args.get("schedule"), ctx)
        if problem:
            return problem
        lines = _header("créer", new_name) + schedule_lines(expr, ctx) + delivery_lines(None, ctx.owners) + \
            _instructions(new_prompt, "Instructions enregistrées")
        dispatch = {"action": "create", "name": new_name, "schedule": expr, "prompt": new_prompt}
        return Decision("confirm", proposal="\n".join(lines), reserves_slot=True,
                        card=_card("créer", new_name, f"{expr}, {len(new_prompt)} caractères, "
                                                     f"empreinte {_digest(new_prompt)}"),
                        meta={"job_id": None, "fingerprint": None, "dispatch": dispatch,
                              "expect": {"name": new_name, "prompt": new_prompt, "expr": expr}})

    # update
    replaced = {"schedule"} if args.get("schedule") else set()
    replaced |= {"prompt"} if new_prompt else set()
    replaced |= {"name"} if new_name else set()
    # A replaced field may fix its own issue (operator schedule, oversize text); any other issue stays the
    # operator's.
    errors = [reason for kind, reason in conformity_issues(job, ctx.owners, ctx.limits) if kind not in replaced]
    if errors:
        return refuse("cette tâche ne respecte pas la politique de Scout (" + "; ".join(errors)
                      + ") : seul l'opérateur peut la modifier")
    old_prompt, old_expr = str(job.get("prompt") or ""), _expr(job)
    dispatch: dict[str, Any] = {"action": "update", "job_id": jid}
    changed: list[str] = []
    before_after: list[str] = []
    if new_name and new_name != name:
        if _name_taken(new_name, ctx, except_id=jid):
            return refuse("une autre tâche porte déjà ce nom")
        dispatch["name"] = new_name
        changed.append("nom")
        before_after += _name_lines(name, "Nom actuel") + _name_lines(new_name, "Nouveau nom")
    expr = old_expr
    if args.get("schedule"):
        new_expr, problem = _check_schedule(args.get("schedule"), ctx)
        if problem:
            return problem
        if new_expr != old_expr:
            dispatch["schedule"] = new_expr
            changed.append("planification")
            old = _code(old_expr)
            before_after += ([f"Planification : {old} → {_code(new_expr)}"] if old else
                             ["Planification actuelle :", *verbatim(str(job.get("schedule_display") or "?")),
                              f"Nouvelle planification : {_code(new_expr)}"])
            expr = new_expr
    prompt = old_prompt
    if new_prompt and new_prompt != old_prompt:
        dispatch["prompt"] = new_prompt
        changed.append("instructions")
        before_after.append(f"Instructions : {len(old_prompt)} → {len(new_prompt)} caractères, "
                            f"empreinte {_digest(old_prompt)} → {_digest(new_prompt)}")
        prompt = new_prompt
    if not changed:
        return refuse("aucune modification demandée (les valeurs données sont déjà celles de la tâche)")
    unchanged = [f for f in ("nom", "planification", "instructions", "livraison") if f not in changed]
    final_name = dispatch.get("name", name)
    lines = _header("mettre à jour", name) + [
        f"Identifiant : {jid}", f"Champs modifiés : {', '.join(changed)}",
        f"Champs inchangés : {', '.join(unchanged)}", *before_after, "",
        "Tâche après la mise à jour :" + (" (reste en pause)" if _paused(job) else ""),
        *_name_lines(final_name)] + schedule_lines(expr, ctx) + delivery_lines(job, ctx.owners) + _instructions(
            prompt, "Nouvelles instructions complètes" if "instructions" in changed else MSG_UPDATE_KEEPS)
    return Decision("confirm", proposal="\n".join(lines), card=_card("mettre à jour", name, ", ".join(changed)),
                    meta=_bound(job, dispatch, {"name": final_name, "prompt": prompt, "expr": expr}))


def _cost(line: str, fenced: bool) -> int:
    """Upper bound of the line's length once Hermes renders it as MarkdownV2, in UTF-16 units (Telegram's
    measure), newline included: inside a fence only \\ and ` are escaped; outside, any character may be."""
    units = len(line.encode("utf-16-le")) // 2
    return (units + line.count("\\") + line.count("`") if fenced else 2 * units) + 1


def split_for_telegram(text: str, limit: int = 3500) -> list[str]:
    """Split a post at line boundaries into chunks whose RENDERED size stays under ``limit`` (Telegram: 4096),
    never leaving a fence open: a chunk that ends inside a fence closes it, the next one reopens it. A line
    too long for one chunk is cut (inside a fence it continues on the next message), never where a piece
    would become a fence line or another unsafe shape (review 3, F8: « aaa```» cut before the ``` closed
    the reopened fence). Every line of every chunk is checked; raises UnsafePost rather than return a
    chunk Hermes would not show verbatim."""
    budget = limit - 2 * _cost(FENCE, False) - 20  # closing fence and the « (i/n) » line
    chunks: list[str] = []
    cur: list[str] = []
    used, fenced = 0, False

    def close() -> None:
        nonlocal cur, used
        chunks.append("\n".join(cur + ([FENCE] if fenced else [])))
        cur, used = ([FENCE], _cost(FENCE, False)) if fenced else ([], 0)

    for line in text.split("\n"):
        marker = line == FENCE
        while True:
            cost = _cost(line, fenced and not marker)
            if used + cost <= budget or (marker and fenced):
                cur.append(line)
                used += cost
                break
            if cur and cur != [FENCE]:
                close()
                continue
            keep = 1
            while keep < len(line) and used + _cost(line[:keep + 1], fenced) <= budget:
                keep += 1
            while keep > 1 and (_unsafe_line(line[:keep]) or _unsafe_line(line[keep:])):
                keep -= 1
            cur.append(line[:keep])
            used += _cost(line[:keep], fenced)
            line = line[keep:]
            close()
        if marker:
            fenced = not fenced
    if cur and cur != [FENCE]:
        close()
    if len(chunks) > 1:
        chunks = [f"({i}/{len(chunks)})\n{c}" for i, c in enumerate(chunks, start=1)]
    for chunk in chunks:
        check_post(chunk)
    return chunks


def check_post(chunk: str) -> None:
    """Raise UnsafePost unless Hermes would show ``chunk`` as intended: fences are only the plugin's own
    ``` lines and balanced, no other line could close/open a fence, toggle the table pass or select the
    rich renderer (table, task list, <details>), no « $$ » or CR, rendered size under Telegram's 4096.
    Lines are also checked as Hermes' table detector cuts them (str.splitlines: U+2028, form feed...)."""
    fences, rendered = 0, 0
    for line in chunk.split("\n"):
        if line == FENCE:
            fences += 1
        elif any(_unsafe_line(part) for part in [line, *line.splitlines()]):
            raise UnsafePost("unsafe line shape")
        rendered += _cost(line, fences % 2 == 1)
    if fences % 2 or "$$" in chunk or "\r" in chunk or rendered > 4096:
        raise UnsafePost("unbalanced fence, $$, CR or oversize")
