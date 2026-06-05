import { useCallback, useRef, useState } from "react";
import { streamPlan } from "../api/streamClient";
import type { FrontendProgressEvent, Plan, ProgressStatus, StreamEvent, StreamRequest, UserIntent } from "../types/agent";

export interface TimelineEvent {
  id: string;
  label: string;
  detail: string;
  level: "info" | "success" | "warning" | "error";
  status: ProgressStatus;
  step?: string | null;
  timestamp?: string;
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

function levelFromStatus(status: ProgressStatus): TimelineEvent["level"] {
  if (status === "success") return "success";
  if (status === "warning") return "warning";
  if (status === "failed") return "error";
  return "info";
}

function phaseFromProgress(progress: FrontendProgressEvent): TimelineEvent["phase"] {
  if (progress.status === "failed") return "error";
  if (progress.type === "final" || progress.status === "success") return "done";
  return "request";
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
    phase: TimelineEvent["phase"] = "request",
    status: ProgressStatus = level === "success" ? "success" : level === "warning" ? "warning" : level === "error" ? "failed" : "running",
    meta: Pick<TimelineEvent, "step" | "timestamp"> = {}
  ) => {
    setEvents((current) => {
      const last = current.at(-1);
      if (last?.label === label && last.detail === detail && last.status === status && last.step === meta.step) {
        return current;
      }
      return [
        ...current,
        {
          id: crypto.randomUUID(),
          label,
          detail,
          level,
          status,
          step: meta.step,
          timestamp: meta.timestamp,
          phase
        }
      ];
    });
  }, []);

  const appendProgress = useCallback((progress: FrontendProgressEvent) => {
    const status = progress.status ?? "running";
    append(
      progress.title || "规划进度",
      progress.message || "系统正在处理你的规划请求。",
      levelFromStatus(status),
      phaseFromProgress(progress),
      status,
      { step: progress.step ?? null, timestamp: progress.timestamp }
    );
  }, [append]);

  const handleStreamEvent = useCallback((message: StreamEvent) => {
    if (message.event === "progress") {
      appendProgress(message.data);
      return;
    }

    if (message.event === "status") {
      append("规划进度", message.data.message, "info", "request", "running");
      return;
    }

    if (message.event === "intent") {
      setIntent(message.data.intent);
      setTrace((current) => [...current, ...message.data.trace]);
      append("需求理解完成", "已识别场景、人群、时间、预算和偏好约束。", "success", "understanding", "success");
      return;
    }

    if (message.event === "capability") {
      append("能力说明", message.data.message, message.data.llm === "rule" ? "warning" : "success", "understanding", message.data.llm === "rule" ? "warning" : "success");
      return;
    }

    if (message.event === "plan") {
      setPlan(message.data.plan);
      setTrace(message.data.trace);
      append("方案已生成", "已生成活动、餐饮、路线和时间线，正在做最终校验。", "success", "routing", "success");
      return;
    }

    if (message.event === "validation") {
      setTrace((current) => [...current, ...message.data.trace]);
      append(
        "方案校验",
        message.data.ok ? "时间、预算、路线和可执行性校验通过。" : `发现 ${message.data.errors.length} 个待确认问题。`,
        message.data.ok ? "success" : "warning",
        "validating",
        message.data.ok ? "success" : "warning"
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
      append("执行动作完成", "预约、购票、打车或日历动作已返回模拟结果。", "success", "executing", "success");
      return;
    }

    if (message.event === "response_chunk") {
      setAssistantText((current) => `${current}${message.data.delta}`);
      return;
    }

    if (message.event === "done") {
      setPlan(message.data.plan);
      setTrace(message.data.trace);
      if (message.data.response_text) {
        setAssistantText((current) => current || message.data.response_text || "");
      }
      if (message.data.plan?.share_message) {
        setAssistantText((current) => current || message.data.plan?.share_message || "");
      }
      append(
        "生成完成",
        message.data.plan ? "方案已经生成，可以查看总览、地图、详情或导出分享。" : "已生成文字回复，本轮不需要展示行程方案。",
        "success",
        "done",
        "success"
      );
      setIsRunning(false);
      return;
    }

    if (message.event === "error") {
      append("处理失败", message.data.message, "error", "error", "failed");
      setIsRunning(false);
    }
  }, [append, appendProgress]);

  const run = useCallback(async (request: StreamRequest) => {
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    setIsRunning(true);
    setEvents([]);
    setIntent(null);
    setPlan(null);
    setTrace([]);
    setAssistantText("");

    try {
      await streamPlan(
        { ...request, session_id: request.session_id ?? getOrCreateSessionId() },
        handleStreamEvent,
        abortRef.current.signal
      );
      setIsRunning(false);
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        append("网络错误", (error as Error).message, "error", "error", "failed");
      }
      setIsRunning(false);
    }
  }, [append, handleStreamEvent]);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setIsRunning(false);
    append("已停止", "当前流式请求已取消。", "warning", "error", "warning");
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
