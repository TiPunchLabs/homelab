"""scout_mail — read-only AgentMail digest for Scout, isolated from Scout's privileged agent.

Registered in Scout's profile only (``plugins.enabled`` of that profile). It adds:
- ``/courriels``: a slash command run by the gateway BEFORE any agent turn. Its reply is posted
  straight to the owner's private chat and is never written to Scout's session history;
- four hooks that keep mail-derived text away from privileged turns:
  ``pre_gateway_dispatch`` refuses a message that replies to (or pastes) a mail result,
  ``pre_llm_call`` and ``transform_tool_result`` taint a session in which such text appears,
  ``pre_tool_call`` vetoes every tool in a tainted session (fail closed).
No tool is registered and no global registry is touched.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from .config import SettingsError, load_settings
from .service import Caller, MailService
from .taint import LedgerFull, TaintStore, TaintStoreError
from .transport import HttpxBackend

logger = logging.getLogger("scout_mail")

BLOCK_FR = ("Outil bloqué : cette conversation contient du contenu issu de courriels, non fiable. "
            "Aucun outil n'est disponible dans cette session ; ouvrez une nouvelle conversation avec /new.")
REMOVED_FR = "[Résultat retiré : il contient du contenu de courriel non fiable. Session restreinte.]"
REFUSAL_COMMAND = "/courriels refus-reponse"
LEDGER_COMMAND = "/courriels registre-illisible"
FULL_FR = ("Registre de sécurité des courriels plein : aucun nouveau résumé n'est livré tant que "
           "l'opérateur ne l'a pas archivé (runbook, section registre).")


def _text_of(value: Any, limit: int = 200_000) -> str:
    """Flatten message content (str or list of parts) into bounded text for detection only."""
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, dict):
        return _text_of(value.get("content") or value.get("text") or "", limit)
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        size = 0
        for part in value:
            piece = _text_of(part, limit - size)
            out.append(piece)
            size += len(piece)
            if size >= limit:
                break
        return "\n".join(out)
    return ""


class _Plugin:
    def __init__(self, ctx: Any, home: Path) -> None:
        self.ctx = ctx
        self.home = home
        try:
            from hermes_constants import profile_name_for_home

            self.profile = profile_name_for_home(home) or ""
        except Exception:
            self.profile = ""
        self.settings = None
        self.error: str | None = None
        try:
            self.settings = load_settings(Path(__file__).with_name("settings.json"))
        except SettingsError as exc:
            self.error = str(exc)
            logger.warning("scout_mail settings invalid: %s", exc)
        self.store = TaintStore(home / "plugin-data" / "scout_mail" / "taint.json")
        # Sessions that must stay restricted although the ledger could not record them.
        self.guarded: set[str] = set()
        self.service = None
        if self.settings is not None:
            from agent.secret_scope import get_secret

            self.service = MailService(self.settings, HttpxBackend(), lambda name: get_secret(name))

    # ---- command -------------------------------------------------------------------------------

    async def command(self, raw_args: str, source: Any = None, **_: Any) -> str | None:
        from .service import MESSAGES_FR

        if self.service is None:
            return MESSAGES_FR["config"]
        arg = (raw_args or "").strip().lower()
        if arg == "registre-illisible":
            return ("Le registre de sécurité des courriels est illisible ou plein : Scout refuse les "
                    "messages jusqu'à intervention de l'opérateur (runbook, section rupture).")
        caller = Caller(
            profile=self.profile,
            platform=str(getattr(getattr(source, "platform", None), "value", getattr(source, "platform", "")) or ""),
            chat_type=str(getattr(source, "chat_type", "") or ""),
            chat_id=str(getattr(source, "chat_id", "") or ""),
            user_id=str(getattr(source, "user_id", "") or ""),
        )
        outcome = await asyncio.to_thread(self.service.run, raw_args, caller)
        if not outcome.mail_derived:
            return outcome.rendered.text
        # Ledger first: if it cannot record the result, nothing mail-derived is delivered.
        try:
            self.store.record_result(caller.chat_id, [], outcome.rendered.parts)
        except LedgerFull:
            return FULL_FR
        except TaintStoreError:
            return MESSAGES_FR["delivery"]
        delivered: list[str] = []
        posted = 0
        for part in outcome.rendered.parts:
            handle = await self.ctx.apost_message(part)
            if not getattr(handle, "ok", False):
                break
            posted += 1
            if getattr(handle, "message_id", None):
                delivered.append(str(handle.message_id))
        if delivered:
            try:
                self.store.record_result(caller.chat_id, delivered, [])
            except TaintStoreError:
                logger.warning("scout_mail could not record delivered message ids")
        if posted == 0:
            return MESSAGES_FR["delivery"]
        if posted < len(outcome.rendered.parts):
            return "Livraison partielle du résumé : relancez /courriels liste."
        return None

    # ---- hooks ---------------------------------------------------------------------------------

    def pre_gateway_dispatch(self, event: Any = None, **_: Any) -> dict | None:
        try:
            source = getattr(event, "source", None)
            chat_id = str(getattr(source, "chat_id", "") or "")
            reply_id = getattr(event, "reply_to_message_id", None)
            reply_text = getattr(event, "reply_to_text", None)
            text = getattr(event, "text", None)
            if self.store.sessions_full():
                return {"action": "rewrite", "text": LEDGER_COMMAND}
            if reply_id and (self.store.is_result_message(chat_id, str(reply_id))
                             or self.store.text_is_tainted(reply_text)):
                return {"action": "rewrite", "text": REFUSAL_COMMAND}
            if isinstance(text, str) and not text.startswith("/courriels") and self.store.text_is_tainted(text):
                return {"action": "rewrite", "text": REFUSAL_COMMAND}
            return None
        except TaintStoreError:
            return {"action": "rewrite", "text": LEDGER_COMMAND}
        except Exception:
            logger.warning("scout_mail pre_gateway_dispatch error; refusing the message")
            return {"action": "rewrite", "text": LEDGER_COMMAND}

    def pre_llm_call(self, session_id: str = "", user_message: Any = None, conversation_history: Any = None,
                     parent_session_id: str = "", **_: Any) -> None:
        if not session_id:
            return None
        try:
            if session_id in self.guarded or self.store.is_session_tainted(session_id):
                return None
            if parent_session_id and (parent_session_id in self.guarded
                                      or self.store.is_session_tainted(parent_session_id)):
                self._restrict(session_id)
                return None
            if self.store.text_is_tainted(_text_of(user_message)) or \
                    self.store.text_is_tainted(_text_of(conversation_history)):
                self._restrict(session_id)
        except Exception:
            logger.warning("scout_mail pre_llm_call could not evaluate taint; session guarded in memory")
            self.guarded.add(session_id)
        return None

    def _restrict(self, session_id: str) -> None:
        """Persist the restriction; if the ledger refuses, keep it in memory (fail closed)."""
        try:
            self.store.taint_session(session_id)
        except TaintStoreError:
            logger.warning("scout_mail could not persist a session restriction; guarded in memory")
            self.guarded.add(session_id)

    def pre_tool_call(self, tool_name: str = "", session_id: str = "", **_: Any) -> dict | None:
        try:
            if session_id in self.guarded or self.store.is_session_tainted(session_id):
                return {"action": "block", "message": BLOCK_FR}
            return None
        except Exception:
            return {"action": "block", "message": BLOCK_FR}

    def transform_tool_result(self, tool_name: str = "", result: Any = None, session_id: str = "",
                              **_: Any) -> str | None:
        try:
            if self.store.text_is_tainted(_text_of(result)):
                self._restrict(session_id)
                return REMOVED_FR
            return None
        except Exception:
            if session_id:
                self.guarded.add(session_id)
            return REMOVED_FR


def register(ctx: Any) -> None:
    """Hermes entry point: one command, four hooks, no tool."""
    from hermes_constants import get_hermes_home

    plugin = _Plugin(ctx, Path(get_hermes_home()))
    ctx.register_command("courriels", handler=plugin.command,
                         description="Résumé en lecture seule de la boîte courriel dédiée",
                         args_hint="[liste|suite|aide]")
    ctx.register_hook("pre_gateway_dispatch", plugin.pre_gateway_dispatch)
    ctx.register_hook("pre_llm_call", plugin.pre_llm_call)
    ctx.register_hook("pre_tool_call", plugin.pre_tool_call)
    ctx.register_hook("transform_tool_result", plugin.transform_tool_result)
