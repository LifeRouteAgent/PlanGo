import { useRef, useState } from "react";
import { streamPlan } from "../api/streamClient";
import type { Plan, StreamEvent, StreamRequest, UserIntent } from "../types/agent";

export interface TimelineEvent {
  id: string;
  label: string;
  detail: string;
  level: "info" | "success" | "warning" | "error";
  phase:
    | "request"
    | "understanding"
    | "searching"
    | "routing"
    | "validating"
    | "executing"
    | "done"
    | "error";
}

const scenarioLabel: Record<string, string> = {
  family: "亲子",
  friends: "朋友",
  couple: "情侣",
  unknown: "待识别"
};

const constraintLabel: Record<string, string> = {
  child_friendly: "适合孩子",
  diet_friendly: "低脂饮食",
  four_to_six_hours: "4-6 小时",
  light_food: "清淡餐食",
  low_queue: "少排队",
  nearby: "距离近",
  group_friendly: "适合多人",
  social: "适合聊天"
};

const validationLabel: Record<string, string> = {
  duration_out_of_range: "时长超出预期",
  timeline_overlap: "时间线存在重叠"
};

function translateList(values: string[], dictionary: Record<string, string>) {
  return values.map((value) => dictionary[value] ?? value).join(" / ");
}

function statusPhase(message: string): TimelineEvent["phase"] {
  if (message.includes("识别") || message.includes("理解")) {
    return "understanding";
  }
  if (message.includes("路线") || message.includes("高德")) {
    return "routing";
  }
  if (message.includes("校验")) {
    return "validating";
  }
  if (message.includes("执行") || message.includes("预订")) {
    return "executing";
  }
  return "searching";
}

export function usePlanStream() {
  const [isRunning, setIsRunning] = useState(false);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [intent, setIntent] = useState<UserIntent | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [trace, setTrace] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  function append(
    label: string,
    detail: string,
    level: TimelineEvent["level"] = "info",
    phase: TimelineEvent["phase"] = "request"
  ) {
    setEvents((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        label,
        detail,
        level,
        phase
      }
    ]);
  }

  function handleStreamEvent(message: StreamEvent) {
    if (message.event === "status") {
      append("系统状态", message.data.message, "info", statusPhase(message.data.message));
      return;
    }

    if (message.event === "intent") {
      setIntent(message.data.intent);
      setTrace((current) => [...current, ...message.data.trace]);
      append(
        "理解您的需求",
        `场景：${scenarioLabel[message.data.intent.scenario]}，人数：${message.data.intent.people.length}，约束：${translateList(message.data.intent.constraints, constraintLabel) || "无"}`,
        "success",
        "understanding"
      );
      return;
    }

    if (message.event === "capability") {
      append(
        "能力边界",
        message.data.message,
        message.data.llm === "mimo" ? "success" : "warning",
        "routing"
      );
      return;
    }

    if (message.event === "plan") {
      setPlan(message.data.plan);
      setTrace(message.data.trace);
      append("生成方案", "已生成活动、餐厅、路线和时间线，正在继续校验。", "success", "routing");
      return;
    }

    if (message.event === "validation") {
      setTrace((current) => [...current, ...message.data.trace]);
      append(
        "校验方案",
        message.data.ok
          ? "时间、偏好和可用性校验通过。"
          : `存在风险：${translateList(message.data.errors, validationLabel)}`,
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
      append("执行结果", "预订动作已返回，订单状态已更新。", "success", "executing");
      return;
    }

    if (message.event === "done") {
      setPlan(message.data.plan);
      setTrace(message.data.trace);
      append("规划过程已完成", "最终方案已生成，可继续导航、保存、分享或预订。", "success", "done");
      setIsRunning(false);
      return;
    }

    if (message.event === "error") {
      append("错误", message.data.message, "error", "error");
      setIsRunning(false);
    }
  }

  async function run(request: StreamRequest) {
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    setIsRunning(true);
    setEvents([]);
    setIntent(null);
    setPlan(null);
    setTrace([]);
    append("请求创建", "已向 Agent 发送流式规划请求。", "info", "request");

    try {
      await streamPlan(request, handleStreamEvent, abortRef.current.signal);
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        append("网络错误", (error as Error).message, "error", "error");
      }
      setIsRunning(false);
    }
  }

  function cancel() {
    abortRef.current?.abort();
    setIsRunning(false);
    append("已中止", "当前流式请求已取消。", "warning", "error");
  }

  return {
    isRunning,
    events,
    intent,
    plan,
    trace,
    replacePlan: setPlan,
    run,
    cancel
  };
}
