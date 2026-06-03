import { useCallback, useRef, useState } from "react";
import { streamPlan } from "../api/streamClient";
import type { Plan, StreamEvent, StreamRequest, UserIntent } from "../types/agent";

export interface TimelineEvent {
  id: string;
  label: string;
  detail: string;
  level: "info" | "success" | "warning" | "error";
  phase: "request" | "understanding" | "searching" | "routing" | "validating" | "executing" | "done" | "error";
}

const SESSION_STORAGE_KEY = "plango_session_id";

function getOrCreateSessionId() {
  const cached = window.localStorage.getItem(SESSION_STORAGE_KEY);
  if (cached) return cached;
  const sessionId = crypto.randomUUID();
  window.localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
  return sessionId;
}

function eventPhase(message: string): TimelineEvent["phase"] {
  const text = message.toLowerCase();
  if (text.includes("intent") || text.includes("理解") || text.includes("意图") || text.includes("约束")) return "understanding";
  if (text.includes("collector") || text.includes("skill") || text.includes("poi") || text.includes("活动") || text.includes("餐厅") || text.includes("召回") || text.includes("筛选")) {
    return "searching";
  }
  if (text.includes("route") || text.includes("map") || text.includes("路线") || text.includes("地图") || text.includes("时间线")) return "routing";
  if (text.includes("verify") || text.includes("critic") || text.includes("校验") || text.includes("验证") || text.includes("检查")) return "validating";
  if (text.includes("execute") || text.includes("预约") || text.includes("购票") || text.includes("打车") || text.includes("日历")) return "executing";
  return "searching";
}

function eventLabel(phase: TimelineEvent["phase"]) {
  const labels: Record<TimelineEvent["phase"], string> = {
    request: "创建请求",
    understanding: "理解需求",
    searching: "筛选活动",
    routing: "规划路线",
    validating: "校验方案",
    executing: "执行动作",
    done: "生成完成",
    error: "处理失败"
  };
  return labels[phase];
}

export function usePlanStream() {
  const [isRunning, setIsRunning] = useState(false);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [intent, setIntent] = useState<UserIntent | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [trace, setTrace] = useState<string[]>([]);
  const [assistantText, setAssistantText] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  const append = useCallback((
    label: string,
    detail: string,
    level: TimelineEvent["level"] = "info",
    phase: TimelineEvent["phase"] = "request"
  ) => {
    setEvents((current) => {
      const last = current.at(-1);
      if (last?.label === label && last.detail === detail && last.phase === phase) {
        return current;
      }
      return [
        ...current,
        {
          id: crypto.randomUUID(),
          label,
          detail,
          level,
          phase
        }
      ];
    });
  }, []);

  const handleStreamEvent = useCallback((message: StreamEvent) => {
    if (message.event === "progress" || message.event === "status") {
      const phase = eventPhase(message.data.message);
      append(eventLabel(phase), message.data.message, "info", phase);
      return;
    }

    if (message.event === "intent") {
      setIntent(message.data.intent);
      setTrace((current) => [...current, ...message.data.trace]);
      append("理解需求", "已识别场景、人群、时间、预算和偏好约束。", "success", "understanding");
      return;
    }

    if (message.event === "capability") {
      append("能力说明", message.data.message, message.data.llm === "rule" ? "warning" : "success", "understanding");
      return;
    }

    if (message.event === "plan") {
      setPlan(message.data.plan);
      setTrace(message.data.trace);
      append("生成方案", "已生成活动、餐饮、路线和时间线，正在做最终校验。", "success", "routing");
      return;
    }

    if (message.event === "validation") {
      setTrace((current) => [...current, ...message.data.trace]);
      append(
        "校验方案",
        message.data.ok ? "时间、预算、路线和可执行性校验通过。" : `发现 ${message.data.errors.length} 个待确认问题。`,
        message.data.ok ? "success" : "warning",
        "validating"
      );
      return;
    }

    if (message.event === "execution") {
      setPlan((current) =>
        current
          ? {
              ...current,
              actions: message.data.actions,
              risk_flags: message.data.risk_flags
            }
          : current
      );
      append("执行动作", "预约、购票、打车或日历动作已返回模拟结果。", "success", "executing");
      return;
    }

    if (message.event === "response_chunk") {
      setAssistantText((current) => `${current}${message.data.delta}`);
      return;
    }

    if (message.event === "done") {
      setPlan(message.data.plan);
      setTrace(message.data.trace);
      if (message.data.plan?.share_message) {
        setAssistantText((current) => current || message.data.plan?.share_message || "");
      }
      append(
        "生成完成",
        message.data.plan ? "方案已经生成，可以查看总览、地图、详情或导出分享。" : "已生成文字回复，本轮不需要展示行程方案。",
        "success",
        "done"
      );
      setIsRunning(false);
      return;
    }

    if (message.event === "error") {
      append("处理失败", message.data.message, "error", "error");
      setIsRunning(false);
    }
  }, [append]);

  const run = useCallback(async (request: StreamRequest) => {
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    setIsRunning(true);
    setEvents([]);
    setIntent(null);
    setPlan(null);
    setTrace([]);
    setAssistantText("");
    append("创建请求", "PlanGo 已收到需求，正在启动规划流程。", "info", "request");
    append("理解需求", "正在理解你的调整意图和当前方案上下文。", "info", "understanding");

    try {
      await streamPlan(
        { ...request, session_id: request.session_id ?? getOrCreateSessionId() },
        handleStreamEvent,
        abortRef.current.signal
      );
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        append("网络错误", (error as Error).message, "error", "error");
      }
      setIsRunning(false);
    }
  }, [append, handleStreamEvent]);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setIsRunning(false);
    append("已停止", "当前流式请求已取消。", "warning", "error");
  }, [append]);

  return {
    isRunning,
    events,
    intent,
    plan,
    trace,
    assistantText,
    replacePlan: setPlan,
    run,
    cancel
  };
}
