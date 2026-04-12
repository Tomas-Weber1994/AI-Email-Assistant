from typing import cast

from app.workflows.nodes import ingest_node
from app.workflows.state import EmailAgentState


class DummyEmailService:
    def __init__(self):
        self.modified = []
        self.raw_message = {
            "payload": {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "Subject", "value": "Quarterly planning"},
                    {"name": "From", "value": "ceo@example.com"},
                ],
                "body": {"data": "SGVsbG8gdGVhbSw="},
            },
            "snippet": "Hello team,",
        }

    def get_message(self, email_id: str):
        assert email_id == "msg-1"
        return self.raw_message

    def modify_labels(self, email_id: str, add=None, remove=None):
        self.modified.append({"email_id": email_id, "add": add, "remove": remove})


def test_ingest_node_extracts_headers_and_body_for_llm():
    email_service = DummyEmailService()
    result = ingest_node(
        cast(EmailAgentState, {"email_id": "msg-1"}),
        {"configurable": {"email": email_service}},
    )

    assert result["raw_content"] == email_service.raw_message
    assert result["status"] == "processing"
    assert result["messages"][0].content == (
        "Subject: Quarterly planning\n"
        "From: ceo@example.com\n"
        "Body: Hello team,"
    )
    assert email_service.modified == [
        {"email_id": "msg-1", "add": None, "remove": ["UNREAD"]}
    ]


