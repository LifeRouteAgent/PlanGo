from __future__ import annotations

import time
from typing import Any

from app.context.context_manager import ContextManager
from app.observability.trace_recorder import new_id  # 导入 ID 生成函数，用于生成 session_id

# 导入运行时存储获取函数，统一读写 session/task/metric 等数据
from app.runtime.runtime_store import get_runtime_store


class SessionStore:
    """文件型会话状态存储。

    这里保存的是 demo 所需的最近一次 PlanState 和会话轮次摘要，目标是支持同一对话框里的
    “继续修改需求”，而不是让每次输入都从空状态开始。
    """

    @staticmethod
    def ensure_session_id(session_id: str | None) -> str:
        """没有 session_id 时创建一个新的。"""

        return session_id or new_id("sess")

    @staticmethod
    def load(session_id: str) -> dict[str, Any] | None:
        """读取会话文件。"""

        # 从 runtime_store 中读取指定 session_id 对应的会话数据
        payload = get_runtime_store().load_session(session_id)
        if isinstance(payload, dict):  # 判断读取结果是否是 dict 类型
            return payload  # 如果是 dict，说明读取成功，直接返回
        return None  # 如果不存在或格式不对，返回 None

    @staticmethod
    def save_turn(
        *,
        session_id: str,  # 当前会话 ID
        trace_id: str,  # 当前请求链路追踪 ID
        run_id: str,  # 当前规划运行 ID
        user_query: str,  # 用户本轮输入内容
        state: dict[str, Any],  # 本轮规划后的内部状态
        response: dict[str, Any],  # 本轮返回给前端的响应
        revision_id: str | None = None,  # 修订 ID；如果本轮是修改方案，可记录 revision_id
        is_revision: bool = False,  # 标记本轮是否是方案修订
    ) -> None:
        """保存一次规划或修正后的最新状态。"""

        # 读取已有会话；没有则创建初始结构
        existing = SessionStore.load(session_id) or {"session_id": session_id, "turns": []}
        # 获取历史轮次列表，格式不对则用空列表
        turns = existing.get("turns", []) if isinstance(existing.get("turns"), list) else []

        turns.append({  # 向历史轮次中追加本轮摘要
            "trace_id": trace_id,  # 保存本轮 trace_id
            "run_id": run_id,  # 保存本轮 run_id
            "revision_id": revision_id,  # 保存本轮 revision_id
            "is_revision": is_revision,  # 保存是否为修订请求
            "user_query": user_query,  # 保存用户输入
            "response_text": response.get("response_text", ""),  # 保存本轮回复文本
            # 保存当前选中方案 ID
            "selected_plan_id": (response.get("selected_plan") or {}).get("id"),
            "ranked_plan_count": len(response.get("ranked_plans", []) or []),  # 保存候选方案数量
            "created_at": time.time(),  # 保存本轮创建时间戳
        })

        # 读取最近一次真正"规划类"状态, 相应, 用户 query
        latest_planning_state = existing.get("latest_planning_state")
        latest_planning_response = existing.get("latest_planning_response")
        latest_planning_query = existing.get("latest_planning_query")

        if _is_planning_state(state, response):  # 判断本轮是否属于真正的规划/推荐场景
            latest_planning_state = state  # 如果是规划场景，则更新最近规划状态
            latest_planning_response = response  # 如果是规划场景，则更新最近规划响应
            latest_planning_query = user_query  # 如果是规划场景，则更新最近规划 query

        payload = {  # 构造要保存的完整会话数据
            "session_id": session_id,  # 当前会话 ID
            "updated_at": time.time(),  # 当前会话更新时间
            "latest_trace_id": trace_id,  # 最近一次 trace_id
            "latest_run_id": run_id,  # 最近一次 run_id
            "latest_revision_id": revision_id,  # 最近一次 revision_id
            "latest_state": state,  # 最近一轮的完整状态，不管是不是规划类
            "latest_response": response,  # 最近一轮的完整响应，不管是不是规划类
            # 最近一次规划类状态，用于后续“继续修改”
            "latest_planning_state": latest_planning_state,
            "latest_planning_response": latest_planning_response,  # 最近一次规划类响应
            "latest_planning_query": latest_planning_query,  # 最近一次规划类 query
            "turns": turns[-30:],  # 只保留最近 30 轮，避免会话文件无限增长
        }
        context_manager = ContextManager()
        if context_manager.should_update_session_summary(payload, is_revision=is_revision):
            session_summary = context_manager.update_session_summary(payload)
        else:
            session_summary = context_manager.session_summary(payload)
        payload["session_summary"] = session_summary.model_dump(mode="json")

        get_runtime_store().save_session(session_id, payload)  # 将会话数据保存到 runtime_store


# todo: 这个函数要改, state 目前只是字典, 看是否能改成 dataclass,
#       `{"simple_qa", "capability"}` 这些内容, 应该也在项目其他地方用到过, 统一命名成一个新变量
def _is_planning_state(state: dict[str, Any], response: dict[str, Any]) -> bool:
    """判断本轮是否值得作为后续“继续规划/修正”的上下文。

    简单问答和能力问答不能覆盖最近一次规划上下文，否则用户先问“你是什么模型”，再说
    “预算改成1000”，系统就会忘记真正要修正的是上一轮行程规划。
    """

    # 从 state 或 response 中读取意图类型
    intent_type = str(state.get("intent_type") or response.get("intent_type") or "")
    # 从 state 或 response 中读取回答模式
    answer_mode = str(state.get("answer_mode") or response.get("answer_mode") or "")

    # 如果是简单问答或能力问答, 则不允许它覆盖最近一次规划上下文
    if intent_type in {"simple_qa", "capability"} or answer_mode in {"simple_qa", "capability"}:
        return False
    # 返回是否属于规划类状态
    return bool(
        # 意图类型是完整行程规划、分类推荐或 POI 搜索
        intent_type in {"full_trip_plan", "category_recommend", "poi_search"}
        or state.get("ranked_plans")  # 或者 state 中存在已排序方案
        or state.get("candidate_plans")  # 或者 state 中存在候选方案
        or state.get("candidate_pois")  # 或者 state 中存在候选 POI
        or response.get("ranked_plans")  # 或者 response 中存在已排序方案
    )
