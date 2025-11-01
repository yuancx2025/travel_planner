# workflow/travel_graph.py
from langgraph.graph import StateGraph, END
from agents.state import TravelState

# This is an example of building a travel planning workflow graph.
def build_graph(chatter, planner, researcher, constraint, enforcer, budget, quality):
    builder = StateGraph(TravelState)
    builder.add_node("chatter", chatter.run)
    builder.add_node("planner", planner.run)
    builder.add_node("researcher", researcher.run)
    builder.add_node("constraint", constraint.run)
    builder.add_node("enforcer", enforcer.run)
    builder.add_node("budget", budget.run)
    builder.add_node("quality", quality.run)

    builder.set_entry_point("chatter")
    builder.add_edge("chatter", "planner")
    builder.add_edge("planner", "researcher")
    builder.add_edge("researcher", "constraint")
    builder.add_conditional_edges("constraint", lambda state: state["next_agent"], {
        "enforcer": "enforcer",
        "budget": "budget",
    })
    builder.add_edge("enforcer", "researcher")  # Re-plan after fixes
    builder.add_edge("budget", "quality")
    builder.add_edge("quality", END)
    return builder.compile()
