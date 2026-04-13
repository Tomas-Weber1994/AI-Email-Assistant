import logging
import json
import re
from typing import Optional, Any, Dict, List
from starlette.concurrency import run_in_threadpool
from langchain_core.messages import HumanMessage

from app.schemas.api import ApprovalDecision, WorkflowStatus
from app.schemas.classification import GmailReservedLabel, GmailSystemLabel
from app.settings import settings
from app.utils.email_utils import get_body, get_headers
from app.workflows.graph import create_email_graph

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("audit_trail")
_WF_TAG_RE = re.compile(r"\[WF:([^]]+)\]")


class WorkflowManager:
    def __init__(self, email, calendar, llm, checkpointer):
        self.email = email
        self.calendar = calendar
        self.llm = llm
        self.graph = create_email_graph(checkpointer)

    def _get_config(self, thread_id: str) -> Dict[str, Any]:
        """Returns the standard configuration for graph invocation."""
        return {
            "configurable": {
                "thread_id": thread_id,
                "email": self.email,
                "calendar": self.calendar,
                "llm": self.llm,
            }
        }

    async def process_unread(self) -> List[Dict[str, Any]]:
        """Main loop for processing new unread emails."""
        unread_messages = await self._run(self.email.list_unread)
        if not unread_messages:
            return []

        results = []
        for msg in unread_messages:
            email_id = msg["id"]
            thread_id = msg.get("threadId") or email_id

            # --- OCHRANA PROTI DUPLICITÁM (Race Condition Prevention) ---
            # 1. Okamžitě odebereme UNREAD, aby další polling cyklus tento email ignoroval.
            await self._run(self.email.modify_labels, email_id, remove=[GmailReservedLabel.UNREAD.value])

            # 2. Skip pokud už na tomto threadu visí schválení (bezpečnostní pojistka).
            is_pending = await self._run(self.email.has_label, email_id, GmailSystemLabel.PENDING_APPROVAL.value)
            if is_pending:
                logger.info("Skipping email %s: already pending manager approval.", email_id)
                continue

            logger.info("Starting workflow for email %s", email_id)
            results.append(await self._process_new_email(email_id, thread_id))

        return results

    async def _process_new_email(self, email_id: str, thread_id: str) -> Dict[str, Any]:
        """Starts the workflow graph for a specific email."""
        config = self._get_config(thread_id)
        try:
            return await self._run(self.graph.invoke, {"email_id": email_id}, config)
        except Exception as e:
            label = "UNCLASSIFIED"
            try:
                snapshot = await self._run(self.graph.get_state, config)
                classification = snapshot.values.get("classification") if snapshot else None
                label = classification.label.value if classification else "UNCLASSIFIED"
            except Exception:
                pass

            self._emit_audit(email_id, label, e)
            return self._error_response(email_id, thread_id, e)

    async def process_pending_approvals(self) -> None:
        """Checks for manager's email responses to resume paused workflows."""
        replies = await self._run(self.email.list_approval_replies, settings.MANAGER_EMAIL)
        if not replies:
            return

        for reply in replies:
            msg_id = reply["id"]
            msg = await self._run(self.email.get_message, msg_id)

            body_text = f"{msg.get('snippet', '')}\n{get_body(msg)}"
            decision = self._parse_decision(body_text)
            workflow_id = self._extract_workflow_id(msg)

            if decision and workflow_id:
                await self.resume_with_decision(workflow_id, decision)
                # Označíme odpověď manažera za vyřízenou
                await self._run(self.email.modify_labels, msg_id, remove=[GmailReservedLabel.UNREAD.value])

    async def resume_with_decision(self, thread_id: str, decision: ApprovalDecision) -> Dict[str, Any]:
        """Resumes a workflow with the manager's APPROVE/REJECT input."""
        config = self._get_config(thread_id)
        try:
            snapshot = await self._run(self.graph.get_state, config)
            email_id = snapshot.values.get("email_id") if snapshot else None

            # Injekce rozhodnutí do stavu grafu
            await self._run(self.graph.update_state, config, {
                "messages": [HumanMessage(content=decision.value)],
                "manager_decision": decision,
            })

            # Pokračování v exekuci
            result = await self._run(self.graph.invoke, None, config)

            # Pokud vše proběhlo, odstraníme dočasný label PENDING_APPROVAL
            if email_id:
                await self._run(self.email.modify_labels, email_id, remove=[GmailSystemLabel.PENDING_APPROVAL.value])

            return result
        except Exception as e:
            return self._error_response(None, thread_id, e)

    @staticmethod
    def _parse_decision(text: str) -> Optional[ApprovalDecision]:
        """Parses the manager's decision from the email text."""
        for line in filter(None, map(str.strip, text.splitlines())):
            if line.startswith(">"):
                continue

            token = line.split()[0].strip(".,!?:;\"'()[]{}").upper()
            if token == ApprovalDecision.APPROVE.value:
                return ApprovalDecision.APPROVE
            if token == ApprovalDecision.REJECT.value:
                return ApprovalDecision.REJECT
        return None

    @staticmethod
    def _extract_workflow_id(msg: Dict[str, Any]) -> Optional[str]:
        headers = get_headers(msg)
        subject = headers.get("Subject", "")
        body = f"{msg.get('snippet', '')}\n{get_body(msg)}"

        for source in (subject, body):
            match = _WF_TAG_RE.search(source or "")
            if match:
                return match.group(1).strip()

        return msg.get("threadId")

    @staticmethod
    def _error_response(email_id: Optional[str], thread_id: str, error: Exception) -> Dict[str, Any]:
        logger.error(f"Critical error on thread {thread_id}: {error}", exc_info=True)
        return {
            "email_id": email_id,
            "thread_id": thread_id,
            "status": WorkflowStatus.ERROR,
            "error_message": str(error),
        }

    @staticmethod
    def _emit_audit(email_id: str, label: str, error: Exception) -> None:
        entry = {
            "email_id": email_id,
            "label": label,
            "outcome": "ERROR",
            "trace": [str(error)]
        }
        audit_logger.info("AUDIT_RECORD: %s", json.dumps(entry, ensure_ascii=False))

    @staticmethod
    async def _run(func, *args, **kwargs) -> Any:
        return await run_in_threadpool(func, *args, **kwargs)
