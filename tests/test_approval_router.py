from typing import cast

from langchain_core.messages import AIMessage

from app.workflows.state import EmailAgentState
from app.workflows.graph import approval_router, post_safe_router


def test_approval_router_routes_error_state_to_cleanup():
    state = {
        "status": "error",
        "messages": [AIMessage(content="MAX_ANALYZE_PASSES_REACHED")],
    }

    assert approval_router(cast(EmailAgentState, cast(object, state))) == "cleanup"



def test_approval_router_routes_sensitive_only_tool_without_approval_to_await_approval():
    state = {
        "status": "processing",
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "notify_manager", "args": {"reason": "urgent"}, "id": "1", "type": "tool_call"}],
            )
        ],
    }

    assert approval_router(cast(EmailAgentState, cast(object, state))) == "await_approval"


def test_approval_router_routes_mixed_safe_and_sensitive_without_approval_to_safe_tools():
    state = {
        "status": "processing",
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "archive_and_label", "args": {"primary_label": "TASK", "is_urgent": True}, "id": "1", "type": "tool_call"},
                    {"name": "notify_manager", "args": {"reason": "urgent"}, "id": "2", "type": "tool_call"},
                ],
            )
        ],
    }

    assert approval_router(cast(EmailAgentState, cast(object, state))) == "safe_tools"


def test_approval_router_routes_sensitive_tool_after_approval_to_approved_tools():
    state = {
        "status": "processing",
        "approval_decision": "APPROVE",
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "notify_manager", "args": {"reason": "urgent"}, "id": "1", "type": "tool_call"}],
            )
        ],
    }

    assert approval_router(cast(EmailAgentState, cast(object, state))) == "approved_tools"


def test_approval_router_routes_mixed_safe_and_sensitive_after_approval_to_approved_tools():
    state = {
        "status": "processing",
        "approval_decision": "APPROVE",
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "create_calendar_event", "args": {"summary": "Meeting", "start_iso": "2026-04-15T14:00:00Z", "end_iso": "2026-04-15T14:45:00Z"}, "id": "1", "type": "tool_call"},
                    {"name": "archive_and_label", "args": {"primary_label": "MEETING_REQUEST", "is_urgent": False}, "id": "2", "type": "tool_call"},
                ],
            )
        ],
    }

    assert approval_router(cast(EmailAgentState, cast(object, state))) == "approved_tools"


def test_post_safe_router_routes_to_await_approval_when_approval_was_requested():
    state = {
        "approval_requested": True,
    }

    assert post_safe_router(cast(EmailAgentState, cast(object, state))) == "await_approval"


def test_post_safe_router_routes_back_to_analyze_when_no_approval_request():
    state = {
        "approval_requested": False,
    }

    assert post_safe_router(cast(EmailAgentState, cast(object, state))) == "analyze"


