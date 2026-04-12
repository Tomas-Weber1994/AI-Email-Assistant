import logging
import uuid
from typing import Literal, Any, Optional
from starlette.concurrency import run_in_threadpool
from app.workflows.graph import create_email_graph

logger = logging.getLogger("agent.audit")


class WorkflowManager:
    def __init__(self, email, calendar, llm, checkpointer):
        self.email = email
        self.calendar = calendar
        self.llm = llm
        self.graph = create_email_graph(checkpointer)

    def _config(self, thread_id: str):
        return {
            "configurable": {
                "thread_id": thread_id,
                "email": self.email,
                "calendar": self.calendar,
                "llm": self.llm,
            }
        }

    async def process_unread(self):
        """
        Načte nepřečtené e-maily z Inboxu a pro každý spustí nové workflow.
        Tuto metodu volá _poll_loop v main.py.
        """
        unread_messages = await run_in_threadpool(self.email.list_unread)

        if not unread_messages:
            return []

        logger.info(f"Nalezeno {len(unread_messages)} nových e-mailů ke zpracování.")

        results = []
        for msg_info in unread_messages:
            email_id = msg_info["id"]
            # thread_id je stabilní klíč workflow pro checkpointer/resume.
            thread_id = msg_info.get("threadId") or email_id

            if await run_in_threadpool(self.email.has_label, email_id, "PENDING_APPROVAL"):
                logger.info(f"Skipping email {email_id}: already waiting for manager approval.")
                continue

            # Spustíme zpracování nového e-mailu
            result = await self.process_new_email(email_id, thread_id)
            results.append(result)

        return results

    async def process_new_email(self, email_id: str, thread_id: str):
        """Spustí graf pro nově příchozí e-mail."""
        config = self._config(thread_id)
        try:
            # Spuštění workflow
            result = await run_in_threadpool(
                self.graph.invoke,
                {"email_id": email_id},
                config,
            )

            # Logování úspěšného dokončení nebo čekání na schválení
            self._log_audit(thread_id, result.get("status"), result.get("classification"))
            return result

        except Exception as e:
            # Graceful failure: zalogování chyby a vrácení bezpečného stavu
            logger.error(f"Critical error processing thread {thread_id}: {str(e)}", exc_info=True)
            return {
                "email_id": email_id,
                "thread_id": thread_id,
                "status": "error",
                "error_message": str(e),
            }

    async def process_pending_approvals(self):
        """
        Vyhledá v Gmailu odpovědi od manažera na žádosti o schválení
        a probudí příslušná workflow.
        """
        from app.settings import settings

        replies = await run_in_threadpool(
            self.email.list_approval_replies,
            manager_email=settings.MANAGER_EMAIL
        )

        for reply_info in replies:
            msg_id = reply_info["id"]
            full_msg = await run_in_threadpool(self.email.get_message, msg_id)

            body = full_msg.get("snippet", "").upper()
            thread_id = full_msg.get("threadId")

            decision: Optional[Literal["APPROVE", "REJECT"]] = None
            if "APPROVE" in body:
                decision = "APPROVE"
            elif "REJECT" in body:
                decision = "REJECT"

            if decision and thread_id:
                logger.info(f"Rozhodnutí manažera pro thread {thread_id}: {decision}")

                # Probudíme graf s daným rozhodnutím
                await self.resume_with_decision(thread_id, decision)

                # Označíme zprávu jako přečtenou (odstraníme UNREAD), aby se neprocesovala znovu
                await run_in_threadpool(
                    self.email.modify_labels,
                    msg_id,
                    remove=["UNREAD"]
                )

    async def resume_with_decision(self, email_id: str, decision: Literal["APPROVE", "REJECT"]):
        """Probudí graf poté, co manažer odpoví APPROVE/REJECT."""
        config = self._config(email_id)
        try:
            from langchain_core.messages import HumanMessage

            state_snapshot = await run_in_threadpool(self.graph.get_state, config)
            original_email_id = None
            if state_snapshot and getattr(state_snapshot, "values", None):
                original_email_id = state_snapshot.values.get("email_id")

            await run_in_threadpool(
                self.graph.update_state,
                config,
                {"messages": [HumanMessage(content=decision.upper())]}
            )

            # Pokračování v běhu grafu z bodu přerušení
            result = await run_in_threadpool(self.graph.invoke, None, config)

            if original_email_id:
                await run_in_threadpool(
                    self.email.modify_labels,
                    original_email_id,
                    remove=["PENDING_APPROVAL"],
                )

            self._log_audit(email_id, result.get("status"), result.get("classification"), decision)
            return result

        except Exception as e:
            logger.error(f"Error during resumption of email {email_id}: {str(e)}", exc_info=True)
            return {"email_id": email_id, "status": "error", "error_message": str(e)}

    def _log_audit(self, email_id: str, status: str, classification: Any = None, decision: str = None):
        """Vytvoří strukturovaný log o zpracování e-mailu."""
        log_entry = {
            "event_id": str(uuid.uuid4()),
            "email_id": email_id,
            "label": getattr(classification, 'label', 'UNKNOWN') if classification else "UNKNOWN",
            "is_urgent": getattr(classification, 'is_urgent', False) if classification else False,
            "decision": decision,
            "outcome": status
        }
        logger.info(f"AUDIT_LOG: {log_entry}")
