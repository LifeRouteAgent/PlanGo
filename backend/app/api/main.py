from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import export, trip


app = FastAPI(title="LifeRouteAgent API", version="0.1.0")
app.include_router(trip.router)
app.include_router(export.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def run_once(user_query: str) -> dict:
    from app.dag.langgraph_dag_config import life_route_graph
    from app.state.plan_state import create_initial_state

    return life_route_graph.invoke(create_initial_state(user_query))


if __name__ == "__main__":
    result = run_once("周末和朋友出去玩 4 个小时，想吃饭看电影，预算 600 元")
    print(result["response_text"])
