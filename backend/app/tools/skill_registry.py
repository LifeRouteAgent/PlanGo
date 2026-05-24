from __future__ import annotations

from dataclasses import dataclass

from app.tools.poi_schema import (
    POI_ACTIVITY,
    POI_ATTRACTION,
    POI_BEAUTY,
    POI_ENTERTAINMENT,
    POI_FITNESS,
    POI_RESTAURANT,
    POI_SHOPPING,
)


@dataclass(frozen=True)
class SkillSpec:
    """本地生活推荐 Skill 的结构化能力描述。

    这份注册表是 Planner 选择 Skill 的唯一元数据来源。当前 Skill 仍是规则实现，
    但把 use_when / do_not_use_when / examples 写成结构化字段后，后续可以安全地
    注入 Planner LLM prompt，让大模型知道每个 Skill 的边界，而不是靠文件名猜。
    """

    name: str
    description: str
    use_when: tuple[str, ...]
    do_not_use_when: tuple[str, ...]
    input_categories: tuple[str, ...]
    output_key: str
    required_slots: tuple[str, ...]
    examples: tuple[str, ...]


SKILL_REGISTRY: dict[str, SkillSpec] = {
    "poi_mix_recommend": SkillSpec(
        name="poi_mix_recommend",
        description="景点、商场、城市漫步和低移动成本商圈容器推荐。",
        use_when=(
            "用户想逛街、citywalk、公园、景点、商场或需要饭前饭后轻休闲。",
            "规划模板需要 shopping、attraction、cafe_or_walk、optional_shopping 槽位。",
        ),
        do_not_use_when=("用户只要求餐厅、KTV、麻将、按摩等明确垂类，且不需要中转商圈。",),
        input_categories=(POI_ATTRACTION, POI_SHOPPING),
        output_key="mix",
        required_slots=("attraction", "shopping", "cafe_or_walk", "optional_shopping"),
        examples=("周末想逛街吃饭", "情侣 citywalk 后吃晚饭", "亲子半日室内商场方案"),
    ),
    "poi_activity_recommend": SkillSpec(
        name="poi_activity_recommend",
        description="展览、手作、票券、体验活动等有时间窗口的活动推荐。",
        use_when=(
            "用户提到展览、手作、体验、活动、票券、博物馆、演出。",
            "规划模板需要 activity 或 family_activity 槽位。",
        ),
        do_not_use_when=("用户只想找餐厅、KTV、按摩、麻将等非活动体验地点。",),
        input_categories=(POI_ACTIVITY,),
        output_key="activity",
        required_slots=("activity", "family_activity"),
        examples=("下午想看展再吃饭", "亲子手作体验", "周末找个活动玩两个小时"),
    ),
    "poi_restaurant_recommend": SkillSpec(
        name="poi_restaurant_recommend",
        description="餐厅、美食、咖啡、聚餐锚点推荐。",
        use_when=(
            "用户明确要吃饭、聚餐、火锅、咖啡、下午茶或方案里需要餐饮锚点。",
            "规划模板需要 restaurant、restaurant_or_tea 槽位。",
        ),
        do_not_use_when=("用户明确只要非餐饮单类推荐，且没有餐饮时间块。",),
        input_categories=(POI_RESTAURANT,),
        output_key="restaurant",
        required_slots=("restaurant", "restaurant_or_tea"),
        examples=("朋友聚餐后唱歌", "推荐附近餐厅", "按摩后找个轻食"),
    ),
    "poi_lifestyle_recommend": SkillSpec(
        name="poi_lifestyle_recommend",
        description="娱乐、健身、美容养生等本地生活方式推荐。",
        use_when=(
            "用户提到 KTV、麻将、棋牌、打牌、唱歌、桌游、密室、按摩、足疗、健身。",
            "规划模板需要 entertainment、lifestyle、optional_entertainment、optional_lifestyle 槽位。",
        ),
        do_not_use_when=("用户只需要景点、商场、餐厅或展览，不涉及娱乐/养生/运动。",),
        input_categories=(POI_FITNESS, POI_ENTERTAINMENT, POI_BEAUTY),
        output_key="lifestyle",
        required_slots=(
            "entertainment",
            "optional_entertainment",
            "lifestyle",
            "optional_lifestyle",
        ),
        examples=("打麻将再唱歌", "按摩放松后吃饭", "朋友约羽毛球再聚餐"),
    ),
}


CATEGORY_TO_SKILLS: dict[str, tuple[str, ...]] = {
    POI_ATTRACTION: ("poi_mix_recommend",),
    POI_SHOPPING: ("poi_mix_recommend",),
    POI_ACTIVITY: ("poi_activity_recommend",),
    POI_RESTAURANT: ("poi_restaurant_recommend",),
    POI_FITNESS: ("poi_lifestyle_recommend",),
    POI_ENTERTAINMENT: ("poi_lifestyle_recommend",),
    POI_BEAUTY: ("poi_lifestyle_recommend",),
}


def select_skills_for_plan(
    *,
    intent_type: str,
    categories: list[str],
    required_slots: list[str],
    planning_template: str,
) -> list[str]:
    """根据意图、目标类别和规划槽位选择本轮要执行的 Skill。

    单类推荐只启用目标类别直接对应的 Skill；完整规划则同时考虑目标类别、模板槽位和
    常见本地生活模板的隐含需求，避免固定把四个 Skill 全部跑一遍。
    """

    selected: set[str] = set()
    for category in categories:
        selected.update(CATEGORY_TO_SKILLS.get(category, ()))

    if intent_type in {"category_recommend", "poi_search"}:
        return _ordered_skills(selected)

    slot_set = set(required_slots)
    for skill_name, spec in SKILL_REGISTRY.items():
        if slot_set & set(spec.required_slots):
            selected.add(skill_name)

    template_defaults = {
        "meal_only": {"poi_restaurant_recommend"},
        "meal_plus_activity": {"poi_activity_recommend", "poi_restaurant_recommend"},
        "family_half_day": {
            "poi_activity_recommend",
            "poi_restaurant_recommend",
            "poi_mix_recommend",
        },
        "friends_gathering": {
            "poi_lifestyle_recommend",
            "poi_restaurant_recommend",
            "poi_activity_recommend",
        },
        "entertainment_gathering": {"poi_lifestyle_recommend"},
        "couple_date": {"poi_activity_recommend", "poi_restaurant_recommend", "poi_mix_recommend"},
        "relaxation": {"poi_lifestyle_recommend", "poi_restaurant_recommend", "poi_mix_recommend"},
        "shopping_leisure": {
            "poi_mix_recommend",
            "poi_restaurant_recommend",
            "poi_lifestyle_recommend",
        },
    }
    selected.update(template_defaults.get(planning_template, set()))

    # 完整规划至少要有一个 Skill，否则后续 Collector / Route Planner 没有候选来源。
    if not selected:
        selected.add("poi_activity_recommend")

    return _ordered_skills(selected)


def collector_categories_for_skills(
    enabled_skills: list[str],
    requested_categories: list[str],
) -> list[str]:
    """根据已启用 Skill 反推 Collector 需要读取的 POI 类别。

    如果用户已经明确了目标类别，只读取这些类别和 Skill 输入类别的交集，避免比如
    “只想唱歌”时把健身、美容也查出来。没有明确类别时，使用 Skill 声明的默认输入类别。
    """

    requested = set(requested_categories)
    categories: set[str] = set()
    for skill_name in enabled_skills:
        spec = SKILL_REGISTRY.get(skill_name)
        if not spec:
            continue
        inputs = set(spec.input_categories)
        if requested:
            categories.update(inputs & requested)
        else:
            categories.update(inputs)
    if requested_categories:
        ordered = [category for category in requested_categories if category in categories]
        extras = sorted(category for category in categories if category not in set(ordered))
        return [*ordered, *extras]
    return sorted(categories)


def skill_enabled(state: dict, skill_name: str) -> bool:
    """判断当前 DAG 计划是否启用某个 Skill。

    为了兼容已有单元测试和直接函数调用：如果 dag_plan 没有 enabled_skills 字段，则认为
    Skill 启用；只有 Planner 明确写入 enabled_skills 后才执行选择性跳过。
    """

    dag_plan = state.get("dag_plan", {})
    enabled_skills = dag_plan.get("enabled_skills")
    if not enabled_skills:
        return True
    return skill_name in set(enabled_skills)


def skipped_skill_patch(skill_name: str) -> dict:
    """返回未启用 Skill 的标准跳过日志补丁。"""

    return {"logs": [f"Skill {skill_name}: skipped because planner did not enable it"]}


def _ordered_skills(skills: set[str]) -> list[str]:
    """按注册表顺序稳定输出 Skill 名称，避免日志和测试因集合顺序波动。"""

    return [skill_name for skill_name in SKILL_REGISTRY if skill_name in skills]
