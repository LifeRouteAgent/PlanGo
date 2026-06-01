import { Check, Loader2 } from "lucide-react";
import type { TimelineEvent } from "../../hooks/usePlanStream";

const steps: Array<{ key: TimelineEvent["phase"]; label: string }> = [
  { key: "understanding", label: "理解需求" },
  { key: "searching", label: "筛选附近活动" },
  { key: "searching", label: "匹配餐厅" },
  { key: "routing", label: "规划路线" },
  { key: "done", label: "生成方案" }
];

function stepIndex(phase: TimelineEvent["phase"]) {
  if (phase === "understanding") return 0;
  if (phase === "searching") return 2;
  if (phase === "routing" || phase === "validating") return 3;
  if (phase === "done") return 4;
  return 0;
}

interface LoadingStepsProps {
  events: TimelineEvent[];
}

export function LoadingSteps({ events }: LoadingStepsProps) {
  const currentPhase = events.at(-1)?.phase ?? "understanding";
  const activeIndex = stepIndex(currentPhase);

  return (
    <section className="loading-steps" aria-live="polite">
      <div className="loading-steps-title">
        <Loader2 size={18} className="spin" />
        <span>PlanGo 正在生成你的本地生活方案</span>
      </div>
      <div className="loading-steps-track">
        {steps.map((step, index) => {
          const done = activeIndex > index || currentPhase === "done";
          const active = !done && activeIndex === index;
          return (
            <div className={`loading-step ${done ? "is-done" : ""} ${active ? "is-active" : ""}`} key={`${step.label}-${index}`}>
              <span className="loading-step-dot">{done ? <Check size={14} /> : index + 1}</span>
              <strong>{step.label}</strong>
            </div>
          );
        })}
      </div>
    </section>
  );
}
