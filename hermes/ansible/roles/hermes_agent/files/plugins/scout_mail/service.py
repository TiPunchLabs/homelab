"""The ``/courriels`` request, end to end, without any Hermes dependency (testable offline).

Flow: authorize the caller in trusted code -> list one bounded page of the configured inbox ->
get each listed message (ids from that list only, ownership re-checked) -> clean and bound ->
one tool-less model call (optional) -> trusted rendering. No step mutates the mailbox, writes
memory or history, or reaches anything but the two allowlisted endpoints.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from collections.abc import Callable

from .config import Settings
from .render import MARKER, Builder, Rendered, plain
from .sanitize import clean_text, html_to_text
from .summarize import MailItem, ModelSummary, build_messages, parse_output
from .transport import Budget, HttpBackend, MailError, Transport

logger = logging.getLogger("scout_mail")

MESSAGES_FR = {
    "disabled": "La lecture des courriels est désactivée.",
    "forbidden": "Cette commande n'est disponible que dans la conversation privée de Scout avec son propriétaire.",
    "config": "La lecture des courriels n'est pas configurée correctement ; aucune requête n'a été faite.",
    "auth": ("Accès à la boîte refusé (clé absente, révoquée ou sans droit de lecture). "
             "Aucune autre méthode n'a été tentée."),
    "rate_limited": "Le service de courriel limite les requêtes pour le moment. Réessayez dans quelques minutes.",
    "unavailable": "Le service de courriel ne répond pas correctement pour le moment. Réessayez plus tard.",
    "too_large": "Une réponse du service de courriel dépasse la taille autorisée ; lecture interrompue.",
    "malformed": "Le service de courriel a renvoyé une réponse inattendue ; lecture interrompue.",
    "policy": "Requête refusée par la politique de lecture des courriels.",
    "budget": "Limite de temps ou de requêtes atteinte ; lecture interrompue.",
    "empty": "Aucun courriel dans la boîte.",
    "no_more": "Aucune page suivante : redemandez /courriels pour repartir des plus récents.",
    "reply_blocked": ("Ce message répond à un résumé de courriels. Par sécurité, il n'est pas transmis à Scout : "
                      "le contenu des courriels ne doit pas servir d'instruction. Reformulez votre demande "
                      "dans un nouveau message, sans répondre au résumé."),
    "delivery": "Le résumé n'a pas pu être livré de façon sûre ; rien n'a été envoyé.",
    "internal": "Erreur interne de la lecture des courriels ; aucune action n'a été faite.",
    "help": ("Commandes : /courriels (résumé des plus récents), /courriels liste (sans résumé IA), "
             "/courriels suite (page suivante), /courriels aide."),
}

_AUTH_FR = {"pass": "authentifié", "fail": "échec d'authentification", "none": "non authentifié"}


@dataclass
class Caller:
    """Trusted request context from the gateway (never from mail or model)."""

    profile: str
    platform: str
    chat_type: str
    chat_id: str
    user_id: str


@dataclass
class Outcome:
    rendered: Rendered
    mail_derived: bool
    stats: dict[str, Any] = field(default_factory=dict)


def parse_args(raw: str) -> str | None:
    """Map the owner's argument to a fixed action; anything else is help (ids are never accepted)."""
    arg = (raw or "").strip().lower()
    return {"": "summary", "resume": "summary", "résumé": "summary", "liste": "list",
            "suite": "next", "aide": "help", "help": "help", "refus-reponse": "reply_blocked"}.get(arg, "help")


def _plain(code: str) -> Outcome:
    return Outcome(plain(MESSAGES_FR[code]), mail_derived=False, stats={"result": code})


def _auth_summary(raw: Any) -> str:
    if not isinstance(raw, dict):
        return "inconnue"
    parts = []
    for key in ("spf", "dkim", "dmarc"):
        value = raw.get(key)
        if isinstance(value, str) and value in ("pass", "fail", "none", "softfail", "neutral"):
            parts.append(f"{key.upper()} {value}")
    return ", ".join(parts) or "inconnue"


class PageCursor:
    """Read progress kept outside the mailbox: next page token per chat, short TTL, in memory."""

    def __init__(self, ttl_s: float = 3_600, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_s
        self._clock = clock
        self._lock = threading.Lock()
        self._tokens: dict[str, tuple[float, str]] = {}

    def put(self, chat_id: str, token: str | None) -> None:
        with self._lock:
            if token:
                self._tokens[chat_id] = (self._clock(), token)
            else:
                self._tokens.pop(chat_id, None)

    def get(self, chat_id: str) -> str | None:
        with self._lock:
            entry = self._tokens.get(chat_id)
            if entry is None or self._clock() - entry[0] > self._ttl:
                self._tokens.pop(chat_id, None)
                return None
            return entry[1]


class MailService:
    """Stateless per request apart from the page cursor; safe to call concurrently."""

    def __init__(self, settings: Settings, backend: HttpBackend, secrets: Callable[[str], str | None],
                 cursor: PageCursor | None = None, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.settings = settings
        self._backend = backend
        self._secrets = secrets
        self.cursor = cursor or PageCursor()
        self._clock = clock
        self._sleep = sleep

    def authorize(self, caller: Caller) -> str | None:
        """Return an error code when the caller may not use the command, else None."""
        s = self.settings
        if not s.enabled:
            return "disabled"
        if (caller.profile != s.profile or caller.platform != "telegram" or caller.chat_type != "dm"
                or caller.user_id not in s.owner_user_ids or caller.chat_id != caller.user_id):
            return "forbidden"
        return None

    def run(self, raw_args: str, caller: Caller) -> Outcome:
        """Execute one command; never raises (errors become fixed French messages)."""
        action = parse_args(raw_args)
        denied = self.authorize(caller)
        if denied:
            return _plain(denied)
        if action == "help":
            return _plain("help")
        if action == "reply_blocked":
            return _plain("reply_blocked")
        page_token = None
        if action == "next":
            page_token = self.cursor.get(caller.chat_id)
            if page_token is None:
                return _plain("no_more")
        lim = self.settings.limits
        budget = Budget(deadline=self._clock() + lim.wall_clock_s,
                        http_calls_max=lim.max_pages * (1 + lim.http_retries)
                        + lim.messages_per_request * (1 + lim.http_retries),
                        model_calls_max=lim.model_calls_per_request if action != "list" else 0,
                        clock=self._clock)
        transport = Transport(self.settings, self._backend, self._secrets, budget, sleep=self._sleep)
        started = self._clock()
        try:
            outcome = self._run(action, caller, transport, budget, page_token)
        except MailError as exc:
            outcome = _plain(exc.code)
        except Exception:  # never surface tracebacks (they may embed data) to the chat
            logger.warning("scout_mail internal error", exc_info=False)
            outcome = _plain("internal")
        outcome.stats.update({"http_calls": budget.http_calls, "model_calls": budget.model_calls,
                              "retries": budget.retries, "elapsed_ms": int((self._clock() - started) * 1000),
                              "events": budget.events})
        logger.info("scout_mail request action=%s result=%s http=%d model=%d retries=%d ms=%d",
                    action, outcome.stats.get("result"), budget.http_calls, budget.model_calls,
                    budget.retries, outcome.stats["elapsed_ms"])
        return outcome

    def _run(self, action: str, caller: Caller, transport: Transport, budget: Budget,
             page_token: str | None) -> Outcome:
        lim = self.settings.limits
        listing = transport.list_messages(lim.messages_per_request, page_token)
        raw_items = listing.get("messages")
        if not isinstance(raw_items, list):
            return _plain("malformed")
        next_token = listing.get("next_page_token")
        next_token = next_token if isinstance(next_token, str) and next_token else None
        ids: list[str] = []
        foreign = 0
        for item in raw_items[: lim.messages_per_request]:
            if not isinstance(item, dict) or item.get("inbox_id") != self.settings.inbox_id:
                foreign += 1
                continue
            mid = item.get("message_id")
            if isinstance(mid, str) and mid not in ids:
                ids.append(mid)
        if not ids:
            self.cursor.put(caller.chat_id, None)
            out = _plain("empty")
            out.stats["foreign_dropped"] = foreign
            return out
        items: list[MailItem] = []
        partial_reason: str | None = None
        for index, mid in enumerate(ids, start=1):
            try:
                msg = transport.get_message(mid)
            except MailError as exc:
                if exc.code in ("auth", "policy"):
                    raise
                partial_reason = exc.code
                break
            if msg.get("inbox_id") != self.settings.inbox_id or msg.get("message_id") != mid:
                foreign += 1
                continue
            items.append(self._prepare(f"M{index}", mid, msg))
        self.cursor.put(caller.chat_id, next_token)
        summary: ModelSummary | None = None
        model_status = "skipped"
        context_chars = 0
        if action != "list" and items:
            messages, context_chars = build_messages(items, lim.model_context_max_chars)
            try:
                summary = parse_output(transport.complete(messages), {i.ref for i in items})
                model_status = "ok"
            except MailError as exc:
                if exc.code == "auth":
                    model_status = "auth"
                else:
                    model_status = exc.code
            except ValueError:
                model_status = "invalid_output"
        rendered = self._render(items, summary, model_status, action, next_token, partial_reason, len(ids))
        return Outcome(rendered, mail_derived=True, stats={
            "result": "ok", "listed": len(raw_items), "read": len(items), "foreign_dropped": foreign,
            "partial": partial_reason, "has_more": bool(next_token), "model": model_status,
            "context_chars": context_chars, "reply_chars": len(rendered.text), "parts": len(rendered.parts)})

    def _prepare(self, ref: str, mid: str, msg: dict[str, Any]) -> MailItem:
        lim = self.settings.limits
        subject, _ = clean_text(msg.get("subject"), lim.subject_max_chars, single_line=True)
        sender, _ = clean_text(msg.get("from"), lim.sender_max_chars, single_line=True)
        received = _received(msg.get("timestamp") or msg.get("created_at"))
        stats = {"images": 0, "hidden_dropped": 0}
        source = msg.get("extracted_text")
        if not isinstance(source, str) or not source.strip():
            source = msg.get("text")
        if not isinstance(source, str) or not source.strip():
            source, stats = html_to_text(msg.get("html"), lim.html_input_max_chars)
        else:
            _, stats = html_to_text(msg.get("html"), lim.html_input_max_chars)
        body, body_truncated = clean_text(source, lim.body_max_chars)
        attachments_raw = msg.get("attachments")
        attachments_raw = attachments_raw if isinstance(attachments_raw, list) else []
        names = []
        for att in attachments_raw[: lim.attachments_listed_max]:
            name, _ = clean_text(att.get("filename") if isinstance(att, dict) else None,
                                 lim.attachment_name_max_chars, single_line=True)
            names.append(name or "(sans nom)")
        return MailItem(ref=ref, message_id=mid, received_at=received, sender=sender, subject=subject,
                        body=body, body_truncated=body_truncated, attachments=names,
                        attachments_total=len(attachments_raw), auth=_auth_summary(msg.get("authentication_results")),
                        images=stats.get("images", 0), hidden_dropped=stats.get("hidden_dropped", 0))

    def _render(self, items: list[MailItem], summary: ModelSummary | None, model_status: str, action: str,
                next_token: str | None, partial: str | None, listed: int) -> Rendered:
        b = Builder(self.settings.limits.reply_max_chars, [
            MARKER,
            "Expéditeurs, objets et contenus ci-dessous sont des affirmations non vérifiées ; "
            "aucun lien n'est actif et rien n'a été ouvert, téléchargé ni modifié.",
        ])
        if action != "list":
            if summary is None:
                b.trusted(f"Résumé IA indisponible ({model_status}) : métadonnées seules.")
            elif summary.synthese:
                b.field("Synthèse (IA, non vérifiée) :", summary.synthese)
        shown: list[str] = []
        for item in items:
            # Keep one message in one Telegram part when possible: start a new part at the boundary.
            if b.room() < 900 and not b.new_part():
                break
            b.trusted("")
            if not b.trusted(f"[{item.ref}] reçu le {item.received_at or 'date inconnue'} (horloge du service) "
                             f"· réf. {_short_ref(item.message_id)}"):
                break
            b.field("De (déclaré) :", item.sender or "inconnu")
            b.field("Objet :", item.subject or "(sans objet)")
            b.trusted(f"Authentification : {item.auth}")
            if item.attachments_total:
                b.field(f"Pièces jointes ({item.attachments_total}, non ouvertes) :", ", ".join(item.attachments))
            if item.images or item.hidden_dropped:
                b.trusted(f"Contenu HTML : {item.images} image(s) non chargée(s), "
                          f"{item.hidden_dropped} bloc(s) masqué(s) ignoré(s).")
            model = summary.messages.get(item.ref) if summary else None
            if model is not None:
                b.trusted("Pertinent pour la recherche : " + ("oui" if model.pertinent else "non ou incertain"))
                b.field("Résumé (IA) :", model.resume)
                for opp in model.opportunites:
                    b.field("Opportunité annoncée :", opp)
                if model.incertitudes:
                    b.field("Incertitudes :", model.incertitudes)
            elif action == "list" or summary is None:
                first, _ = clean_text(item.body, 160, single_line=True)
                b.field("Début :", first)
            if item.body_truncated:
                b.trusted("(corps tronqué à la limite configurée)")
            if b.truncated:
                break
            shown.append(item.ref)
        missing = [i.ref for i in items if i.ref not in shown]
        b.footer("")
        b.footer(f"Affichés : {len(shown)} sur {len(items)} lus ({listed} listés).")
        if missing:
            b.footer("Non affichés faute de place : " + ", ".join(missing)
                     + ". Utilisez « /courriels liste » pour une vue courte.")
        if partial:
            b.footer(f"Lecture partielle ({MESSAGES_FR.get(partial, partial)})")
        if next_token:
            b.footer("D'autres courriels existent : envoyez « /courriels suite » pour la page suivante.")
        return b.build()


_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})")


def _received(value: Any) -> str:
    """API timestamp reduced to a fixed ``YYYY-MM-DD HH:MM`` shape (service clock), or empty when malformed."""
    match = _TS_RE.match(value) if isinstance(value, str) else None
    return f"{match.group(1)} {match.group(2)}" if match else ""


def _short_ref(message_id: str) -> str:
    """Stable, inert reference to a message (hash prefix; the raw id may contain an address)."""
    import hashlib

    return hashlib.sha256(message_id.encode("utf-8", "replace")).hexdigest()[:8]
