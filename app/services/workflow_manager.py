import logging
import json
from typing import Optional
from starlette.concurrency import run_in_threadpool
from langchain_core.messages import HumanMessage
from app.schemas.api import ApprovalDecision, WorkflowStatus
from app.schemas.classification import GmailReservedLabel, GmailSystemLabel
from app.settings import settings
from app.utils.email_utils import get_body
from app.workflows.graph import create_email_graph

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("audit_trail")


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

    @staticmethod
    def _snapshot_values(snapshot) -> dict:
        return snapshot.values if snapshot and hasattr(snapshot, "values") else {}

    @classmethod
    def _label_from_snapshot(cls, snapshot) -> str:
        classification = cls._snapshot_values(snapshot).get("classification")
        return classification.label.value if classification and hasattr(classification, "label") else "UNCLASSIFIED"

    async def process_unread(self):
        """Fetches unread inbox emails and starts a new workflow for each one."""
        unread_messages = await run_in_threadpool(self.email.list_unread)

        if not unread_messages:
            return []

        logger.info("Found %d new email(s) to process.", len(unread_messages))

        results = []
        for msg_info in unread_messages:
            email_id = msg_info["id"]
            # thread_id is the stable workflow key used by the checkpointer for resume.
            thread_id = msg_info.get("threadId") or email_id

            if await run_in_threadpool(self.email.has_label, email_id, GmailSystemLabel.PENDING_APPROVAL.value):
                logger.info("Skipping email %s: already waiting for manager approval.", email_id)
                continue

            result = await self.process_new_email(email_id, thread_id)
            results.append(result)

        return results

    async def process_new_email(self, email_id: str, thread_id: str):
        """Runs the graph for a newly received email."""
        config = self._config(thread_id)
        try:
            result = await run_in_threadpool(
                self.graph.invoke,
                {"email_id": email_id},
                config,
            )
            return result

        except Exception as e:
            logger.error("Critical error processing thread %s: %s", thread_id, e, exc_info=True)
            # Try to read the classification already saved in the checkpoint.
            label = "UNCLASSIFIED"
            try:
                state_snapshot = await run_in_threadpool(self.graph.get_state, config)
                label = self._label_from_snapshot(state_snapshot)
            except Exception:
                pass  # fall back to UNCLASSIFIED

            self._emit_error_audit(email_id=email_id, error=e, label=label)
            return {
                "email_id": email_id,
                "thread_id": thread_id,
                "status": WorkflowStatus.ERROR,
                "error_message": str(e),
            }

    async def process_pending_approvals(self):
        """Polls Gmail for manager approval replies and resumes the matching workflows."""
        replies = await run_in_threadpool(
            self.email.list_approval_replies,
            manager_email=settings.MANAGER_EMAIL,
        )

        if not replies:
            return

        logger.info("Found %d approval reply candidate(s).", len(replies))

        for reply_info in replies:
            msg_id = reply_info["id"]
            full_msg = await run_in_threadpool(self.email.get_message, msg_id)

            snippet = full_msg.get("snippet", "")
            full_text = f"{snippet}\n{get_body(full_msg)}"
            thread_id = full_msg.get("threadId")
            decision = self._extract_manager_decision(full_text)

            if not decision:
                logger.debug("Skipping reply %s: decision not parsed from manager message.", msg_id)
                continue

            if not thread_id:
                logger.warning("Skipping reply %s: missing threadId.", msg_id)
                continue

            logger.info("Manager decision for thread %s: %s", thread_id, decision.value)
            await self.resume_with_decision(thread_id, decision)

            # Mark the reply as read so it is not processed again.
            await run_in_threadpool(
                self.email.modify_labels,
                msg_id,
                remove=[GmailReservedLabel.UNREAD.value],
            )

    async def resume_with_decision(self, thread_id: str, decision: ApprovalDecision):
        """Resumes the graph after the manager replies APPROVE or REJECT."""
        config = self._config(thread_id)
        try:
            # Read the checkpoint to get the original message ID (needed to remove the
            # PENDING_APPROVAL label, which is on the message, not the thread).
            snapshot = await run_in_threadpool(self.graph.get_state, config)
            original_email_id = self._snapshot_values(snapshot).get("email_id")

            await run_in_threadpool(
                self.graph.update_state,
                config,
                {
                    "messages": [HumanMessage(content=decision.value)],
                    "manager_decision": decision,
                }
            )

            result = await run_in_threadpool(self.graph.invoke, None, config)

            if original_email_id:
                await run_in_threadpool(
                    self.email.modify_labels,
                    original_email_id,
                    remove=[GmailSystemLabel.PENDING_APPROVAL.value],
                )

            return result

        except Exception as e:
            logger.error("Error during resumption of thread %s: %s", thread_id, e, exc_info=True)
            return {"thread_id": thread_id, "status": WorkflowStatus.ERROR, "error_message": str(e)}

    @staticmethod
    def _extract_manager_decision(text: str) -> Optional[ApprovalDecision]:
        # Parse the first explicit decision token from manager-authored lines.
        # This tolerates punctuation like "APPROVE." and avoids exact-match brittleness.
        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            if not line or line.startswith(">"):
                continue

            token = line.split()[0].strip(".,!?:;\"'()[]{}")
            normalized = token.upper()
            if normalized == ApprovalDecision.APPROVE.value:
                return ApprovalDecision.APPROVE
            if normalized == ApprovalDecision.REJECT.value:
                return ApprovalDecision.REJECT

        return None

    @staticmethod
    def _emit_error_audit(email_id: str, error: Exception, label: str = "UNCLASSIFIED") -> None:
        audit_entry = {
            "email_id": email_id,
            "label": label,
            "is_urgent": False,
            "actions": [],
            "outcome": "ERROR",
            "trace": [f"ERROR: Workflow failed outside cleanup: {error}"],
        }
        audit_logger.info("AUDIT_RECORD: %s", json.dumps(audit_entry, ensure_ascii=False))
