from operator import add
from typing import Annotated, TypedDict, Literal, NotRequired
from langchain_core.messages import BaseMessage


class EmailAgentState(TypedDict):
    """
    Single source of truth pro LangGraph.
    Využívá historii zpráv pro rozhodování agenta.
    """
    # Identifikace
    email_id: str

    # Historie komunikace (včetně tool calls a jejich výsledků)
    # Annotated + add zajistí, že se nové zprávy připisují k existujícím
    messages: Annotated[list[BaseMessage], add]

    # Surová data pro potřeby toolů (např. odeslání reply vyžaduje original headers)
    raw_content: dict

    # Status pro API/Frontend (processing, waiting_approval, completed, error)
    status: Literal["processing", "waiting_approval", "completed", "error"]

    # Strukturovaný audit log pro finální report
    audit_log: Annotated[list[str], add]

    # Rozhodnutí ze schvalování (nastaveno při resume)
    approval_decision: NotRequired[Literal["APPROVE", "REJECT"]]

    # Marker, že během workflow už byl odeslán approval request
    approval_requested: NotRequired[bool]

    # Počet průchodů analyze uzlem (ochrana proti tool-loopu)
    analyze_passes: NotRequired[int]

