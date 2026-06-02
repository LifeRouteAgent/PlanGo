from __future__ import annotations

from typing import Annotated, Any, NotRequired, TypedDict


def merge_dicts(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    """LangGraph 并行分支合并字典状态时使用的 reducer。

    多个 Skill 会并行写入 `recommended_pois` 的不同 key，不能用默认覆盖行为。
    这里采用浅合并：右侧分支覆盖同名 key，不同 key 保留。
    """

    merged: dict[str, Any] = {}
    if left:
        merged.update(left)
    if right:
        merged.update(right)
    return merged


def append_lists(left: list[Any] | None, right: list[Any] | None) -> list[Any]:
    """LangGraph 合并日志、错误和候选方案列表时使用的 reducer。"""

    return [*(left or []), *(right or [])]


def replace_list(left: list[Any] | None, right: list[Any] | None) -> list[Any]:
    """每轮规划结果使用覆盖语义，避免 Verifier 回退后旧方案污染新方案。"""

    return list(right or [])


class PlanState(TypedDict):
    """贯穿 LangGraph DAG 的全局状态对象。

    约定：每个节点只返回自己负责更新的字段，不直接修改入参对象。
    这样后续可以安全接入 checkpoint、trace 和人工 review。
    """

    user_query: str
    user_profile: dict[str, Any]
    constraints: dict[str, Any]
    candidate_pois: Annotated[dict[str, list[dict[str, Any]]], merge_dicts]
    recommended_pois: Annotated[dict[str, list[dict[str, Any]]], merge_dicts]
    routes: Annotated[list[dict[str, Any]], replace_list]
    candidate_plans: Annotated[list[dict[str, Any]], replace_list]
    verified_plans: Annotated[list[dict[str, Any]], replace_list]
    ranked_plans: list[dict[str, Any]]
    selected_plan: dict[str, Any]
    execution_status: str
    logs: Annotated[list[str], append_lists]
    errors: Annotated[list[dict[str, Any]], replace_list]
    response_text: str
    dag_plan: dict[str, Any]
    intent_type: str
    target_categories: list[str]
    answer_mode: str
    need_clarification: bool
    missing_constraints: Annotated[list[str], replace_list]
    clarify_question: str
    replanning_count: int
    max_replanning_count: int
    force_empty_candidates: bool
    force_restaurant_unavailable: bool
    force_route_timeout: bool
    force_duration_exceeded: bool
    session_id: str
    trace_id: str
    run_id: str
    revision_id: str
    is_revision: bool
    task_id: str
    tool_evidence: Annotated[list[dict[str, Any]], append_lists]
    booking_actions: Annotated[list[dict[str, Any]], append_lists]


class PlanStatePatch(TypedDict, total=False):
    """节点返回的局部状态补丁。

    LangGraph 会把补丁合并回 PlanState；列表和字典字段通过上面的 reducer 合并。
    """

    user_query: str
    user_profile: dict[str, Any]
    constraints: dict[str, Any]
    candidate_pois: dict[str, list[dict[str, Any]]]
    recommended_pois: dict[str, list[dict[str, Any]]]
    routes: list[dict[str, Any]]
    candidate_plans: list[dict[str, Any]]
    verified_plans: list[dict[str, Any]]
    ranked_plans: list[dict[str, Any]]
    selected_plan: dict[str, Any]
    execution_status: str
    logs: list[str]
    errors: list[dict[str, Any]]
    response_text: str
    dag_plan: dict[str, Any]
    intent_type: str
    target_categories: list[str]
    answer_mode: str
    need_clarification: bool
    missing_constraints: list[str]
    clarify_question: str
    replanning_count: int
    max_replanning_count: int
    force_empty_candidates: bool
    force_restaurant_unavailable: bool
    force_route_timeout: bool
    force_duration_exceeded: bool
    session_id: str
    trace_id: str
    run_id: str
    revision_id: str
    is_revision: bool
    task_id: str
    tool_evidence: list[dict[str, Any]]
    booking_actions: list[dict[str, Any]]


class PoiRecord(TypedDict):
    """Collector 层对外输出的统一 POI 字段。

    后续无论来自高德 CSV/JSONL、实时地图 API，还是人工精选库，都需要先映射为该结构。
    """

    id: str
    name: str
    category: str
    subcategory: str
    lat: float
    lon: float
    address: str
    rating: float
    price_level: str
    open_status: str
    tags: list[str]
    avg_price: NotRequired[float]
    image_url: NotRequired[str]
    images: NotRequired[list[str]]


class RecommendedPoiRecord(PoiRecord):
    """Skill 层对候选 POI 打分后的输出结构。

    这里不只保存推荐分数，还保存本地生活规划需要的可执行性字段。
    后续 Route Planner、Verifier 和 Ranker 都基于这些字段判断方案是否能落地。
    """

    score: float
    reason: str
    risk_flags: list[str]
    estimated_duration_minutes: int
    reservation_required: bool
    crowd_risk: str
    budget_fit: str
    scene_fit: float
    distance_sensitive: bool


def create_initial_state(
    user_query: str,
    *,
    user_profile: dict[str, Any] | None = None,
    max_replanning_count: int = 2,
    session_id: str = "",
    trace_id: str = "",
    run_id: str = "",
    revision_id: str = "",
    is_revision: bool = False,
    task_id: str = "",
) -> PlanState:
    """创建一次规划运行的初始状态。"""

    return {
        "user_query": user_query,
        "user_profile": user_profile or {},
        "constraints": {},
        "candidate_pois": {},
        "recommended_pois": {},
        "routes": [],
        "candidate_plans": [],
        "verified_plans": [],
        "ranked_plans": [],
        "selected_plan": {},
        "execution_status": "pending",
        "logs": [],
        "errors": [],
        "response_text": "",
        "dag_plan": {},
        "intent_type": "full_trip_plan",
        "target_categories": [],
        "answer_mode": "trip_plan",
        "need_clarification": False,
        "missing_constraints": [],
        "clarify_question": "",
        "replanning_count": 0,
        "max_replanning_count": max_replanning_count,
        # 以下 force_* 字段只用于测试和演示异常分支，不代表真实业务输入。
        "force_empty_candidates": (
            bool(user_profile.get("force_empty_candidates")) if user_profile else False
        ),
        "force_restaurant_unavailable": (
            bool(user_profile.get("force_restaurant_unavailable")) if user_profile else False
        ),
        "force_route_timeout": (
            bool(user_profile.get("force_route_timeout")) if user_profile else False
        ),
        "force_duration_exceeded": (
            bool(user_profile.get("force_duration_exceeded")) if user_profile else False
        ),
        "session_id": session_id,
        "trace_id": trace_id,
        "run_id": run_id,
        "revision_id": revision_id,
        "is_revision": is_revision,
        "task_id": task_id,
        "tool_evidence": [],
        "booking_actions": [],
    }
