from __future__ import annotations  # 启用“延迟解析类型注解”，避免前向引用或复杂类型在运行时立即求值

from typing import Any  # 引入 Any，表示字段可以接收任意类型的数据

from pydantic import BaseModel, Field  # BaseModel 用于定义请求/响应模型，Field 用于设置默认值、校验规则和字段说明


class TripPlanRequest(BaseModel):  # 行程规划接口的请求体模型
    user_query: str = Field(..., min_length=1)  # 用户输入的自然语言需求，必填，最少 1 个字符
    user_profile: dict[str, Any] = Field(default_factory=dict)  # 用户画像信息，默认为空字典，例如城市、预算、偏好等
    max_replanning_count: int = Field(default=2, ge=0, le=3)  # 最大重规划次数，默认 2 次，范围 0 到 3
    session_id: str | None = None  # 会话 ID，可选，用于关联多轮对话
    trace_id: str | None = None  # 链路追踪 ID，可选，用于日志追踪和排查问题
    run_id: str | None = None  # 当前运行 ID，可选，用于区分一次具体的规划执行
    user_id: str | None = None  # 用户 ID，可选，用于长期记忆、用户画像和行为记录
    message_id: str | None = None  # 当前消息 ID，可选，用于定位某一轮用户输入
    timezone: str = "Asia/Shanghai"  # 用户时区，默认中国上海时区
    source: str = "api"  # 请求来源，默认 api，例如也可以是 web、app、debug 等
    geo_location: dict[str, Any] | None = None  # 浏览器或客户端获取到的地理位置，可选，例如经纬度
    manual_origin: dict[str, Any] | None = None  # 用户手动输入或 LLM 识别出的出发地，可选
    debug: bool = False  # 是否开启调试模式，默认关闭


class TripPlanResponse(BaseModel):  # 行程规划接口的响应体模型
    response_text: str  # 返回给前端展示的主要文本内容，必填
    execution_status: str  # 执行状态，必填，例如 success、failed、need_clarification
    intent_type: str = ""  # 用户意图类型，默认空字符串，例如 trip_plan、single_recommend、qa
    answer_mode: str = ""  # 回答模式，默认空字符串，例如 direct_answer、plan_cards、clarify
    need_clarification: bool = False  # 是否需要追问用户补充信息，默认不需要
    missing_constraints: list[str] = Field(default_factory=list)  # 缺失的约束条件列表，默认为空列表
    clarify_question: str = ""  # 需要追问用户的问题，默认空字符串
    selected_plan: dict[str, Any]  # 最终选中的方案，必填
    ranked_plans: list[dict[str, Any]]  # 排序后的候选方案列表，必填
    errors: list[dict[str, Any]]  # 执行过程中产生的错误信息列表，必填
    logs: list[str]  # 执行日志列表，必填
    session_id: str = ""  # 会话 ID，默认空字符串
    trace_id: str = ""  # 链路追踪 ID，默认空字符串
    run_id: str = ""  # 当前运行 ID，默认空字符串
    revision_id: str = ""  # 方案修订 ID，默认空字符串
    is_revision: bool = False  # 当前响应是否是基于已有方案的修改结果，默认不是
    task_id: str = ""  # 异步任务 ID，默认空字符串
    final_text: str = ""  # 最终生成的完整文本，默认空字符串
    response_payload: dict[str, Any] = Field(default_factory=dict)  # 给前端使用的结构化响应数据，默认为空字典
    plan_state_id: str = ""  # 当前规划状态 ID，默认空字符串，用于持久化 PlanState
    constraints: dict[str, Any] = Field(default_factory=dict)  # 本次规划抽取出的约束条件，默认为空字典
    target_categories: list[str] = Field(default_factory=list)  # 本次需要查询的 POI 类别列表，默认为空列表
    weather: dict[str, Any] = Field(default_factory=dict)  # 天气信息，默认为空字典
    routes: list[dict[str, Any]] = Field(default_factory=list)  # 路线信息列表，默认为空列表
    debug: dict[str, Any] = Field(default_factory=dict)  # 调试信息，默认为空字典


class ExecutePlanRequest(BaseModel):  # 执行计划接口的请求体模型
    plan: dict[str, Any]  # 前端传入的待执行方案，必填
    session_id: str | None = None  # 会话 ID，可选
    trace_id: str | None = None  # 链路追踪 ID，可选
    run_id: str | None = None  # 当前运行 ID，可选
    task_id: str | None = None  # 异步任务 ID，可选


class ExportPlanRequest(BaseModel):  # 导出计划接口的请求体模型
    plan: dict[str, Any]  # 需要导出的方案，必填
    session_id: str | None = None  # 会话 ID，可选
    trace_id: str | None = None  # 链路追踪 ID，可选


class AdjustPlanRequest(BaseModel):  # 局部调整方案接口的请求体模型
    """方案局部调整请求。

    前端用于“某一站不满意，换一个类似地点”的产品化调整。
    不要求重新跑完整 DAG，后端会按当前站点类别从数据库找替代 POI。
    """

    plan: dict[str, Any]  # 当前正在调整的完整方案，必填
    poi_id: str  # 用户想要替换的 POI ID，必填
    prompt: str = Field(default="换一个更合适的")  # 用户调整要求，默认是“换一个更合适的”
    session_id: str | None = None  # 会话 ID，可选
    trace_id: str | None = None  # 链路追踪 ID，可选
    run_id: str | None = None  # 当前运行 ID，可选


class RevisePlanRequest(BaseModel):  # 多轮修改方案接口的请求体模型
    session_id: str = Field(..., min_length=1)  # 会话 ID，必填，最少 1 个字符，用于找到历史上下文
    user_query: str = Field(..., min_length=1)  # 用户新的修改需求，必填，最少 1 个字符
    selected_plan_id: str | None = None  # 用户当前选中的方案 ID，可选
    max_replanning_count: int = Field(default=2, ge=0, le=3)  # 最大重规划次数，默认 2 次，范围 0 到 3


class DataSourceStatusResponse(BaseModel):  # 数据源状态接口的响应体模型
    enabled: bool  # 数据源是否启用，必填
    source: str  # 数据源类型或名称，必填，例如 mysql、mock、csv
    database_name: str  # 当前使用的数据库名称，必填
    table_counts: dict[str, int] = Field(default_factory=dict)  # 各数据表的数据量统计，默认为空字典
    error: str | None = None  # 数据源异常信息，可选，没有错误时为 None