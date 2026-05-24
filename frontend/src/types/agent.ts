export type Scenario = "family" | "friends" | "couple" | "unknown";

export type StepType = "travel" | "activity" | "meal" | "extra" | "buffer";

export type BookingStatus = "pending" | "confirmed" | "failed" | "compensated" | "skipped";

export interface Location {
  name: string;
  lat: number;
  lng: number;
  address: string;
}

export interface Person {
  role: string;
  age: number | null;
  gender: string | null;
  preferences: string[];
}

export interface UserIntent {
  raw_text: string;
  scenario: Scenario;
  start_time: string;
  duration_min_range: [number, number];
  people: Person[];
  goals: string[];
  constraints: string[];
  radius_km: number;
  need_confirmation: boolean;
}

export interface StepDetail {
  image_url: string | null;
  tags: string[];
  description: string;
  traffic: string;
  cost: number;
  address: string;
}

export interface PlanStep {
  type: StepType;
  title: string;
  start_time: string;
  end_time: string;
  location: Location | null;
  target_id: string | null;
  reason: string;
  cost: number;
  booking_required: boolean;
  metadata: Record<string, unknown>;
  detail?: StepDetail;
}

export interface BookingAction {
  action_id: string;
  action_type: string;
  target_id: string;
  target_name: string;
  scheduled_time: string;
  people_count: number;
  status: BookingStatus;
  order_id: string | null;
  failure_reason: string | null;
}

export interface RouteStop {
  order: number;
  title: string;
  start_time: string;
  end_time: string;
  location: Location | null;
}

export interface RouteSegment {
  type: "travel" | "activity" | "meal" | "return";
  title: string;
  color: string;
  polyline: Array<{ lat: number; lng: number }>;
}

export interface PlanAlternative {
  id: string;
  title: string;
  rating: number;
  distance_km: number;
  duration_min: number;
  tags: string[];
  image_url?: string | null;
  description?: string;
}

export interface WeatherHour {
  time: string;
  temperature_c: number;
  condition: string;
  icon: string;
}

export interface WeatherInfo {
  temperature_c: number | null;
  condition: string;
  icon: string;
  summary: string;
  source: "amap" | "unconfigured" | "error";
  hourly: WeatherHour[];
  message?: string;
}

export interface Plan {
  id?: string;
  trace_id?: string;
  run_id?: string;
  session_id?: string;
  scenario: Scenario;
  start_time: string;
  end_time: string;
  total_duration_min: number;
  total_cost: number;
  steps: PlanStep[];
  actions: BookingAction[];
  rationale: string[];
  share_message: string;
  risk_flags: string[];
  city?: {
    code: string;
    name: string;
  };
  saved?: boolean;
  favorited?: boolean;
  recommendation?: {
    title: string;
    rating: number;
    distance_km: number;
    tags: string[];
    cover_image: string | null;
  };
  route?: {
    provider: string;
    source?: string;
    polyline: Array<{ lat: number; lng: number }>;
    segments?: RouteSegment[];
    stops: RouteStop[];
    navigate_url: string | null;
  };
  alternatives?: PlanAlternative[];
  weather?: WeatherInfo;
  details?: {
    steps: PlanStep[];
    alternatives: PlanAlternative[];
  };
}

export interface ChatHistoryItem {
  role: "user" | "assistant";
  content: string;
}

export type StreamEvent =
  | { event: "status"; data: { message: string } }
  | {
      event: "capability";
      data: {
        llm: "mimo" | "rule";
        local_life_tools: "mock" | "real";
        booking: "mock" | "real";
        message: string;
      };
    }
  | { event: "intent"; data: { intent: UserIntent; trace: string[] } }
  | { event: "plan"; data: { plan: Plan; trace: string[] } }
  | {
      event: "validation";
      data: { ok: boolean; errors: string[]; warnings: string[]; trace: string[] };
    }
  | { event: "execution"; data: { actions: BookingAction[]; risk_flags: string[] } }
  | { event: "response_chunk"; data: { delta: string } }
  | { event: "done"; data: { plan: Plan | null; trace: string[] } }
  | { event: "error"; data: { message: string; errors?: string[] } };

export interface StreamRequest {
  goal: string;
  city: string;
  execute: boolean;
  fail_next_restaurant_booking: boolean;
  history?: ChatHistoryItem[];
}
