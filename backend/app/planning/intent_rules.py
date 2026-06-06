from __future__ import annotations

from app.domain.poi import (
    POI_ACTIVITY,
    POI_ATTRACTION,
    POI_BEAUTY,
    POI_ENTERTAINMENT,
    POI_FITNESS,
    POI_RESTAURANT,
    POI_SHOPPING,
)


CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        POI_RESTAURANT,
        ("餐厅", "吃饭", "美食", "火锅", "咖啡", "饭店", "轻食", "下午茶", "晚餐", "午餐", "夜宵"),
    ),
    (
        POI_ACTIVITY,
        ("活动", "体验", "展览", "票券", "博物馆", "手作", "演出", "亲子活动", "体验课"),
    ),
    (
        POI_ENTERTAINMENT,
        (
            "电影",
            "影院",
            "KTV",
            "ktv",
            "娱乐",
            "桌游",
            "棋牌",
            "麻将",
            "打牌",
            "唱歌",
            "K歌",
            "k歌",
            "密室",
            "剧本杀",
        ),
    ),
    (POI_FITNESS, ("健身", "运动", "瑜伽", "普拉提", "羽毛球", "爬山", "攀岩", "游泳")),
    (POI_BEAUTY, ("按摩", "足疗", "美容", "养生", "洗浴", "SPA", "spa", "美甲", "护理")),
    (POI_SHOPPING, ("购物", "商场", "逛街", "生活广场", "商圈", "买东西")),
    (
        POI_ATTRACTION,
        (
            "环球影城",
            "景点",
            "乐园",
            "主题公园",
            "公园",
            "citywalk",
            "城市漫步",
            "观光",
            "散步",
            "露营",
        ),
    ),
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
SIMPLE_QA_KEYWORDS = ("你好", "hello", "谢谢", "hi", "早上好", "晚上好")


def detect_intent_type(query: str) -> str:
    """确定性意图兜底规则。

    这部分属于 graph/service 的护栏，不是 LLM agent。LLM 不可用或误判时，
    V2 用它保证明显的推荐/规划请求不会被降级成闲聊。
    """

    lowered = query.lower()
    if _looks_like_full_plan_zh(query):
        return "full_trip_plan"
    if any(keyword in query for keyword in CAPABILITY_KEYWORDS):
        return "capability"
    if any(keyword in query for keyword in MODEL_QA_KEYWORDS) or any(
        keyword in lowered for keyword in SIMPLE_QA_KEYWORDS
    ):
        return "simple_qa"

    categories = detect_target_categories(query)
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


def detect_target_categories(query: str) -> list[str]:
    """从用户输入中识别目标 POI 类别，输出仍使用受控 POI 类型。"""

    categories: list[str] = []
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword in query for keyword in keywords):
            categories.append(category)
    return list(dict.fromkeys(categories))


def _looks_like_full_plan_zh(query: str) -> bool:
    has_time = any(
        keyword in query
        for keyword in ("明天", "今天", "周末", "周六", "周日", "上午", "下午", "晚上")
    )
    has_company = any(
        keyword in query for keyword in ("对象", "情侣", "女朋友", "男朋友", "朋友", "家人", "同事")
    )
    has_actions = sum(
        1
        for keyword in ("环球影城", "唱歌", "看电影", "吃饭", "逛街", "按摩", "打牌", "麻将")
        if keyword in query
    )
    asks_plan = any(keyword in query for keyword in ("规划", "安排", "行程", "帮我"))
    return asks_plan and has_time and (has_company or has_actions >= 2)
