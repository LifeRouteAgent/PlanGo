from __future__ import annotations

from app.agents.llm_understanding import build_llm_understanding
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


CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (POI_RESTAURANT, ("餐厅", "吃饭", "美食", "火锅", "咖啡", "饭店", "轻食")),
    (POI_ACTIVITY, ("活动", "体验", "展览", "票券", "博物馆", "手作")),
    (POI_ENTERTAINMENT, ("电影", "影院", "KTV", "ktv", "娱乐", "桌游", "棋牌", "麻将", "打牌", "唱歌", "K歌", "k歌")),
    (POI_FITNESS, ("健身", "运动", "瑜伽", "普拉提")),
    (POI_BEAUTY, ("按摩", "足疗", "美容", "养生", "洗浴")),
    (POI_SHOPPING, ("购物", "商场", "逛街", "生活广场")),
    (POI_ATTRACTION, ("景点", "公园", "citywalk", "城市漫步", "观光")),
)


def intent_router_node(state: PlanState) -> PlanStatePatch:
    """前置意图路由节点。

    该节点解决“不是每次都要完整行程规划”的问题：
    - 用户问系统能力时，直接进入能力说明。
    - 用户只是简单问答时，直接生成轻量回答。
    - 用户只要求某一类推荐时，只走 Collector + Skill + Ranker。
    - 用户明确要安排一天/周末/路线/行程时，才走完整规划 DAG。
    """

    query = state["user_query"].strip()
    llm_understanding = build_llm_understanding(query, state.get("user_profile", {}))
    rule_intent_type = _detect_intent_type(query)
    rule_categories = _detect_target_categories(query)
    if llm_understanding:
        llm_intent_type = llm_understanding["intent_type"]
        intent_type = _guard_llm_intent(llm_intent_type, rule_intent_type)
        categories = llm_understanding.get("target_categories", []) or rule_categories
        constraints = {
            **state.get("constraints", {}),
            "llm_understanding": llm_understanding,
        }
        logs = [
            "Intent Router: used LLM understanding "
            f"intent_type={intent_type}, target_categories={','.join(categories) or 'none'}"
            + (f", guarded_from={llm_intent_type}" if intent_type != llm_intent_type else "")
        ]
    else:
        intent_type = rule_intent_type
        categories = rule_categories
        constraints = state.get("constraints", {})
        logs = [
            "Intent Router: used rule fallback "
            f"intent_type={intent_type}, target_categories={','.join(categories) or 'none'}"
        ]
    answer_mode = {
        "capability": "capability",
        "simple_qa": "simple_qa",
        "category_recommend": "category_recommend",
        "poi_search": "poi_search",
        "full_trip_plan": "trip_plan",
    }[intent_type]

    return {
        "constraints": constraints,
        "intent_type": intent_type,
        "target_categories": categories,
        "answer_mode": answer_mode,
        "logs": logs,
    }


def intent_router_route(state: PlanState) -> str:
    """LangGraph 条件边使用的路由函数。"""

    intent_type = state.get("intent_type", "full_trip_plan")
    if intent_type in {"capability", "simple_qa"}:
        return "direct_answer"
    if intent_type in {"category_recommend", "poi_search"}:
        return "recommend"
    return "full_plan"


def _detect_intent_type(query: str) -> str:
    """基于规则的轻量意图识别。

    后续如果接入 MiMo 或其他 LLM，只需要替换这里，不影响 DAG 结构。
    """

    if any(keyword in query for keyword in ("你能做什么", "支持什么", "有什么功能", "怎么用")):
        return "capability"
    if any(keyword in query for keyword in ("你好", "hello", "谢谢", "你是谁")):
        return "simple_qa"

    categories = _detect_target_categories(query)
    planning_keywords = ("规划", "行程", "路线", "安排", "周末", "一天", "半天", "上午", "下午", "晚上")
    recommend_keywords = ("推荐", "找", "查", "附近", "有哪些")

    if any(keyword in query for keyword in planning_keywords) and len(categories) >= 2:
        return "full_trip_plan"
    if any(keyword in query for keyword in planning_keywords) and any(
        keyword in query for keyword in ("吃", "玩", "逛", "唱", "打牌", "麻将", "棋牌")
    ):
        return "full_trip_plan"
    if categories and any(keyword in query for keyword in recommend_keywords):
        return "category_recommend"
    if categories:
        return "poi_search"
    return "simple_qa"


def _detect_target_categories(query: str) -> list[str]:
    """从用户输入中识别目标 POI 类别。"""

    categories: list[str] = []
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword in query for keyword in keywords):
            categories.append(category)
    return categories


def _guard_llm_intent(llm_intent_type: str, rule_intent_type: str) -> str:
    """给大模型意图增加确定性护栏。

    大模型负责理解自然语言，但不能把明显包含规划、推荐或 POI 类别的请求降级成闲聊。
    这层护栏只处理“降级错误”，不会把普通问答强行升级成规划。
    """

    actionable_intents = {"category_recommend", "poi_search", "full_trip_plan"}
    if rule_intent_type in actionable_intents and llm_intent_type in {"simple_qa", "capability"}:
        return rule_intent_type
    if rule_intent_type == "full_trip_plan" and llm_intent_type in {"category_recommend", "poi_search"}:
        return "full_trip_plan"
    return llm_intent_type
