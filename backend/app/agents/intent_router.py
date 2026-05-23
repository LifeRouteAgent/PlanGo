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
    (POI_RESTAURANT, ("餐厅", "吃饭", "美食", "火锅", "咖啡", "饭店", "轻食", "下午茶", "晚餐", "午餐", "夜宵")),
    (POI_ACTIVITY, ("活动", "体验", "展览", "票券", "博物馆", "手作", "演出", "亲子活动", "体验课")),
    (POI_ENTERTAINMENT, ("电影", "影院", "KTV", "ktv", "娱乐", "桌游", "棋牌", "麻将", "打牌", "唱歌", "K歌", "k歌", "密室", "剧本杀")),
    (POI_FITNESS, ("健身", "运动", "瑜伽", "普拉提", "羽毛球", "爬山", "攀岩", "游泳")),
    (POI_BEAUTY, ("按摩", "足疗", "美容", "养生", "洗浴", "SPA", "spa", "美甲", "护理")),
    (POI_SHOPPING, ("购物", "商场", "逛街", "生活广场", "商圈", "买东西")),
    (POI_ATTRACTION, ("景点", "公园", "citywalk", "城市漫步", "观光", "散步", "露营")),
)

CAPABILITY_KEYWORDS = (
    "你能做什么",
    "支持什么",
    "有什么功能",
    "怎么用",
    "如何使用",
    "使用说明",
    "项目能力",
)

MODEL_QA_KEYWORDS = (
    "你是什么模型",
    "你用的什么模型",
    "当前模型",
    "什么大模型",
    "模型是谁",
    "你是谁开发",
    "你是谁",
)

SIMPLE_QA_KEYWORDS = (
    "你好",
    "hello",
    "谢谢",
    "hi",
    "早上好",
    "晚上好",
)


def intent_router_node(state: PlanState) -> PlanStatePatch:
    """前置意图路由节点。

    大模型负责自然语言理解；规则负责兜底和护栏。模型身份、能力说明、普通问答这类请求
    不应该进入本地生活规划链路，因此先用硬规则拦截。
    """

    query = state["user_query"].strip()
    rule_intent_type = _detect_intent_type(query)
    rule_categories = _detect_target_categories(query)

    if _is_direct_answer_query(query, rule_intent_type):
        intent_type = rule_intent_type
        categories: list[str] = []
        constraints = state.get("constraints", {})
        logs = [f"Intent Router: direct rule intent_type={intent_type}"]
    else:
        llm_understanding = build_llm_understanding(query, state.get("user_profile", {}))
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
    """基于规则的轻量意图识别，用于 LLM 调用前护栏和失败时兜底。"""

    lowered = query.lower()
    if any(keyword in query for keyword in CAPABILITY_KEYWORDS):
        return "capability"
    if any(keyword in query for keyword in MODEL_QA_KEYWORDS) or any(
        keyword in lowered for keyword in SIMPLE_QA_KEYWORDS
    ):
        return "simple_qa"

    categories = _detect_target_categories(query)
    planning_keywords = (
        "规划",
        "行程",
        "路线",
        "安排",
        "周末",
        "一天",
        "半天",
        "上午",
        "下午",
        "晚上",
        "小时",
        "然后",
        "再去",
    )
    recommend_keywords = ("推荐", "找", "查", "附近", "有哪些", "来几个")
    action_keywords = ("吃", "玩", "逛", "唱", "打牌", "麻将", "棋牌", "看电影", "按摩", "运动")

    if any(keyword in query for keyword in planning_keywords) and (
        len(categories) >= 2 or any(keyword in query for keyword in action_keywords)
    ):
        return "full_trip_plan"
    if categories and any(keyword in query for keyword in recommend_keywords):
        return "category_recommend"
    if categories:
        return "poi_search"
    return "simple_qa"


def _is_direct_answer_query(query: str, rule_intent_type: str) -> bool:
    """判断是否应跳过 LLM 和规划链路，直接回答。

    只有能力说明、模型身份、寒暄感谢这类确定性问答才直接截断。其他被规则兜底成
    simple_qa 的模糊句子仍交给 LLM 判断，例如“朋友聚会 4 小时”可能其实是完整规划。
    """

    lowered = query.lower()
    return rule_intent_type == "capability" or any(
        keyword in query for keyword in MODEL_QA_KEYWORDS
    ) or any(keyword in lowered for keyword in SIMPLE_QA_KEYWORDS)


def _detect_target_categories(query: str) -> list[str]:
    """从用户输入中识别目标 POI 类别。"""

    categories: list[str] = []
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword in query for keyword in keywords):
            categories.append(category)
    return categories


def _guard_llm_intent(llm_intent_type: str, rule_intent_type: str) -> str:
    """给大模型意图增加确定性护栏。

    模型不能把明确的规划、推荐或 POI 查询降级成闲聊；规则直接命中的问答也不能被升级成规划。
    """

    if rule_intent_type == "capability":
        return rule_intent_type

    actionable_intents = {"category_recommend", "poi_search", "full_trip_plan"}
    if rule_intent_type in actionable_intents and llm_intent_type in {"simple_qa", "capability"}:
        return rule_intent_type
    if rule_intent_type == "full_trip_plan" and llm_intent_type in {
        "category_recommend",
        "poi_search",
    }:
        return "full_trip_plan"
    return llm_intent_type
