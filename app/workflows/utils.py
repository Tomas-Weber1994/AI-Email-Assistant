import logging
from typing import Any, TypedDict
from langchain_core.messages import AIMessage, ToolMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from app.utils.email_utils import get_headers, get_body

logger = logging.getLogger(__name__)


class RuntimeConfig(TypedDict):
    email: Any
    llm: Any
    thread_id: str | None


def get_runtime_config(config: RunnableConfig) -> RuntimeConfig:
    """Extracts services from LangGraph runnable config."""
    configurable = config["configurable"]
    return {
        "email": configurable["email"],
        "llm": configurable["llm"],
        "thread_id": configurable.get("thread_id"),
    }


def extract_email_parts(raw_msg: dict) -> tuple[str, str, str]:
    """Returns (sender, subject, body) from a raw Gmail message dict."""
    headers = get_headers(raw_msg)
    sender = raw_msg.get("from") or headers.get("From", "unknown")
    subject = raw_msg.get("subject") or headers.get("Subject", "")
    body = raw_msg.get("body") or get_body(raw_msg)
    return sender, subject, body


def sanitize_messages_for_openai(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Ensures valid sequence of AIMessage/ToolMessage for LLM providers."""
    sanitized: list[BaseMessage] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if isinstance(msg, AIMessage):
            tool_calls = getattr(msg, "tool_calls", []) or []
            if not tool_calls:
                sanitized.append(msg)
                i += 1
                continue

            pending_ids = {tc.get("id") for tc in tool_calls if tc.get("id")}
            collected_tools: list[ToolMessage] = []
            j = i + 1
            while j < len(messages):
                next_msg = messages[j]
                if not isinstance(next_msg, ToolMessage): break
                if next_msg.tool_call_id in pending_ids:
                    pending_ids.remove(next_msg.tool_call_id)
                    collected_tools.append(next_msg)
                j += 1
            if not pending_ids:
                sanitized.append(msg)
                sanitized.extend(collected_tools)
            i = j
        else:
            if not isinstance(msg, ToolMessage):
                sanitized.append(msg)
            i += 1
    return sanitized
