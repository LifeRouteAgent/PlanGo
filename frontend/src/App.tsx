import { useEffect, useMemo, useState } from "react";
import { ChatHome } from "./pages/ChatHome";
import { ChatSidebar } from "./pages/ChatHome/ChatSidebar";
import { PlanDetail } from "./pages/PlanDetail";
import { PlanOverview } from "./pages/PlanOverview";
import { SharePage } from "./pages/SharePage";
import type { Plan, PlanAlternative } from "./types/agent";
import {
  createEmptyConversation,
  deleteConversation,
  isPlanLinkMessage,
  loadConversations,
  loadOrCreateActiveConversation,
  PLAN_LINK_MESSAGE,
  saveConversations,
  setActiveConversationId,
  upsertConversation,
  type ConversationRecord,
  type StoredChatMessage
} from "./utils/conversationStore";
import { AUTO_SUBMIT_EVENT, type AutoSubmitPayload } from "./utils/autoSubmitEvent";
import { planToViewModel, type PlanViewModel } from "./utils/planViewModel";

type AppRoute = "/" | "/plan" | "/plan/detail" | "/share";
export type AppView = "planner" | "plans" | "favorites" | "history" | "calendar" | "profile" | "observability";

type PendingChatSubmit = AutoSubmitPayload;

function normalizePath(pathname: string): AppRoute {
  if (pathname === "/plan" || pathname === "/plan/detail" || pathname === "/share") {
    return pathname;
  }
  return "/";
}

function detailUrl(plan: PlanViewModel | null | undefined) {
  return plan?.id ? `/plan/detail?plan=${encodeURIComponent(plan.id)}` : "/plan/detail";
}

function planIdFromLocation() {
  return new URLSearchParams(window.location.search).get("plan") || "";
}

function samePlan(left: PlanViewModel | null, right: PlanViewModel) {
  return Boolean(left && (left.id === right.id || left.raw.id === right.raw.id));
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
    highlight_tags: alternative.highlight_tags?.length ? alternative.highlight_tags : plan.highlight_tags,
    rationale: [alternative.recommendation_reason || alternative.description || "这是一个地点组合不同的备选方案。", ...(alternative.pros ?? [])].filter(
      Boolean
    ),
    risk_flags: alternative.cons ?? plan.risk_flags
  };
}

function badgeFor(index: number) {
  if (index === 0) return "方案一";
  if (index === 1) return "方案二";
  return "方案三";
}

function planLinkMessageId(plan: Plan) {
  return `plan-link-${plan.id ?? plan.trace_id ?? crypto.randomUUID()}`;
}

function appendPlanLinkMessage(messages: StoredChatMessage[], plan: Plan | null) {
  if (!plan) {
    return messages;
  }

  const lastMessage = messages[messages.length - 1];
  if (lastMessage && isPlanLinkMessage(lastMessage)) {
    return messages;
  }

  return [
    ...messages,
    {
      id: planLinkMessageId(plan),
      role: "assistant" as const,
      content: PLAN_LINK_MESSAGE
    }
  ];
}

export function App() {
  const [route, setRoute] = useState<AppRoute>(() => normalizePath(window.location.pathname));
  const [activeConversation, setActiveConversation] = useState<ConversationRecord>(() => loadOrCreateActiveConversation());
  const [conversations, setConversations] = useState<ConversationRecord[]>(() => loadConversations());
  const [messages, setMessages] = useState<StoredChatMessage[]>(() => appendPlanLinkMessage(activeConversation.messages, activeConversation.plan));
  const [latestPlan, setLatestPlan] = useState<Plan | null>(() => activeConversation.plan);
  const [selectedPlan, setSelectedPlan] = useState<PlanViewModel | null>(null);
  const [feedbackMessage, setFeedbackMessage] = useState("");
  const [pendingChatSubmit, setPendingChatSubmit] = useState<PendingChatSubmit | null>(null);

  useEffect(() => {
    const onPopState = () => setRoute(normalizePath(window.location.pathname));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = (nextRoute: AppRoute, targetUrl: string = nextRoute) => {
    const currentUrl = `${window.location.pathname}${window.location.search}`;
    if (currentUrl !== targetUrl) {
      window.history.pushState({}, "", targetUrl);
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

  const handleStreamComplete = (conversationId: string, nextMessages: StoredChatMessage[], nextPlan: Plan | null) => {
    const records = loadConversations();
    const target = records.find((item) => item.id === conversationId);
    if (!target) return;

    const messagesWithPlanLink = nextPlan ? appendPlanLinkMessage(nextMessages, nextPlan) : nextMessages;
    const saved = upsertConversation(
      {
        ...target,
        messages: messagesWithPlanLink,
        plan: nextPlan ?? target.plan
      },
      { activate: conversationId === activeConversation.id }
    );

    setConversations(loadConversations());
    if (conversationId === activeConversation.id) {
      setActiveConversation(saved);
      setMessages(messagesWithPlanLink);
      setLatestPlan(saved.plan);
      setSelectedPlan(saved.plan ? planToViewModel(saved.plan, badgeFor(0), 0) : null);
    }
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
    if (!planOptions.length) {
      if (selectedPlan) setSelectedPlan(null);
      return;
    }

    if (route === "/plan/detail") {
      const urlPlanId = planIdFromLocation();
      const matchedPlan = urlPlanId
        ? planOptions.find((item) => item.id === urlPlanId || item.raw.id === urlPlanId)
        : null;
      if (matchedPlan) {
        if (!samePlan(selectedPlan, matchedPlan)) {
          setSelectedPlan(matchedPlan);
        }
        return;
      }
    }

    const stillExists = selectedPlan ? planOptions.some((item) => samePlan(selectedPlan, item)) : false;
    if (!stillExists) {
      setSelectedPlan(planOptions[0]);
    }
  }, [planOptions, route, selectedPlan]);

  const handlePlanReady = (plan: Plan) => {
    setLatestPlan(plan);
    const first = planToViewModel(plan, badgeFor(0), 0);
    setSelectedPlan(first);
    const nextMessages = appendPlanLinkMessage(messages, plan);
    setMessages(nextMessages);
    persistConversation(nextMessages, plan);
  };

  const handleSelectPlan = (plan: PlanViewModel) => {
    setSelectedPlan(plan);
    navigate("/plan/detail", detailUrl(plan));
  };

  const openCurrentDetail = () => {
    const plan = selectedPlan ?? planOptions[0] ?? null;
    if (plan) setSelectedPlan(plan);
    navigate("/plan/detail", detailUrl(plan));
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
    const nextMessages = appendPlanLinkMessage(record.messages, record.plan);
    setMessages(nextMessages);
    setLatestPlan(record.plan);
    setSelectedPlan(record.plan ? planToViewModel(record.plan, badgeFor(0), 0) : null);
    setFeedbackMessage("");
    navigate("/");
  };

  const handleDeleteConversation = (conversationId: string) => {
    const wasActive = conversationId === activeConversation.id;
    const remaining = deleteConversation(conversationId);

    if (!wasActive) {
      setConversations(remaining);
      return;
    }

    const nextActive = remaining[0] ?? upsertConversation(createEmptyConversation());
    if (!remaining.length) {
      saveConversations([nextActive]);
    }
    setActiveConversationId(nextActive.id);
    setActiveConversation(nextActive);
    setConversations(loadConversations());
    setMessages(appendPlanLinkMessage(nextActive.messages, nextActive.plan));
    setLatestPlan(nextActive.plan);
    setSelectedPlan(nextActive.plan ? planToViewModel(nextActive.plan, badgeFor(0), 0) : null);
    setFeedbackMessage("");
    navigate("/");
  };

  const handlePreferenceSubmit = (message: string) => {
    const pending = { id: crypto.randomUUID(), text: message };
    setPendingChatSubmit(pending);
    navigate("/");
    window.setTimeout(() => {
      window.dispatchEvent(new CustomEvent<PendingChatSubmit>(AUTO_SUBMIT_EVENT, { detail: pending }));
    }, 120);
  };

  return (
    <main className="plango-app">
      <ChatSidebar
        conversationId={activeConversation.id}
        conversations={conversations}
        onNewConversation={handleNewConversation}
        onLoadConversation={handleLoadConversation}
        onDeleteConversation={handleDeleteConversation}
      />
      <div className="app-content-with-sidebar">
        <div hidden={route !== "/"}>
          <ChatHome
            conversationId={activeConversation.id}
            messages={messages}
            hasPlan={Boolean(latestPlan)}
            onMessagesChange={handleMessagesChange}
            onPlanReady={handlePlanReady}
            onOpenPlans={() => navigate("/plan")}
            onOpenDetail={openCurrentDetail}
            onStreamComplete={handleStreamComplete}
            pendingSubmit={pendingChatSubmit}
            onPendingSubmitConsumed={() => setPendingChatSubmit(null)}
          />
        </div>

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
            onPreferenceSubmit={handlePreferenceSubmit}
          />
        )}

        {route === "/share" && (
          <SharePage
            plan={selectedPlan ?? planOptions[0] ?? null}
            feedbackMessage={feedbackMessage}
            onFeedback={setFeedbackMessage}
            onBack={() => {
              if (selectedPlan) {
                navigate("/plan/detail", detailUrl(selectedPlan));
              } else {
                navigate("/plan");
              }
            }}
            onBackHome={() => navigate("/")}
          />
        )}
      </div>
    </main>
  );
}

