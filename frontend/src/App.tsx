import { Activity, Calendar, CalendarClock, Heart, History, Home, User } from "lucide-react";
import { useState } from "react";
import { AppShell } from "./components/AppShell";
import type { TimelineEvent } from "./hooks/usePlanStream";
import { ObservabilityPage } from "./pages/ObservabilityPage";
import { OperationsConsole } from "./pages/OperationsConsole";
import { PlannerWorkspace } from "./pages/PlannerWorkspace";
import { UserSectionPage } from "./pages/UserSectionPage";
import type { Plan } from "./types/agent";

export type AppView = "planner" | "plans" | "favorites" | "history" | "calendar" | "profile" | "observability";

const navigation = [
  { id: "planner", label: "首页", icon: Home },
  { id: "plans", label: "我的规划", icon: CalendarClock },
  { id: "favorites", label: "收藏夹", icon: Heart },
  { id: "history", label: "历史记录", icon: History },
  { id: "calendar", label: "日历", icon: Calendar },
  { id: "profile", label: "个人中心", icon: User },
  { id: "observability", label: "观测面板", icon: Activity }
] as const;

const pageTitle: Record<AppView, string> = {
  planner: "首页",
  plans: "我的规划",
  favorites: "收藏夹",
  history: "历史记录",
  calendar: "日历",
  profile: "个人中心",
  observability: "观测面板"
};

export function App() {
  const [activeView, setActiveView] = useState<AppView>("planner");
  const [latestPlan, setLatestPlan] = useState<Plan | null>(null);
  const [latestEvents, setLatestEvents] = useState<TimelineEvent[]>([]);
  const [city, setCity] = useState("beijing");

  return (
    <AppShell
      activeView={activeView}
      navigation={navigation}
      city={city}
      pageTitle={pageTitle[activeView]}
      onCityChange={setCity}
      onNavigate={setActiveView}
    >
      {activeView === "planner" && (
        <PlannerWorkspace
          city={city}
          onCityChange={setCity}
          onPlanChange={setLatestPlan}
          onTraceChange={setLatestEvents}
        />
      )}
      {activeView === "plans" && <OperationsConsole plan={latestPlan} />}
      {activeView === "observability" && <ObservabilityPage plan={latestPlan} events={latestEvents} />}
      {activeView !== "planner" && activeView !== "plans" && activeView !== "observability" && (
        <UserSectionPage section={activeView} />
      )}
    </AppShell>
  );
}
