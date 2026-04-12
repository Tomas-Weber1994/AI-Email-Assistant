from typing import Literal, Any, cast
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import AIMessage

from app.workflows.state import EmailAgentState
from app.workflows.nodes import ingest_node, analyze_node, cleanup_node
from app.workflows.tools import get_all_tools, get_sensitive_tool_names


def router(state: EmailAgentState) -> Literal["tools", "ask_approval", "cleanup"]:
    if state.get("status") == "error":
        return "cleanup"

    last_msg = state["messages"][-1]
    decision = state.get("approval_decision")

    # 1. Pokud model poslal tool_call a máme schváleno -> jdeme rovnou vykonat
    if isinstance(last_msg, AIMessage) and last_msg.tool_calls and decision in ["APPROVE", "REJECT"]:
        return "tools"

    # 2. POJISTKA: Pokud máme schváleno (APPROVE), ale model poslal jen text (tool_calls=[]),
    # nesmíme jít do cleanup! Musíme se vrátit do analyze, aby ho ten náš "kopanec"
    # v analyze_node donutil ten tool_call poslat.
    if decision == "APPROVE" and (not isinstance(last_msg, AIMessage) or not last_msg.tool_calls):
        # Tímto ho nepustíme do cleanupu, dokud ten kalendář skutečně nezavolá
        return "tools"  # Nebo ho nechat v analyze, ale tools je jistější cesta k exekuci

    # 3. Pokud model nic nenavrhl a nemáme APPROVE, tak teprve jdeme do cleanup
    if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
        return "cleanup"

    # 4. Standardní sensitive check
    sensitive_names = get_sensitive_tool_names()
    has_sensitive = any(tc["name"] in sensitive_names for tc in last_msg.tool_calls)

    if has_sensitive and not decision:
        return "ask_approval"

    return "tools"



def create_email_graph(checkpointer):
    workflow = StateGraph(cast(Any, EmailAgentState))

    # Definice uzlů
    workflow.add_node("ingest", cast(Any, ingest_node))
    workflow.add_node("analyze", cast(Any, analyze_node))

    # Jeden uzel pro všechny nástroje. LLM k němu má přístup buď hned (safe),
    # nebo po schválení (sensitive).
    workflow.add_node("tools", ToolNode(get_all_tools()))

    # Uzel, který se stará o logiku přerušení.
    # Může to být buď uzel volající interrupt(), nebo místo, kde se interruptuje předem.
    workflow.add_node("ask_approval", lambda state: {"status": "waiting_approval"})

    workflow.add_node("cleanup", cast(Any, cleanup_node))

    # Propojení grafu
    workflow.set_entry_point("ingest")
    workflow.add_edge("ingest", "analyze")

    # Podmíněné větvení z analýzy
    workflow.add_conditional_edges(
        "analyze",
        router,
        {
            "tools": "tools",
            "ask_approval": "ask_approval",
            "cleanup": "cleanup"
        }
    )

    # Po vykonání nástrojů se VŽDY vracíme do analyze.
    # LLM tak uvidí výsledek (např. "Event created" nebo "Conflict found") a může reagovat.
    workflow.add_edge("tools", "analyze")

    # Po odeslání žádosti o schválení se po resume vracíme do analyze.
    # Model uvidí zprávu od manažera a vygeneruje finální tool call.
    workflow.add_edge("ask_approval", "analyze")

    workflow.add_edge("cleanup", END)

    # KLÍČOVÝ BOD: Interruptujeme před uzlem ask_approval.
    # To umožní manažerovi odpovědět a my pak graf probudíme.
    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["ask_approval"]
    )

