import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Gauge,
  ListChecks,
  Route,
  Sparkles
} from "lucide-react";
import { useEffect, useState } from "react";
import type { TimelineEvent } from "../hooks/usePlanStream";
import type { Plan } from "../types/agent";

interface ObservabilityPageProps {
  plan: Plan | null;
  events: TimelineEvent[];
}

interface RawTraceEvent {
  event_type: string;
  node_name?: string;
  tool?: string;
  provider?: string;
  model?: string;
  success?: boolean;
  source?: string;
  latency_ms?: number;
  duration_ms?: number;
  error?: string | null;
  content_preview?: string;
  raw_preview?: string;
  understanding?: Record<string, unknown>;
  parsed?: Record<string, unknown>;
  issues?: unknown[];
  plan_count?: number;
  output_summary?: Record<string, unknown>;
}

interface TracePayload {
  summary?: {
    event_count?: number;
    node_count?: number;
    tool_count?: number;
    duration_ms?: number;
  };
  events?: RawTraceEvent[];
}

function countByLevel(events: TimelineEvent[], level: TimelineEvent["level"]) {
  return events.filter((event) => event.level === level).length;
}

function phaseLabel(phase: TimelineEvent["phase"]) {
  const labels: Record<TimelineEvent["phase"], string> = {
    request: "请求",
    understanding: "理解",
    searching: "召回",
    routing: "路线",
    validating: "校验",
    executing: "执行",
    done: "完成",
    error: "异常"
  };
  return labels[phase];
}

function llmEventTitle(event: RawTraceEvent) {
  if (event.event_type === "llm_understanding") return "意图与约束理解";
  if (event.event_type === "llm_semantic_extractor") return "Memory / Revision 语义抽取";
  if (event.event_type === "llm_critic") return "LLM Critic 方案审查";
  if (event.event_type === "response_plan_enrichment") return "方案展示增强";
  if (event.event_type === "response_llm_preview") return "最终回复生成";
  return `${event.provider ?? "LLM"} / ${event.model ?? "unknown"}`;
}

function llmEventText(event: RawTraceEvent) {
  if (event.event_type === "llm_understanding") {
    return event.success
      ? JSON.stringify(event.understanding ?? {}, null, 0)
      : "结构化识别未拿到有效 LLM JSON，系统已使用规则兜底。";
  }
  if (event.event_type === "llm_semantic_extractor") {
    return JSON.stringify(event.parsed ?? { raw_preview: event.raw_preview }, null, 0);
  }
  if (event.event_type === "llm_critic") {
    return JSON.stringify(event.issues ?? { raw_preview: event.raw_preview }, null, 0);
  }
  if (event.event_type === "response_llm_preview") {
    return event.content_preview || "Response LLM 无返回内容，已使用模板兜底。";
  }
  if (event.event_type === "response_plan_enrichment") {
    return event.raw_preview || `方案展示增强结果：${event.plan_count ?? 0} 个方案`;
  }
  if (event.success === false && event.source === "fallback") {
    return "真实 LLM 调用失败，系统已使用规则/模板兜底；下方 Tool Trace 可查看 HTTP 错误原因。";
  }
  return event.content_preview || event.error || "无返回内容";
}

export function ObservabilityPage({ plan, events }: ObservabilityPageProps) {
  const [tracePayload, setTracePayload] = useState<TracePayload | null>(null);
  const [traceStatus, setTraceStatus] = useState("等待 trace_id");
  const successCount = countByLevel(events, "success");
  const warningCount = countByLevel(events, "warning");
  const errorCount = countByLevel(events, "error");
  const latestEvent = events[events.length - 1];
  const rawEvents = tracePayload?.events ?? [];
  const llmEvents = rawEvents.filter((event) =>
    [
      "llm_result",
      "llm_understanding",
      "llm_semantic_extractor",
      "llm_critic",
      "response_llm_preview",
      "response_plan_enrichment"
    ].includes(event.event_type)
  );
  const toolEvents = rawEvents.filter((event) => event.event_type === "tool_call");
  const nodeEvents = rawEvents.filter((event) => event.event_type === "node_run");

  useEffect(() => {
    if (!plan?.trace_id) {
      setTracePayload(null);
      setTraceStatus("等待 trace_id");
      return;
    }

    let cancelled = false;
    setTraceStatus("正在读取后端 trace");
    fetch(`/trip/trace/${plan.trace_id}`)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`trace 接口返回 ${response.status}`);
        }
        return response.json() as Promise<TracePayload>;
      })
      .then((payload) => {
        if (!cancelled) {
          setTracePayload(payload);
          setTraceStatus("已加载 trace");
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setTracePayload(null);
          setTraceStatus((error as Error).message);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [plan?.trace_id]);

  return (
    <div className="ops-page observability-page">
      <section className="page-heading">
        <p className="eyebrow">Agent Observability</p>
        <h1>观测面板</h1>
        <p>从产品视角查看最近一次规划的理解、召回、路线、校验、LLM 决策链路和执行状态。</p>
      </section>

      <section className="ops-metrics" aria-label="运行观测指标">
        <article className="ops-card">
          <Gauge size={22} />
          <span className="muted">事件数</span>
          <strong>{events.length}</strong>
        </article>
        <article className="ops-card">
          <CheckCircle2 size={22} />
          <span className="muted">成功</span>
          <strong>{successCount}</strong>
        </article>
        <article className="ops-card">
          <AlertTriangle size={22} />
          <span className="muted">风险</span>
          <strong>{warningCount + errorCount}</strong>
        </article>
        <article className="ops-card">
          <Route size={22} />
          <span className="muted">方案站点</span>
          <strong>{plan?.steps.length ?? 0}</strong>
        </article>
        <article className="ops-card">
          <Sparkles size={22} />
          <span className="muted">LLM 事件</span>
          <strong>{llmEvents.length}</strong>
        </article>
        <article className="ops-card">
          <ListChecks size={22} />
          <span className="muted">工具调用</span>
          <strong>{tracePayload?.summary?.tool_count ?? toolEvents.length}</strong>
        </article>
        <article className="ops-card">
          <Clock3 size={22} />
          <span className="muted">节点耗时</span>
          <strong>{tracePayload?.summary?.duration_ms ?? 0}ms</strong>
        </article>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">运行状态</p>
            <h2>{latestEvent ? latestEvent.label : "尚未开始规划"}</h2>
          </div>
          <Sparkles size={20} />
        </div>
        <p className="muted">
          {latestEvent
            ? latestEvent.detail
            : "回到首页输入一次本地生活需求后，这里会展示 Agent 的实时过程。"}
        </p>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">LLM Trace</p>
            <h2>大模型调用与识别结果</h2>
          </div>
          <Sparkles size={20} />
        </div>
        <p className="muted">
          {plan?.trace_id ? `trace_id: ${plan.trace_id}，${traceStatus}` : "当前方案没有 trace_id。"}
        </p>
        <div className="observability-list">
          {llmEvents.length === 0 && (
            <article className="observability-row">
              <Sparkles size={18} />
              <div>
                <strong>暂无 LLM 事件</strong>
                <p>如果这里为空，通常是本轮被规则直接回答，或 LLM 未配置、调用失败。</p>
              </div>
              <span>LLM</span>
            </article>
          )}
          {llmEvents.map((event, index) => (
            <article
              className={`observability-row ${event.success === false ? "is-warning" : "is-success"}`}
              key={`${event.event_type}-${index}`}
            >
              <Sparkles size={18} />
              <div>
                <strong>{llmEventTitle(event)}</strong>
                <p>{llmEventText(event)}</p>
              </div>
              <span>{event.success === false ? "失败/降级" : "成功"}</span>
            </article>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Tool & Node Trace</p>
            <h2>工具调用与节点运行</h2>
          </div>
          <Gauge size={20} />
        </div>
        <div className="observability-list">
          {[...toolEvents, ...nodeEvents].slice(0, 80).map((event, index) => (
            <article
              className={`observability-row ${event.error ? "is-warning" : "is-success"}`}
              key={`${event.event_type}-${index}`}
            >
              <ListChecks size={18} />
              <div>
                <strong>{event.tool ?? event.node_name ?? event.event_type}</strong>
                <p>
                  {event.error
                    ? event.error
                    : JSON.stringify(event.output_summary ?? { source: event.source, success: event.success }, null, 0)}
                </p>
              </div>
              <span>{event.latency_ms ?? event.duration_ms ?? 0}ms</span>
            </article>
          ))}
          {rawEvents.length === 0 && (
            <article className="observability-row">
              <ListChecks size={18} />
              <div>
                <strong>暂无后端 trace</strong>
                <p>完成一次规划后会自动拉取后端 trace 文件。</p>
              </div>
              <span>Trace</span>
            </article>
          )}
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Trace Timeline</p>
            <h2>最近一次流式过程</h2>
          </div>
          <Clock3 size={20} />
        </div>

        <div className="observability-list">
          {events.length === 0 && (
            <article className="observability-row">
              <ListChecks size={18} />
              <div>
                <strong>等待规划请求</strong>
                <p>暂无 trace。先生成一次方案即可看到节点过程。</p>
              </div>
              <span>待开始</span>
            </article>
          )}
          {events.map((event) => (
            <article className={`observability-row is-${event.level}`} key={event.id}>
              <ListChecks size={18} />
              <div>
                <strong>{event.label}</strong>
                <p>{event.detail}</p>
              </div>
              <span>{phaseLabel(event.phase)}</span>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
