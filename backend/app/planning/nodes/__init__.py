"""Planning Graph V2 node modules grouped by business stage."""

from app.planning.nodes.candidate_nodes import (
    single_category_ranker_node,
    poi_scorer_node,
    candidate_pool_balancer_node,
)
from app.planning.nodes.constraint_nodes import constraint_builder_node
from app.planning.nodes.context_nodes import (
    request_context_loader_node,
    session_state_loader_node,
    memory_reader_node,
)
from app.planning.nodes.intent_nodes import (
    intent_resolver_node,
    session_preference_extractor_node,
    async_event_emitter_node,
    request_router_node,
)
from app.planning.nodes.planning_nodes import route_planner_node, plan_editor_node
from app.planning.nodes.recall_nodes import recall_plan_compiler_node, collector_node
from app.planning.nodes.response_nodes import (
    simple_response_generator_node,
    response_generator_node,
    response_assembler_node,
)
from app.planning.nodes.session_nodes import session_state_saver_node
from app.planning.nodes.validation_nodes import (
    final_ranker_node,
    fallback_relaxation_node,
    failure_analyzer_node,
    post_check_filter_node,
    availability_checker_node,
    pre_ranker_node,
)

GRAPH_NODES = {
    "request_context_loader": request_context_loader_node,
    "session_state_loader": session_state_loader_node,
    "memory_reader": memory_reader_node,
    "intent_resolver": intent_resolver_node,
    "session_preference_extractor": session_preference_extractor_node,
    "async_event_emitter": async_event_emitter_node,
    "request_router": request_router_node,
    "constraint_builder": constraint_builder_node,
    "plan_editor": plan_editor_node,
    "recall_plan_compiler": recall_plan_compiler_node,
    "collector": collector_node,
    "poi_scorer": poi_scorer_node,
    "candidate_pool_balancer": candidate_pool_balancer_node,
    "route_planner": route_planner_node,
    "pre_ranker": pre_ranker_node,
    "availability_checker": availability_checker_node,
    "post_check_filter": post_check_filter_node,
    "failure_analyzer": failure_analyzer_node,
    "fallback_relaxation": fallback_relaxation_node,
    "final_ranker": final_ranker_node,
    "single_category_ranker": single_category_ranker_node,
    "response_assembler": response_assembler_node,
    "response_generator": response_generator_node,
    "simple_response_generator": simple_response_generator_node,
    "session_state_saver": session_state_saver_node,
}
