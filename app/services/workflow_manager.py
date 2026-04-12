import logging
import re
from typing import Dict, Any, List, Optional, Tuple, Set, Literal, cast
from langchain_openai import ChatOpenAI
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from starlette.concurrency import run_in_threadpool

from app.schemas.api import ManagerReplyDecision
from app.settings import settings
from app.utils.email_utils import get_body, get_headers
from app.workflows.graph import create_email_graph

logger = logging.getLogger(__name__)


class WorkflowManager:
    def __init__(self, email, calendar, llm: ChatOpenAI, checkpointer: SqliteSaver):
        self.email = email
        self.calendar = calendar
        self.llm = llm
        self.graph = create_email_graph(checkpointer)
        # Lokální cache pro zamezení duplicitního spuštění v rámci jednoho běhu
        self._processing_ids: Set[str] = set()

    def _config(self, thread_id: str) -> RunnableConfig:
        return {
            "configurable": {
                "thread_id": thread_id,
                "email": self.email,
                "calendar": self.calendar,
                "llm": self.llm,
            }
        }

    async def _invoke_graph(self, graph_input: Any, thread_id: str) -> Any:
        """Run sync graph invoke safely from async code (SqliteSaver is sync-only)."""
        return await run_in_threadpool(self.graph.invoke, graph_input, self._config(thread_id))

    async def process_unread(self, max_results: int = 20) -> List[Dict[str, Any]]:
        """Načte nové emaily a spustí pro každý novou instanci grafu."""
        unread = await run_in_threadpool(self.email.list_unread, max_results)
        logger.info("Unread poll fetched %s messages (limit=%s)", len(unread), max_results)

        for msg in unread:
            email_id = msg.get("id")
            if not email_id or email_id in self._processing_ids:
                if not email_id:
                    logger.warning("Skipping unread message without id: %s", msg)
                else:
                    logger.info("Skipping email %s - already processing in current run", email_id)
                continue

            # Pojistka: Nekonáme, pokud už se na schválení čeká (label v Gmailu)
            if await run_in_threadpool(self.email.has_label, email_id, "PENDING_APPROVAL"):
                logger.info("Skipping email %s - pending approval already exists", email_id)
                continue

            self._processing_ids.add(email_id)
            logger.info(f"Starting workflow for email: {email_id}")

            try:
                # Prvotní spuštění grafu
                await self._invoke_graph({"email_id": email_id}, email_id)
            finally:
                self._processing_ids.discard(email_id)

        return unread

    async def resume_approval(self, email_id: str, decision: str) -> Dict[str, Any]:
        """Probuzení grafu po rozhodnutí manažera."""
        normalized_decision = decision.strip().upper()
        logger.info("Resume requested for workflow %s with decision=%s", email_id, normalized_decision)

        has_pending = await run_in_threadpool(self.email.has_label, email_id, "PENDING_APPROVAL")
        if not has_pending:
            logger.warning("Resume skipped for workflow %s - no PENDING_APPROVAL label", email_id)
            return {"status": "skipped", "reason": "No pending approval found."}

        try:
            # --- KRITICKÝ FIX START ---
            # Musíme explicitně zapsat rozhodnutí do stavu grafu,
            # aby ho analyze_node mohl přečíst a vynutit exekuci toolu.
            await run_in_threadpool(
                self.graph.update_state,
                self._config(email_id),
                {"approval_decision": normalized_decision}
            )
            logger.info("Graph state updated with approval_decision=%s for %s", normalized_decision, email_id)
            # --- KRITICKÝ FIX KONEC ---

            # Nyní probudíme graf z interruptu
            command = Command(resume=normalized_decision)
            invoke_result = await self._invoke_graph(command, email_id)
            logger.info("Resume invoke completed for workflow %s with result=%s", email_id, invoke_result)

            # Kontrola výsledku
            graph_status = invoke_result.get("status") if isinstance(invoke_result, dict) else None
            if graph_status == "error":
                return {
                    "status": "error",
                    "detail": "Workflow ended in error state after resume.",
                    "graph_status": graph_status,
                }

            # Úklid labelu v Gmailu až po úspěšném doběhu grafu
            await run_in_threadpool(self.email.modify_labels, email_id, None,
                                    ["PENDING_APPROVAL", "APPROVAL_REMINDER_SENT"])
            logger.info("Removed PENDING_APPROVAL label after resume for workflow %s", email_id)

            return {"status": "success", "decision": normalized_decision}

        except Exception as e:
            logger.exception("Error during resume for %s", email_id)
            return {"status": "error", "detail": str(e)}

    async def _send_approval_reminder(self, workflow_id: str) -> Dict[str, Any]:
        logger.info("Reminder requested for workflow %s", workflow_id)

        # ZDE JE ZMĚNA: Ptáme se grafu, ne Gmailu
        state = await run_in_threadpool(self.graph.get_state, self._config(workflow_id))

        # Pokud graf čeká před uzlem 'ask_approval', znamená to, že interrupt je aktivní
        is_waiting = state.next and "ask_approval" in state.next

        if not is_waiting:
            logger.warning("Reminder skipped for workflow %s - graph is not in interrupt state", workflow_id)
            return {"status": "skipped", "reason": "Workflow is not waiting for approval."}

        reminder_sent = await run_in_threadpool(self.email.has_label, workflow_id, "APPROVAL_REMINDER_SENT")
        if reminder_sent:
            return {"status": "skipped", "reason": "Already sent."}

        raw_msg = await run_in_threadpool(self.email.get_message, workflow_id)
        headers = get_headers(raw_msg)
        subject = headers.get("Subject", "Email")
        body = (
            "Reminder: the AI agent is still waiting for your decision.\n\n"
            f"WORKFLOW ID: {workflow_id}\n"
            "Please reply with APPROVE or REJECT."
        )

        await run_in_threadpool(
            self.email.send_message,
            settings.MANAGER_EMAIL,
            f"[APPROVAL REQUIRED] [WF:{workflow_id}] Reminder: {subject}",
            body,
        )
        await run_in_threadpool(self.email.modify_labels, workflow_id, ["APPROVAL_REMINDER_SENT"], None)
        logger.info("Reminder sent for workflow %s and APPROVAL_REMINDER_SENT label set", workflow_id)
        return {"status": "success", "workflow_id": workflow_id}

    async def process_pending_approvals(self, max_results: int = 20):
        """Hledá odpovědi od manažera a posouvá čekající grafy."""
        replies = await run_in_threadpool(self.email.list_approval_replies, settings.MANAGER_EMAIL, max_results)
        logger.info("Approval inbox poll fetched %s replies (limit=%s)", len(replies), max_results)

        for reply in replies:
            reply_id = reply.get("id")
            if not reply_id:
                logger.warning("Skipping approval reply without id: %s", reply)
                continue
            raw = await run_in_threadpool(self.email.get_message, reply_id)
            body = get_body(raw)
            subject = get_headers(raw).get("Subject", "")

            decision, workflow_id = self._extract_decision_and_workflow_id(body, subject)
            logger.info(
                "Parsed manager reply id=%s -> decision=%s workflow_id=%s (strict mode: APPROVE/REJECT only)",
                reply_id,
                decision,
                workflow_id,
            )

            if decision and workflow_id:
                parsed = ManagerReplyDecision(
                    decision=cast(Literal["APPROVE", "REJECT"], decision),
                    workflow_id=workflow_id,
                )
                logger.info("Resuming workflow %s from reply %s with decision=%s", parsed.workflow_id, reply_id, parsed.decision)
                res = await self.resume_approval(parsed.workflow_id, parsed.decision)
                logger.info("Resume result for workflow %s: %s", parsed.workflow_id, res)
                if res.get("status") in ["success", "skipped"]:
                    await run_in_threadpool(self.email.modify_labels, reply_id, None, ["UNREAD", "INBOX"])
                    logger.info("Archived manager reply %s after resume result=%s", reply_id, res.get("status"))
            elif workflow_id:
                logger.warning(
                    "Reply %s contains workflow_id=%s but no strict decision token on first line; sending reminder",
                    reply_id,
                    workflow_id,
                )
                await self._send_approval_reminder(workflow_id)
                await run_in_threadpool(self.email.modify_labels, reply_id, None, ["UNREAD", "INBOX"])
                logger.info("Archived unparseable manager reply %s after reminder flow", reply_id)
            else:
                # Pokud z emailu nic nevyčteme, archivujeme ho, ať tam nestraší
                logger.warning("Reply %s has no workflow id in subject; archiving without action", reply_id)
                await run_in_threadpool(self.email.modify_labels, reply_id, None, ["UNREAD", "INBOX"])
                logger.info("Archived manager reply %s with no actionable workflow reference", reply_id)

    @staticmethod
    def _extract_decision_and_workflow_id(
            text: str,
            subject: str = ""
    ) -> Tuple[Optional[Literal["APPROVE", "REJECT"]], Optional[str]]:
        """Strictní extrakce rozhodnutí + workflow ID pro approval reply."""
        decision: Optional[Literal["APPROVE", "REJECT"]] = None
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
        first_token = first_line.rstrip(".,!?:;").upper()
        if first_token in {"APPROVE", "REJECT"}:
            decision = first_token

        workflow_id = None
        if subject:
            subject_match = re.search(r"\[WF:([a-fA-F0-9]+)]", subject, flags=re.IGNORECASE)
            workflow_id = subject_match.group(1).strip() if subject_match else None
        return decision, workflow_id
