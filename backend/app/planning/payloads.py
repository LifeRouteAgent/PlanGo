from __future__ import annotations

"""V2 返回前端的稳定契约。

这里不做召回、排序、路线等业务决策，只做最终响应的结构校验和展示字段清洗。
所有 graph 节点生成的 payload 在出图前都应经过这里，避免把数据库原始字段、
英文内部枚举、精确起点坐标或未清洗标签直接暴露给前端。
"""

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RAW_TAG_MARKERS = (
    "sub_category_id",
    "leaf_category_id",
    "category_id",
    "sub_category_name",
)
RAW_TAG_VALUES = {
    "activity",
    "attraction",
    "restaurant",
    "shopping",
    "entertainment",
    "fitness",
    "beauty",
    "cinema",
    "mixed",
}


class PayloadModel(BaseModel):
    """前端契约基类：禁止多余字段，避免内部临时字段无意透出。"""

    model_config = ConfigDict(extra="forbid")


class RoutePointPayload(PayloadModel):
    lat: float
    lng: float


class TimelineNodePayload(PayloadModel):
    # 时间轴允许展示 POI 坐标，但起点只展示“起点”，不回传用户精确位置。
    time_text: str = ""
    title: str
    description: str | None = None
    poi_id: str | None = None
    type: Literal["origin", "poi"] = "poi"
    source: str | None = None

    @model_validator(mode="after")
    def origin_is_generic(self) -> "TimelineNodePayload":
        if self.type == "origin":
            self.title = "起点"
            self.description = self.description or "出发起点"
            self.poi_id = None
        return self


class RouteSegmentPayload(PayloadModel):
    # 路线段是地图画线和交通文案的核心字段，字段名需要长期稳定。
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    from_id: str | None = None
    to_id: str | None = None
    from_item_id: str | None = None
    to_item_id: str | None = None
    from_type: Literal["origin", "poi"] = "poi"
    to_type: Literal["poi"] = "poi"
    distance_km: float | None = None
    duration_minutes: int | None = None
    transport_mode: str = "推荐交通"
    source: str = "unknown"
    polyline: list[RoutePointPayload] = Field(default_factory=list)

    @field_validator("transport_mode", mode="before")
    @classmethod
    def normalize_mode(cls, value: Any) -> str:
        return transport_mode_label(value)

    @model_validator(mode="after")
    def origin_label_is_generic(self) -> "RouteSegmentPayload":
        if self.from_type == "origin":
            self.from_ = "起点"
            self.from_id = self.from_id or "origin"
            self.from_item_id = self.from_item_id or "origin"
        return self


class PlanItemPayload(PayloadModel):
    # POI 卡片只保留前端展示所需字段，禁止把数据库整行或 raw_extra 带出去。
    id: str
    poi_id: str | None = None
    name: str
    category: str
    logical_category: str
    display_category: str | None = None
    subcategory: str | None = None
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    rating: float | None = None
    avg_price: float | None = None
    image_url: str | None = None
    images: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    reason: str = ""
    recommendation_reason: str | None = None
    score: float | None = None
    reservation_required: bool | None = None
    reservation_available: bool | None = None
    crowd_risk: str | None = None
    open_status: str | None = None
    risk_flags: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    start_time: str | None = None
    end_time: str | None = None

    @field_validator("tags", mode="before")
    @classmethod
    def clean_tags(cls, value: Any) -> list[str]:
        return clean_display_tags(value, fallback=["本地生活"], limit=8)

    @field_validator("images", mode="before")
    @classmethod
    def clean_images(cls, value: Any) -> list[str]:
        return clean_image_list(value)

    @field_validator("image_url", mode="before")
    @classmethod
    def clean_image(cls, value: Any) -> str | None:
        text = str(value or "").strip()
        return text if text.startswith(("http://", "https://")) else None

    @model_validator(mode="after")
    def fill_display_fields(self) -> "PlanItemPayload":
        self.display_category = self.display_category or category_label(self.logical_category)
        if not self.poi_id:
            self.poi_id = self.id
        if self.image_url and self.image_url not in self.images:
            self.images.insert(0, self.image_url)
        if not self.image_url and self.images:
            self.image_url = self.images[0]
        if not self.tags:
            self.tags = [self.display_category]
        return self


class PlanCardPayload(PayloadModel):
    # 方案卡片字段同时服务列表预览和详情页，标题/优缺点/亮点都必须是短展示文案。
    id: str
    plan_id: str
    title: str
    subtitle: str | None = None
    tags: list[str] = Field(default_factory=list)
    highlight_tags: list[str] = Field(default_factory=list)
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    timeline: list[TimelineNodePayload] = Field(default_factory=list)
    route_segments: list[RouteSegmentPayload] = Field(default_factory=list)
    route_text: str | None = None
    budget_text: str | None = None
    warnings: list[str] = Field(default_factory=list)
    score: float | None = None
    plan_score: float | None = None
    rank_features: dict[str, Any] = Field(default_factory=dict)
    why_recommend: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    items: list[PlanItemPayload] = Field(default_factory=list)
    total_distance_km: float | None = None
    route_minutes: int | None = None
    total_duration_minutes: int | None = None
    estimated_budget: float | None = None
    fit_summary: dict[str, Any] = Field(default_factory=dict)
    recommendation_reason: str | None = None

    @field_validator("tags", "highlight_tags", mode="before")
    @classmethod
    def clean_short_tags(cls, value: Any) -> list[str]:
        return clean_display_tags(value, fallback=[], limit=4, max_chars=6)

    @field_validator("pros", "cons", mode="before")
    @classmethod
    def clean_points(cls, value: Any) -> list[str]:
        return clean_display_tags(value, fallback=[], limit=3, max_chars=15)

    @model_validator(mode="after")
    def fill_plan_display(self) -> "PlanCardPayload":
        if not self.highlight_tags:
            self.highlight_tags = clean_display_tags(
                [item.display_category for item in self.items],
                fallback=["本地生活"],
                limit=4,
                max_chars=6,
            )
        if not self.tags:
            self.tags = list(self.highlight_tags)
        if not self.pros:
            self.pros = ["地点匹配", "路线清晰"]
        if not self.cons:
            self.cons = ["出发前确认"]
        if not self.title or looks_like_raw_text(self.title) or " + " in self.title:
            labels = []
            for item in self.items:
                label = item.display_category or category_label(item.logical_category)
                if label not in labels:
                    labels.append(label)
            self.title = (f"{'＋'.join(labels[:2])}轻松线" if labels else "本地生活方案")[:18]
        return self


class PlanningResponsePayload(PayloadModel):
    # 顶层 payload 对齐旧前端依赖：plans、selected_plan、poi_list 等字段必须稳定存在。
    response_type: str
    summary: str = ""
    plans: list[PlanCardPayload] = Field(default_factory=list)
    selected_plan: PlanCardPayload | dict[str, Any] = Field(default_factory=dict)
    poi_list: list[PlanItemPayload] = Field(default_factory=list)
    failure_reason: str | None = None
    preference_context: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    followup_suggestions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def align_selected_plan(self) -> "PlanningResponsePayload":
        if self.plans:
            selected_id = ""
            if isinstance(self.selected_plan, PlanCardPayload):
                selected_id = self.selected_plan.id
            elif isinstance(self.selected_plan, dict):
                selected_id = str(
                    self.selected_plan.get("id") or self.selected_plan.get("plan_id") or ""
                )
            self.selected_plan = next(
                (
                    plan
                    for plan in self.plans
                    if plan.id == selected_id or plan.plan_id == selected_id
                ),
                self.plans[0],
            )
        else:
            self.selected_plan = {}
        return self


def normalize_response_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """统一的出图校验入口。

    任何节点只要要写入 response_payload，都通过这个函数收口；校验失败时应尽早暴露，
    不让不稳定字段继续进入 SSE、Session 或前端渲染链路。
    """

    return PlanningResponsePayload.model_validate(payload).model_dump(
        mode="json",
        by_alias=True,
        exclude_none=False,
    )


def clean_display_tags(
    values: Any,
    *,
    fallback: list[str] | None = None,
    limit: int = 6,
    max_chars: int = 15,
) -> list[str]:
    fallback = fallback or []
    raw_values = values if isinstance(values, list) else [values]
    result: list[str] = []
    for value in raw_values:
        text = clean_display_text(value, max_chars=max_chars)
        if not text or text in result:
            continue
        result.append(text)
        if len(result) >= limit:
            break
    if result:
        return result
    return [text for item in fallback if (text := clean_display_text(item, max_chars=max_chars))][
        :limit
    ]


def clean_display_text(value: Any, *, max_chars: int = 15) -> str:
    text = str(value or "").strip()
    if not text or looks_like_raw_text(text):
        return ""
    if text.lower() == "ktv":
        text = "KTV"
    text = re.sub(r"\s+", " ", text).strip(" ，,。；;：:|/\\")
    if not text or len(text) > max_chars * 2:
        return ""
    return text[:max_chars]


def looks_like_raw_text(value: str) -> bool:
    text = str(value or "").strip()
    lowered = text.lower()
    return (
        any(mark in text for mark in ("{", "}", "[", "]", ",", "，"))
        or any(marker in lowered for marker in RAW_TAG_MARKERS)
        or lowered in RAW_TAG_VALUES
    )


def category_label(category: Any) -> str:
    key = str(category or "").replace("poi_", "")
    return {
        "restaurant": "餐饮",
        "activity": "活动",
        "attraction": "景点",
        "shopping": "购物",
        "entertainment": "娱乐",
        "fitness": "运动",
        "beauty": "放松",
    }.get(key, "本地生活")


def transport_mode_label(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text or text == "mixed":
        return "推荐交通"
    if "walk" in text or "步行" in text:
        return "步行"
    if "taxi" in text or "打车" in text:
        return "打车"
    if "drive" in text or "driving" in text or "驾车" in text:
        return "驾车"
    if "bus" in text or "metro" in text or "transit" in text or "公交" in text or "地铁" in text:
        return "公共交通"
    return str(value)


def clean_image_list(value: Any) -> list[str]:
    raw_values = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in raw_values:
        if isinstance(item, dict):
            item = item.get("url") or item.get("src")
        text = str(item or "").strip().strip('"').strip("'")
        if text.startswith(("http://", "https://")) and text not in result:
            result.append(text)
    return result[:8]
