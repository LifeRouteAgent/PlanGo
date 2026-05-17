from __future__ import annotations

from app.state.plan_state import PlanState, PlanStatePatch


def user_confirm_node(state: PlanState) -> PlanStatePatch:
    return {"logs": ["User Confirm: auto-confirmed for the minimal DAG run"]}


def execution_agent_node(state: PlanState) -> PlanStatePatch:
    status = "simulated" if state.get("selected_plan") else "skipped"
    return {
        "execution_status": status,
        "logs": [f"Execution Agent: execution_status={status}"],
    }
