from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import compat, export, plans, trip

app = FastAPI(title="LifeRouteAgent API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(trip.router)
app.include_router(plans.router)
app.include_router(export.router)
app.include_router(compat.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def run_once(user_query: str) -> dict:
    from app.graph.graph_builder import run_planning_request
    from app.graph.state import planning_state_to_legacy

    return planning_state_to_legacy(run_planning_request(user_query))


if __name__ == "__main__":
    result = run_once("周末和朋友出去玩 4 个小时，想吃饭看电影，预算 600 元")
    print(result["response_text"])
