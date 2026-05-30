from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.availability_checker import availability_checker_node
from app.agents.constraint_builder import constraint_builder_node
from app.agents.constraint_clarifier import (
    constraint_clarifier_node,
    constraint_clarifier_route,
)
from app.agents.execution_agent import execution_agent_node, user_confirm_node
from app.agents.intent_parser import intent_parser_node
from app.agents.intent_router import intent_router_node, intent_router_route
from app.agents.llm_critic import llm_critic_node
from app.agents.planner_agent import planner_agent_node
from app.agents.poi_collector import poi_collector_node
from app.agents.ranker import ranker_node
from app.agents.response_generator import response_generator_node, response_route
from app.agents.route_planner import route_time_planner_node
from app.agents.verifier import verifier_node, verifier_route
from app.state.plan_state import PlanState
from app.tools.poi_activity_recommend import poi_activity_recommend_node
from app.tools.poi_lifestyle_recommend import poi_lifestyle_recommend_node
from app.tools.poi_mix_recommend import poi_mix_recommend_node
from app.tools.poi_restaurant_recommend import poi_restaurant_recommend_node


def build_life_route_graph():
    """构建本地生活规划 LangGraph DAG。

    重点结构：
    - Collector 后四个 Skill 并行执行。
    - Verifier 通过条件边决定进入排序、回退 Planner 或直接输出失败响应。
    """

    graph = StateGraph(PlanState)

    graph.add_node("intent_parser", intent_parser_node)
    graph.add_node("intent_router", intent_router_node)
    graph.add_node("constraint_builder", constraint_builder_node)
    graph.add_node("constraint_clarifier", constraint_clarifier_node)
    graph.add_node("planner_agent", planner_agent_node)
    graph.add_node("poi_collector", poi_collector_node)
    graph.add_node("poi_mix_recommend", poi_mix_recommend_node)
    graph.add_node("poi_activity_recommend", poi_activity_recommend_node)
    graph.add_node("poi_restaurant_recommend", poi_restaurant_recommend_node)
    graph.add_node("poi_lifestyle_recommend", poi_lifestyle_recommend_node)
    graph.add_node(
        "post_skill_router", lambda state: {"logs": ["DAG: joined parallel skill results"]}
    )
    graph.add_node("route_time_planner", route_time_planner_node)
    graph.add_node("availability_checker", availability_checker_node)
    graph.add_node("verifier", verifier_node)
    graph.add_node("llm_critic", llm_critic_node)
    graph.add_node("ranker", ranker_node)
    graph.add_node("response_generator", response_generator_node)
    graph.add_node("user_confirm", user_confirm_node)
    graph.add_node("execution_agent", execution_agent_node)

    graph.add_edge(START, "intent_router")
    graph.add_conditional_edges(
        "intent_router",
        intent_router_route,
        {
            "direct_answer": "response_generator",
            "recommend": "constraint_builder",
            "full_plan": "intent_parser",
        },
    )
    graph.add_edge("intent_parser", "constraint_builder")
    graph.add_edge("constraint_builder", "constraint_clarifier")
    graph.add_conditional_edges(
        "constraint_clarifier",
        constraint_clarifier_route,
        {
            "clarify": "response_generator",
            "continue": "planner_agent",
        },
    )
    graph.add_edge("planner_agent", "poi_collector")
    graph.add_edge("poi_collector", "poi_mix_recommend")
    graph.add_edge("poi_collector", "poi_activity_recommend")
    graph.add_edge("poi_collector", "poi_restaurant_recommend")
    graph.add_edge("poi_collector", "poi_lifestyle_recommend")
    graph.add_edge(
        [
            "poi_mix_recommend",
            "poi_activity_recommend",
            "poi_restaurant_recommend",
            "poi_lifestyle_recommend",
        ],
        "post_skill_router",
    )
    graph.add_conditional_edges(
        "post_skill_router",
        lambda state: (
            "rank" if state.get("intent_type") in {"category_recommend", "poi_search"} else "route"
        ),
        {
            "rank": "ranker",
            "route": "route_time_planner",
        },
    )
    graph.add_edge("route_time_planner", "availability_checker")
    graph.add_edge("availability_checker", "verifier")
    graph.add_conditional_edges(
        "verifier",
        verifier_route,
        {
            "rank": "llm_critic",
            "replan": "planner_agent",
            "respond": "response_generator",
        },
    )
    graph.add_edge("llm_critic", "ranker")
    graph.add_edge("ranker", "response_generator")
    graph.add_conditional_edges(
        "response_generator",
        response_route,
        {
            "execute": "user_confirm",
            "end": END,
        },
    )
    graph.add_edge("user_confirm", "execution_agent")
    graph.add_edge("execution_agent", END)

    return graph.compile()


life_route_graph = build_life_route_graph()
