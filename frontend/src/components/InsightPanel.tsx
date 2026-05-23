import { Brain, Copy, Users } from "lucide-react";
import type { Plan, UserIntent } from "../types/agent";

interface InsightPanelProps {
  intent: UserIntent | null;
  plan: Plan | null;
  trace: string[];
}

const scenarioText: Record<string, string> = {
  family: "亲子",
  friends: "朋友",
  couple: "情侣",
  unknown: "待识别"
};

export function InsightPanel({ intent, plan, trace }: InsightPanelProps) {
  const toolTrace = trace.filter((line) => line.startsWith("tool."));
  const decisionTrace = trace.filter((line) => !line.startsWith("tool."));

  return (
    <section className="panel insight-panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">决策上下文</p>
          <h2>约束与推理摘要</h2>
        </div>
        <Brain size={19} />
      </div>

      <div className="constraint-grid">
        <div>
          <span>场景</span>
          <strong>{intent ? scenarioText[intent.scenario] : "待识别"}</strong>
        </div>
        <div>
          <span>人数</span>
          <strong>{intent?.people.length ?? 0}</strong>
        </div>
        <div>
          <span>半径</span>
          <strong>{intent ? `${intent.radius_km}km` : "-"}</strong>
        </div>
      </div>

      <div className="tag-cloud">
        {(intent?.constraints ?? ["等待约束识别"]).map((constraint) => (
          <span key={constraint}>{constraint}</span>
        ))}
      </div>

      {plan && (
        <div className="share-box">
          <div className="share-title">
            <Users size={17} />
            <strong>可转发消息</strong>
          </div>
          <p>{plan.share_message}</p>
          <button
            className="inline-button"
            type="button"
            onClick={() => navigator.clipboard.writeText(plan.share_message)}
          >
            <Copy size={15} />
            复制
          </button>
        </div>
      )}

      <div className="trace-raw">
        <strong>工具调用链</strong>
        {toolTrace.length === 0 ? (
          <p className="muted">暂无工具调用。</p>
        ) : (
          toolTrace.map((line) => <code key={line}>{line}</code>)
        )}
      </div>

      <div className="trace-raw">
        <strong>决策轨迹</strong>
        {decisionTrace.length === 0 ? (
          <p className="muted">暂无轨迹。</p>
        ) : (
          decisionTrace.map((line) => <code key={line}>{line}</code>)
        )}
      </div>
    </section>
  );
}
