import { Sparkles } from "lucide-react";

export function WelcomeHero() {
  return (
    <section className="welcome-hero" aria-label="PlanGo 欢迎区">
      <div className="brand-pill">
        <Sparkles size={16} />
        <span>PlanGo</span>
      </div>
      <h1>把周末安排交给 PlanGo</h1>
      <p>告诉我人数、时间、预算和偏好，我会帮你生成可执行的本地生活方案，并把路线、预算和每一站理由讲清楚。</p>
    </section>
  );
}
