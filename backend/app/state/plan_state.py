from __future__ import annotations

from typing import Annotated, Any, TypedDict


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
    errors: Annotated[list[str], replace_list]
    response_text: str
    dag_plan: dict[str, Any]
    replanning_count: int
    max_replanning_count: int
    force_empty_candidates: bool
    force_restaurant_unavailable: bool
    force_route_timeout: bool
    force_duration_exceeded: bool


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
    errors: list[str]
    response_text: str
    dag_plan: dict[str, Any]
    replanning_count: int
    max_replanning_count: int
    force_empty_candidates: bool
    force_restaurant_unavailable: bool
    force_route_timeout: bool
    force_duration_exceeded: bool


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


class RecommendedPoiRecord(PoiRecord):
    """Skill 层对候选 POI 打分后的输出结构。"""

    score: float
    reason: str
    risk_flags: list[str]


def create_initial_state(
    user_query: str,
    *,
    user_profile: dict[str, Any] | None = None,
    max_replanning_count: int = 2,
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
        "replanning_count": 0,
        "max_replanning_count": max_replanning_count,
        # 以下 force_* 字段只用于测试和演示异常分支，不代表真实业务输入。
        "force_empty_candidates": bool(user_profile.get("force_empty_candidates")) if user_profile else False,
        "force_restaurant_unavailable": bool(user_profile.get("force_restaurant_unavailable")) if user_profile else False,
        "force_route_timeout": bool(user_profile.get("force_route_timeout")) if user_profile else False,
        "force_duration_exceeded": bool(user_profile.get("force_duration_exceeded")) if user_profile else False,
    }
