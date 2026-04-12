from langchain_core.messages import AIMessage, HumanMessage

from app.workflows.nodes import analyze_node
from app.workflows.state import EmailAgentState
from typing import cast


class DummyModel:
    def invoke(self, _messages):
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "ask_manager_for_approval",
                    "args": {"proposed_action": "create_calendar_event", "reason": "Meeting request"},
                    "id": "1",
                    "type": "tool_call",
                }
            ],
        )


class DummyLLM:
    def bind_tools(self, _tools):
        return DummyModel()


def test_analyze_node_sets_approval_requested_flag_when_approval_tool_is_called():
    state = {
        "messages": [HumanMessage(content="Subject: test")],
        "analyze_passes": 0,
    }
    result = analyze_node(cast(EmailAgentState, cast(object, state)), {"configurable": {"llm": DummyLLM()}})

    assert result["approval_requested"] is True
    assert result["status"] == "processing"


