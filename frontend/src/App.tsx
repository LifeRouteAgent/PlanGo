import { useEffect, useMemo, useState } from "react";
import { ChatHome } from "./pages/ChatHome";
import { PlanDetail } from "./pages/PlanDetail";
import { PlanOverview } from "./pages/PlanOverview";
import { SharePage } from "./pages/SharePage";
import type { Plan, PlanAlternative } from "./types/agent";
import {
  createEmptyConversation,
  loadConversations,
  loadOrCreateActiveConversation,
  setActiveConversationId,
  upsertConversation,
  type ConversationRecord,
  type StoredChatMessage
} from "./utils/conversationStore";
import { planToViewModel, type PlanViewModel } from "./utils/planViewModel";

type AppRoute = "/" | "/plan" | "/plan/detail" | "/share";
export type AppView = "planner" | "plans" | "favorites" | "history" | "calendar" | "profile" | "observability";

function normalizePath(pathname: string): AppRoute {
  if (pathname === "/plan" || pathname === "/plan/detail" || pathname === "/share") {
    return pathname;
  }
  return "/";
}

function alternativeToPlan(plan: Plan, alternative: PlanAlternative): Plan {
  return {
    ...plan,
    id: alternative.id,
    total_cost: alternative.total_cost ?? plan.total_cost,
    total_duration_min: alternative.duration_min || plan.total_duration_min,
    steps: alternative.steps?.length ? alternative.steps : plan.steps,
    recommendation: {
      title: alternative.title,
      rating: alternative.rating,
      distance_km: alternative.distance_km,
      tags: alternative.tags,
      cover_image: alternative.image_url ?? plan.recommendation?.cover_image ?? null
    },
    route: alternative.route ?? plan.route,
    rationale: [
      alternative.recommendation_reason || alternative.description || "这是一个地点组合不同的备选方案。",
      ...(alternative.pros ?? [])
    ].filter(Boolean),
    risk_flags: alternative.cons ?? plan.risk_flags
  };
}

function badgeFor(index: number) {
  if (index === 0) return "主推方案";
  if (index === 1) return "更省心";
  return "不同路线";
}

export function App() {
  const [route, setRoute] = useState<AppRoute>(() => normalizePath(window.location.pathname));
  const [activeConversation, setActiveConversation] = useState<ConversationRecord>(() => loadOrCreateActiveConversation());
  const [conversations, setConversations] = useState<ConversationRecord[]>(() => loadConversations());
  const [messages, setMessages] = useState<StoredChatMessage[]>(() => activeConversation.messages);
  const [latestPlan, setLatestPlan] = useState<Plan | null>(() => activeConversation.plan);
  const [selectedPlan, setSelectedPlan] = useState<PlanViewModel | null>(null);
  const [feedbackMessage, setFeedbackMessage] = useState("");

  useEffect(() => {
    const onPopState = () => setRoute(normalizePath(window.location.pathname));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = (nextRoute: AppRoute) => {
    if (window.location.pathname !== nextRoute) {
      window.history.pushState({}, "", nextRoute);
    }
    setRoute(nextRoute);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const persistConversation = (nextMessages: StoredChatMessage[], nextPlan: Plan | null = latestPlan) => {
    const saved = upsertConversation({
      ...activeConversation,
      messages: nextMessages,
      plan: nextPlan
    });
    setActiveConversation(saved);
    setConversations(loadConversations());
  };

  const handleMessagesChange = (nextMessages: StoredChatMessage[]) => {
    setMessages(nextMessages);
    persistConversation(nextMessages);
  };

  const planOptions = useMemo(() => {
    if (!latestPlan) {
      return [];
    }

    const primary = planToViewModel(latestPlan, badgeFor(0), 0);
    const alternatives =
      latestPlan.alternatives?.slice(0, 2).map((alternative, index) =>
        planToViewModel(alternativeToPlan(latestPlan, alternative), badgeFor(index + 1), index + 1)
      ) ?? [];

    return [primary, ...alternatives].slice(0, 3);
  }, [latestPlan]);

  useEffect(() => {
    if (!selectedPlan && planOptions.length) {
      setSelectedPlan(planOptions[0]);
    }
  }, [planOptions, selectedPlan]);

  const handlePlanReady = (plan: Plan) => {
    setLatestPlan(plan);
    const first = planToViewModel(plan, badgeFor(0), 0);
    setSelectedPlan(first);
    persistConversation(messages, plan);
  };

  const handleSelectPlan = (plan: PlanViewModel) => {
    setSelectedPlan(plan);
    navigate("/plan/detail");
  };

  const handleNewConversation = () => {
    const created = upsertConversation(createEmptyConversation());
    setActiveConversation(created);
    setConversations(loadConversations());
    setMessages(created.messages);
    setLatestPlan(null);
    setSelectedPlan(null);
    setFeedbackMessage("");
    navigate("/");
  };

  const handleLoadConversation = (conversationId: string) => {
    const record = loadConversations().find((item) => item.id === conversationId);
    if (!record) return;
    setActiveConversationId(record.id);
    setActiveConversation(record);
    setConversations(loadConversations());
    setMessages(record.messages);
    setLatestPlan(record.plan);
    setSelectedPlan(record.plan ? planToViewModel(record.plan, badgeFor(0), 0) : null);
    setFeedbackMessage("");
    navigate("/");
  };

  return (
    <main className="plango-app">
      {route === "/" && (
        <ChatHome
          conversationId={activeConversation.id}
          messages={messages}
          conversations={conversations}
          hasPlan={Boolean(latestPlan)}
          onMessagesChange={handleMessagesChange}
          onPlanReady={handlePlanReady}
          onOpenPlans={() => navigate("/plan")}
          onOpenDetail={() => navigate("/plan/detail")}
          onNewConversation={handleNewConversation}
          onLoadConversation={handleLoadConversation}
        />
      )}

      {route === "/plan" && (
        <PlanOverview
          plans={planOptions}
          onBackHome={() => navigate("/")}
          onOpenDetail={handleSelectPlan}
          onShare={(plan) => {
            setSelectedPlan(plan);
            navigate("/share");
          }}
        />
      )}

      {route === "/plan/detail" && (
        <PlanDetail
          plan={selectedPlan}
          onBack={() => navigate("/plan")}
          onBackHome={() => navigate("/")}
          onShare={() => navigate("/share")}
          onPlanUpdate={setSelectedPlan}
        />
      )}

      {route === "/share" && (
        <SharePage
          plan={selectedPlan ?? planOptions[0] ?? null}
          feedbackMessage={feedbackMessage}
          onFeedback={setFeedbackMessage}
          onBack={() => navigate(selectedPlan ? "/plan/detail" : "/plan")}
          onBackHome={() => navigate("/")}
        />
      )}
    </main>
  );
}
