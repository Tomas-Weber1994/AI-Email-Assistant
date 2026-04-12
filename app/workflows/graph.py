from typing import Literal

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, ToolMessage

from app.workflows.state import EmailAgentState
from app.workflows.nodes import ingest_node, classify_node, ask_approval_node, cleanup_node, analyze_node
from app.workflows.tools import get_all_tools, get_sensitive_tool_names


# --- ROUTING LOGIC (Srdce grafu kombinující V1 a V2) ---

def routing_logic(state: EmailAgentState) -> Literal["tools", "ask_approval", "cleanup"]:
    """
    Rozhoduje o dalším kroku na základě klasifikace, historie zpráv a provedených akcí.
    Implementuje striktní pravidla pro Human-in-the-loop a zamezuje zacyklení.
    """
    classification = state.get("classification")
    messages = state.get("messages", [])

    if not classification or state.get("status") == "error":
        return "cleanup"

    # --- 1. POJISTKA PROTI ZACYKLENÍ ---
    # Pokud poslední zpráva v historii je potvrzení o archivaci, workflow končí.
    if messages:
        last_msg = messages[-1]
        if isinstance(last_msg, ToolMessage) and (
            "Archived with labels" in last_msg.content or "Moved to SPAM" in last_msg.content
        ):
            return "cleanup"

    # --- 2. VYHODNOCENÍ LIDSKÉHO ROZHODNUTÍ (Approval/Reject) ---
    # Najdeme poslední zprávu od člověka v historii.
    last_human_msg = next((m for m in reversed(messages) if isinstance(m, HumanMessage)), None)

    # Pokud manažer zamítl (REJECT), jdeme rovnou do cleanup (zápis logu a konec).
    if last_human_msg and "REJECT" in last_human_msg.content.upper():
        return "cleanup"

    # Prověříme, zda máme schválení (APPROVE).
    has_approval = last_human_msg and "APPROVE" in last_human_msg.content.upper()

    # --- 3. KONTROLA NÁSTROJŮ ---
    # Podíváme se, co AI navrhla v poslední zprávě.
    last_ai_msg = next((m for m in reversed(messages) if hasattr(m, "tool_calls")), None)

    if not last_ai_msg:
        return "cleanup"

    tool_calls = getattr(last_ai_msg, "tool_calls", [])

    # SPAM, MARKETING a INFO_ONLY (pokud není urgentní) jdou na tools jen s validním tool_call.
    if classification.label in ["SPAM", "MARKETING", "INFO_ONLY"] and not classification.is_urgent:
        return "tools" if tool_calls else "cleanup"

    if not tool_calls:
        return "cleanup"

    sensitive_tools = get_sensitive_tool_names()
    requires_approval = any(tc["name"] in sensitive_tools for tc in tool_calls)

    # Pokud nástroj vyžaduje schválení a my ho ještě nemáme, jdeme do approval uzlu.
    if requires_approval and not has_approval:
        return "ask_approval"


    # Ve všech ostatních případech (buď není schválení potřeba, nebo už bylo uděleno) jdeme na tools.
    return "tools"


# --- KONSTRUKCE KOMPLETNÍHO GRAFU ---

def create_email_graph(checkpointer):
    workflow = StateGraph(EmailAgentState)

    # Přidání uzlů
    workflow.add_node("ingest", ingest_node)  # Stažení emailu [cite: 6]
    workflow.add_node("classify", classify_node)  # LLM klasifikace [cite: 11]
    workflow.add_node("analyze", analyze_node)  # Návrh tool_calls [cite: 15]
    workflow.add_node("tools", ToolNode(get_all_tools()))  # Provedení akcí [cite: 13]
    workflow.add_node("ask_approval", ask_approval_node)  # Email manažerovi [cite: 17, 21]
    workflow.add_node("cleanup", cleanup_node)  # Audit log a ukončení

    # Definice hran (Workflow)
    workflow.set_entry_point("ingest")

    workflow.add_edge("ingest", "classify")
    workflow.add_edge("classify", "analyze")

    # Hlavní rozhodovací bod po analýze
    workflow.add_conditional_edges(
        "analyze",
        routing_logic,
        {
            "tools": "tools",
            "ask_approval": "ask_approval",
            "cleanup": "cleanup"
        }
    )

    # Po schválení se vracíme do analýzy (aby model mohl potvrdit tool_call)
    # Nebo lze jít přímo do tools, pokud routing_logic po APPROVE vrátí 'tools'
    # NEBO??? workflow.add_edge("ask_approval", END)  # Přerušení běhu (čekání na externí event/resume)
    workflow.add_edge("ask_approval", "analyze")

    # Po vykonání nástrojů se vracíme na analýzu pro kontrolu výsledku nebo další krok
    workflow.add_edge("tools", "analyze")

    # Cleanup je konečná stanice
    workflow.add_edge("cleanup", END)

    # Kompilace s přerušením pro Human-in-the-loop 
    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_after=["ask_approval"]
    )
