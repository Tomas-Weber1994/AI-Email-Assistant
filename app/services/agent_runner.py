# app/services/agent_runner.py
import logging
from starlette.concurrency import run_in_threadpool
from app.agent.graph import app as agent_graph
from app.database import db
from app.schemas.classification import EmailRecord, ApprovalStatus

logger = logging.getLogger(__name__)


class AgentRunner:
    def __init__(self, gmail, calendar):
        self.gmail = gmail
        self.calendar = calendar

    async def process_unread(self, max_results: int = 20) -> list[dict]:
        """
        Main entry point for API endpoint.
        Synchronizing Gmail unread messages and approved DB records, then running the workflow for each.
        """
        tasks = []

        # 1) New emails
        unread = await run_in_threadpool(self.gmail.list_unread, max_results=max_results)
        for msg in unread:
            tasks.append({"id": msg["id"], "record": None, "retry": False})

        # 2) Approved records (retry)
        approved = await run_in_threadpool(db.list_by_status, ApprovalStatus.APPROVED)
        for record in approved:
            tasks.append({"id": record.email_id, "record": record, "retry": True})

        results = []
        for task in tasks:
            res = await self._run_workflow(task["id"], task["record"], task["retry"])
            results.append(res)
        return results

    async def _run_workflow(self, email_id: str, record: EmailRecord = None, is_retry: bool = False) -> dict:
        """
        Run LangGraph workflow for a single email.
        Returns a structured AgentResponse dict for the API.
        """
        try:
            existing = await run_in_threadpool(db.find_by_id, email_id)

            if not is_retry and existing:
                if existing.classification is not None:
                    logger.info(f"Email {email_id} already processed. Skipping.")
                    return {"email_id": email_id, "status": "skipped"}
                else:
                    logger.info(f"Email {email_id} found in DB but incomplete. Re-processing.")
                    record = existing

            if not record:
                record = EmailRecord(email_id=email_id)

            state = {
                "record": record,
                "is_retry": is_retry,
                "error": None
            }
            final_state = await run_in_threadpool(
                agent_graph.invoke,
                state,
                {"configurable": {"gmail": self.gmail, "calendar": self.calendar}}
            )

            # Update record from final state (LangGraph returns a new dict)
            record = final_state["record"]

            if is_retry and not final_state.get("error"):
                # Reset status so list_by_status(APPROVED) won't pick it up again.
                record.status = ApprovalStatus.NOT_REQUIRED
                record.audit_trail.append("Approved actions executed successfully.")
                await run_in_threadpool(db.save, record)

            if final_state.get("error"):
                record.audit_trail.append(f"Error: {final_state['error']}")

            # Build structured response
            response = record.to_response()
            logger.info(f"Processed {email_id}: {response.model_dump_json()}")
            return response.model_dump()

        except Exception as e:
            logger.exception(f"Critical workflow failure for {email_id}")
            return {"email_id": email_id, "status": "error", "error": str(e)}
