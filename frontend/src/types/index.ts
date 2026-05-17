// 前端只定义页面真正会消费的字段，避免和后端内部 PlanState 强耦合。
export interface TripPlanRequest {
  user_query: string;
  user_profile?: Record<string, unknown>;
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
}

export interface TimelineItem {
  order: number;
  start_time: string;
  title: string;
  category: string;
  address: string;
}

export interface RankedPlan {
  id?: string;
  title?: string;
  items?: PoiItem[];
  timeline?: TimelineItem[];
  total_duration_minutes?: number;
  route_minutes?: number;
  estimated_budget?: number;
  verified?: boolean;
}

export interface TripPlanResponse {
  response_text: string;
  execution_status: string;
  selected_plan: RankedPlan;
  ranked_plans: RankedPlan[];
  errors: string[];
  logs: string[];
}
