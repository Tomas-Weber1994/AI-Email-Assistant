from typing import cast

from langchain_core.messages import AIMessage

from app.schemas.classification import EmailLabel
from app.workflows.policies import apply_sales_outreach_guard
from app.workflows.state import EmailClassification, EmailAgentState
from app.workflows.tools import ToolName


def _state_for(label: EmailLabel) -> EmailAgentState:
    return cast(EmailAgentState, {
        "classification": EmailClassification(label=label, is_urgent=False),
    })


def test_sales_outreach_guard_injects_required_tools():
    response = AIMessage(content="plain response", tool_calls=[])

    guarded = apply_sales_outreach_guard(response, _state_for(EmailLabel.SALES_OUTREACH))

    names = [tc["name"] for tc in guarded.tool_calls]
    assert ToolName.SEND_REPLY.value in names
    assert ToolName.ARCHIVE_AND_LABEL.value in names


def test_sales_outreach_guard_keeps_non_sales_response_unchanged():
    response = AIMessage(content="plain response", tool_calls=[])

    guarded = apply_sales_outreach_guard(response, _state_for(EmailLabel.INFO_ONLY))

    assert guarded is response

