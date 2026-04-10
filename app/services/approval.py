import logging
from starlette.concurrency import run_in_threadpool
from app.database import db
from app.schemas.classification import ApprovalStatus

logger = logging.getLogger(__name__)


class ApprovalService:
    def __init__(self, gmail):
        """
        Service for managing approval processes.
        Monitors threads with the manager and updates status in DB.
        """
        self.gmail = gmail

    async def process_pending(self) -> list[dict]:
        """
        Goes through all pending approval records, checks Gmail threads
        for the manager's decision, and updates DB accordingly.
        """
        pending = await run_in_threadpool(db.list_by_status, ApprovalStatus.PENDING)
        results = []

        for record in pending:
            if not record.approval_thread_id:
                continue

            decision = await run_in_threadpool(
                self._fetch_and_parse_decision,
                record.approval_thread_id
            )

            if not decision:
                continue

            if decision == "APPROVE":
                record.status = ApprovalStatus.APPROVED
                record.audit_trail.append("Manager approved via email reply.")
            elif decision == "REJECT":
                record.status = ApprovalStatus.REJECTED
                record.audit_trail.append("Manager rejected via email reply.")

            await run_in_threadpool(db.save, record)

            results.append({
                "email_id": record.email_id,
                "decision": decision,
                "thread_id": record.approval_thread_id
            })

            logger.info(f"Approval resolved for {record.email_id}: {decision}")

        return results

    def _fetch_and_parse_decision(self, thread_id: str) -> str | None:
        """
        Fetches the Gmail thread and looks for the manager's APPROVE/REJECT
        keyword in the most recent reply.
        """
        try:
            thread = self.gmail.get_thread(thread_id)
            messages = thread.get("messages", [])

            # Walk messages newest-first (latest manager reply)
            for msg in reversed(messages):
                snippet = msg.get("snippet", "").strip().upper()

                # Skip the original approval request sent by the agent
                if "[APPROVAL]" in snippet:
                    continue

                if snippet.startswith("APPROVE"):
                    return "APPROVE"
                if snippet.startswith("REJECT"):
                    return "REJECT"

            return None
        except Exception as e:
            logger.error(f"Error fetching/parsing thread {thread_id}: {e}")
            return None
