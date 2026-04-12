from unittest.mock import patch

from app.settings import settings
from app.workflows.tools import get_tool_sets


def _tool_names(tools):
    return {tool.name for tool in tools}


def test_sales_reply_is_safe_when_approval_is_disabled():
    with patch.object(settings, "SALES_REPLY_REQUIRES_APPROVAL", False):
        safe_tools, sensitive_tools = get_tool_sets()

    assert "send_reply" in _tool_names(safe_tools)
    assert "send_reply" not in _tool_names(sensitive_tools)


def test_sales_reply_is_sensitive_when_approval_is_enabled():
    with patch.object(settings, "SALES_REPLY_REQUIRES_APPROVAL", True):
        safe_tools, sensitive_tools = get_tool_sets()

    assert "send_reply" not in _tool_names(safe_tools)
    assert "send_reply" in _tool_names(sensitive_tools)

