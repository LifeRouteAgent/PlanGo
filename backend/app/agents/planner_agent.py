from __future__ import annotations

from app.agents.llm_understanding import get_llm_understanding
from app.agents.issue_utils import issue_codes
from app.state.plan_state import PlanState, PlanStatePatch
from app.tools.poi_schema import (
    POI_ACTIVITY,
    POI_ATTRACTION,
    POI_BEAUTY,
    POI_ENTERTAINMENT,
    POI_FITNESS,
    POI_RESTAURANT,
    POI_SHOPPING,
)
from app.tools.skill_registry import (
    SKILL_REGISTRY,
    collector_categories_for_skills,
    select_skills_for_plan,
)


def planner_agent_node(state: PlanState) -> PlanStatePatch:
    """主控 Planner Agent 节点。

    Gate 2 开始，Planner 不再只决定“查哪些类别”，而是生成本地生活规划模板：
    - planning_template：本次任务属于吃饭、聚会、亲子、放松等哪种模板。
    - required_slots：后续路线规划需要填充的时间线槽位。
    - movement_policy：本地短途场景下的移动策略，比如低移动、同商圈优先。
    - candidate_strategy：候选组合策略，比如同商圈优先、类别聚焦、放宽类别。
    """

    constraints = state.get("constraints", {})
    llm_understanding = get_llm_understanding(state)
    preferences = constraints.get("preferences") or ["活动", "餐厅", "休闲娱乐"]
    # 单类推荐/地点查询由 Intent Router 指定目标类别；完整行程才根据偏好扩展类别。
    categories = state.get("target_categories") or _categories_for_preferences(preferences)
    llm_dag_plan = _llm_dag_plan(llm_understanding)
    planning_template = (
        llm_dag_plan.get("planning_template")
        or (
            llm_understanding.get("planning_template")
            if llm_understanding and llm_understanding.get("planning_template")
            else ""
        )
        or _select_planning_template(state, preferences, categories)
    )
    required_slots = (
        llm_dag_plan.get("slot_sequence")
        or (
            llm_understanding.get("required_slots")
            if llm_understanding and llm_understanding.get("required_slots")
            else []
        )
        or _required_slots_for_template(planning_template, categories)
    )
    time_budget = int(float(constraints.get("duration_hours", 10))) * 60
    movement_policy = (
        llm_dag_plan.get("movement_policy")
        or _movement_policy_for_state(state, planning_template, time_budget)
    )
    candidate_strategy = (
        llm_dag_plan.get("candidate_strategy")
        or _candidate_strategy_for_template(planning_template)
    )
    replanning_count = state.get("replanning_count", 0) + 1
    last_errors = issue_codes(state.get("errors", []))

    # Verifier 回退后，Planner 会收紧部分约束，避免重复生成同样失败的候选方案。
    # 这里先实现可观察的最小策略：路线超时则降低路线阈值压力；总时长超出则减少活动组合强度。
    retry_policy = "initial_plan"
    if replanning_count > 1:
        if "candidate_empty" in last_errors:
            retry_policy = "broaden_categories"
            categories = sorted(set(categories) | {POI_SHOPPING, POI_ENTERTAINMENT})
            candidate_strategy = "broaden_categories"
        elif "restaurant_unavailable" in last_errors:
            retry_policy = "prefer_non_restaurant_backup"
            candidate_strategy = "replace_restaurant_or_delay_meal"
        elif "budget_exceeded" in last_errors:
            retry_policy = "lower_price_level"
            candidate_strategy = "budget_fit_first"
        elif "reservation_required" in last_errors:
            retry_policy = "add_reservation_backup"
            candidate_strategy = "reservation_backup_first"
        elif "weak_preference_match" in last_errors:
            retry_policy = "tighten_preference_match"
            candidate_strategy = "preference_fit_first"
        elif "route_timeout" in last_errors or "total_duration_exceeded" in last_errors:
            retry_policy = "compact_timeline"
            movement_policy = "same_business_area_first"
            candidate_strategy = "compact_slots_same_area_first"

    enabled_skills = _valid_enabled_skills(llm_dag_plan.get("enabled_skills"))
    if not enabled_skills:
        enabled_skills = select_skills_for_plan(
            intent_type=state.get("intent_type", "full_trip_plan"),
            categories=categories,
            required_slots=required_slots,
            planning_template=planning_template,
        )
    collector_categories = [
        category
        for category in llm_dag_plan.get("collector_categories", [])
        if category in {
            POI_ACTIVITY,
            POI_ATTRACTION,
            POI_BEAUTY,
            POI_ENTERTAINMENT,
            POI_FITNESS,
            POI_RESTAURANT,
            POI_SHOPPING,
        }
    ]
    if not collector_categories:
        collector_categories = collector_categories_for_skills(enabled_skills, categories)

    return {
        "dag_plan": {
            "collector_categories": collector_categories,
            "planning_template": planning_template,
            "required_slots": required_slots,
            "slot_sequence": required_slots,
            "time_budget": time_budget,
            "movement_policy": movement_policy,
            "candidate_strategy": candidate_strategy,
            "enabled_skills": enabled_skills,
            "parallel_skills": enabled_skills,
            "feedback_policy": "verifier_failed_then_replan",
            "retry_policy": retry_policy,
        },
        "replanning_count": replanning_count,
        # 每次重新规划都开启一个新的尝试轮次，清空上一轮的失败结果。
        # Planner 已经在上方读取了旧 errors 并转成 retry_policy，因此这里可以安全清空。
        "errors": [],
        "candidate_plans": [],
        "verified_plans": [],
        "routes": [],
        "logs": [
            "Planner Agent: "
            + (
                "used LLM dag_plan, "
                if llm_dag_plan
                else ("used LLM template, " if llm_understanding else "used rule fallback, ")
            )
            + f"template={planning_template}, slots={','.join(required_slots)}, "
            + f"categories={','.join(collector_categories)}, "
            + f"enabled_skills={','.join(enabled_skills)}, movement_policy={movement_policy}, "
            + f"retry_policy={retry_policy}"
        ],
    }


def _llm_dag_plan(llm_understanding: dict | None) -> dict:
    """读取并返回已由 Intent LLM 生成且通过白名单清洗的 DAG Plan。"""

    if not isinstance(llm_understanding, dict):
        return {}
    dag_plan = llm_understanding.get("dag_plan")
    return dag_plan if isinstance(dag_plan, dict) else {}


def _valid_enabled_skills(skills: object) -> list[str]:
    """过滤 LLM 输出的 Skill 名称，只允许注册表内的节点进入 LangGraph。"""

    if not isinstance(skills, list):
        return []
    return [str(item) for item in skills if str(item) in SKILL_REGISTRY]


def _categories_for_preferences(preferences: list[str]) -> list[str]:
    """根据用户偏好选择七张 POI 表中的必要类别。"""

    categories = {POI_ATTRACTION, POI_ACTIVITY, POI_RESTAURANT}
    if any(item in preferences for item in ("休闲娱乐", "健身", "美容养生", "购物")):
        categories.update({
            POI_SHOPPING,
            POI_FITNESS,
            POI_ENTERTAINMENT,
            POI_BEAUTY,
        })
    return sorted(categories)


def _select_planning_template(
    state: PlanState,
    preferences: list[str],
    categories: list[str],
) -> str:
    """根据场景、偏好和目标类别选择本地生活规划模板。

    模板是后续路线和时间规划的“骨架”。例如同样是餐厅，`meal_only`
    只需要推荐吃饭地点，而 `friends_gathering` 会倾向组合餐厅和娱乐活动。
    """

    intent_type = state.get("intent_type", "full_trip_plan")
    if intent_type in {"category_recommend", "poi_search"}:
        return "category_recommendation"

    scenario = state.get("constraints", {}).get("scenario", "unknown")
    preference_text = " ".join(preferences)
    category_set = set(categories)

    if scenario == "family":
        return "family_half_day"
    if scenario == "couple":
        return "couple_date"
    if POI_BEAUTY in category_set or any(
        word in preference_text for word in ("美容养生", "按摩", "养生")
    ):
        return "relaxation"
    if POI_SHOPPING in category_set and not ({POI_ACTIVITY, POI_ENTERTAINMENT} & category_set):
        return "shopping_leisure"
    if category_set == {POI_ENTERTAINMENT}:
        return "entertainment_gathering"
    if category_set == {POI_RESTAURANT} or preferences == ["餐厅"]:
        return "meal_only"
    if scenario == "friends":
        return "friends_gathering"
    if POI_RESTAURANT in category_set and (
        {POI_ACTIVITY, POI_ENTERTAINMENT, POI_ATTRACTION} & category_set
    ):
        return "meal_plus_activity"
    return "meal_plus_activity"


def _required_slots_for_template(planning_template: str, categories: list[str]) -> list[str]:
    """把规划模板转成 Route Planner 可消费的时间线槽位。

    槽位只描述业务角色，不绑定具体 POI。具体 POI 由后续 Skill 和 Route Planner 填充。
    """

    if planning_template == "category_recommendation":
        return [_slot_for_category(category) for category in categories]
    template_slots = {
        "meal_only": ["restaurant"],
        "meal_plus_activity": ["activity", "restaurant"],
        "family_half_day": ["family_activity", "restaurant", "optional_shopping"],
        "friends_gathering": ["activity_or_entertainment", "restaurant", "optional_lifestyle"],
        "entertainment_gathering": ["entertainment", "optional_entertainment"],
        "couple_date": ["activity", "restaurant", "cafe_or_walk"],
        "relaxation": ["lifestyle", "restaurant_or_tea", "optional_shopping"],
        "shopping_leisure": ["shopping", "restaurant", "optional_entertainment"],
    }
    return template_slots.get(planning_template, ["activity", "restaurant"])


def _slot_for_category(category: str) -> str:
    """把统一 POI 类别映射成规划槽位名称。"""

    return {
        POI_RESTAURANT: "restaurant",
        POI_ACTIVITY: "activity",
        POI_ATTRACTION: "attraction",
        POI_SHOPPING: "shopping",
        POI_FITNESS: "fitness",
        POI_ENTERTAINMENT: "entertainment",
        POI_BEAUTY: "lifestyle",
    }.get(category, "poi")


def _movement_policy_for_state(
    state: PlanState,
    planning_template: str,
    time_budget: int,
) -> str:
    """选择本地生活场景的移动策略。

    本地生活规划对移动成本很敏感，短时间窗口和亲子/放松场景都应该减少跨区移动。
    """

    constraints = state.get("constraints", {})
    scenario = constraints.get("scenario", "unknown")
    if constraints.get("movement_policy"):
        return str(constraints["movement_policy"])
    if constraints.get("max_route_minutes_source") == "user" or time_budget <= 240:
        return "compact_walk_or_taxi"
    if scenario == "family" or planning_template in {
        "family_half_day",
        "relaxation",
        "shopping_leisure",
    }:
        return "low_movement"
    return "balanced_local"


def _candidate_strategy_for_template(planning_template: str) -> str:
    """为 Collector + Skill + Route Planner 提供候选组合策略。"""

    if planning_template in {"family_half_day", "shopping_leisure"}:
        return "same_business_area_first"
    if planning_template == "meal_only":
        return "restaurant_fit_first"
    if planning_template == "relaxation":
        return "slow_pace_reservation_first"
    if planning_template == "category_recommendation":
        return "category_focus"
    return "slot_balance"
