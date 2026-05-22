// 前端只定义页面真正会消费的字段，避免和后端内部 PlanState 强耦合。
export interface TripPlanRequest {
  user_query: string;
  user_profile?: Record<string, unknown>;
  max_replanning_count?: number;
  session_id?: string;
  trace_id?: string;
  run_id?: string;
}

export interface RevisePlanRequest {
  session_id: string;
  user_query: string;
  selected_plan_id?: string;
  max_replanning_count?: number;
}

export interface PoiItem {
  id: string;
  name: string;
  category: string;
  subcategory: string;
  lat: number;
  lon: number;
  address: string;
  rating: number;
  price_level: string;
  open_status: string;
  tags: string[];
  score?: number;
  reason?: string;
  risk_flags?: string[];
  estimated_duration_minutes?: number;
  reservation_required?: boolean;
  crowd_risk?: "low" | "medium" | "high" | string;
  budget_fit?: "good" | "tight" | "over_budget" | "unknown" | string;
  scene_fit?: number;
  distance_sensitive?: boolean;
  recommendation_reason?: string;
  option_prompts?: string[];
  image_urls?: string[];
  photo_urls?: string[];
  photos?: Array<string | { url?: string; title?: string }>;
}

export interface TimelineItem {
  order: number;
  slot_type?: string;
  poi_id?: string;
  start_time: string;
  end_time?: string;
  title: string;
  category: string;
  address: string;
  stay_minutes?: number;
  travel_from_previous_minutes?: number;
  transport_mode?: string;
  distance_from_previous_km?: number;
}

export interface RankedPlan {
  id?: string;
  title?: string;
  items?: PoiItem[];
  timeline?: TimelineItem[];
  total_duration_minutes?: number;
  route_minutes?: number;
  total_distance_km?: number;
  route_segments?: RouteSegment[];
  estimated_budget?: number;
  plan_score?: number;
  recommendation_reason?: string;
  pros?: string[];
  cons?: string[];
  plan_actions?: PlanAction[];
  score_breakdown?: ScoreBreakdown;
  verified?: boolean;
  issues?: PlanIssue[];
}

export interface PlanAction {
  id: string;
  label: string;
  type: "execute" | "export" | "refine" | string;
  prompt?: string;
}

export interface RouteSegment {
  from?: string;
  to?: string;
  from_item_id?: string;
  to_item_id?: string;
  from_id?: string;
  to_id?: string;
  distance_km?: number;
  transport_mode?: string;
  duration_minutes?: number;
  source?: "haversine_estimated" | "amap_walking" | "amap_driving" | string;
  fallback_distance_km?: number;
  forced_timeout?: boolean;
}

export interface ScoreBreakdown {
  preference_match?: number;
  distance_reasonable?: number;
  time_feasible?: number;
  rating_heat?: number;
  budget_fit?: number;
  scene_fit?: number;
  warning_penalty?: number;
  issue_codes?: string[];
}

export interface PlanIssue {
  code: string;
  message: string;
  suggestion: string;
  severity: "error" | "warning" | string;
  source?: string;
  details?: Record<string, unknown>;
}

export interface TripPlanResponse {
  response_text: string;
  execution_status: string;
  intent_type: string;
  answer_mode: string;
  need_clarification: boolean;
  missing_constraints: string[];
  clarify_question: string;
  selected_plan: RankedPlan;
  ranked_plans: RankedPlan[];
  errors: PlanIssue[];
  logs: string[];
  session_id?: string;
  trace_id?: string;
  run_id?: string;
  revision_id?: string;
  is_revision?: boolean;
}

export interface TripPlanStreamEvent {
  event: "status" | "metadata" | "response_chunk" | "final" | "done" | string;
  data: Record<string, unknown>;
}

export interface AgentThinkingEvent {
  agent: string;
  title?: string;
  message: string;
  summary?: Record<string, unknown>;
  logs?: string[];
}

// 产品化 Trace 事件：前端只展示阶段、标题和说明，不直接展示后端内部 PlanState。
export interface TraceProgressEvent {
  event: string;
  stage?: string;
  title: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface AdjustPlanResponse {
  success: boolean;
  plan: RankedPlan;
  old_poi?: PoiItem | Record<string, unknown>;
  new_poi?: PoiItem | null;
  message: string;
}

export interface ExecutionStep {
  id: string;
  type: string;
  title: string;
  description?: string;
  status: "pending" | "running" | "done" | "failed" | string;
  result?: string;
  poi_id?: string;
  poi_name?: string;
}

export interface DataSourceStatus {
  enabled: boolean;
  source: string;
  database_name: string;
  table_counts: Record<string, number>;
  error?: string | null;
}
