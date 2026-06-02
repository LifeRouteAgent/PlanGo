import { Sparkles } from "lucide-react";

export function WelcomeHero() {
  return (
    <section className="welcome-hero" aria-label="PlanGo 欢迎区">
      <div className="welcome-copy">
        <h1>
           <span>PlanGo</span>
          <Sparkles size={26} />
        </h1>
        <p>告诉我人数、时间、预算和偏好，我会帮你生成可执行的本地生活方案，并把路线、预算和每一站理由讲清楚。</p>
      </div>
      <div className="hero-map-illustration" aria-hidden="true">
        <div className="hero-map-card">
          <span className="hero-pin hero-pin-large" />
          <span className="hero-pin hero-pin-small" />
          <span className="hero-tree" />
          <svg viewBox="0 0 220 120" role="presentation">
            <path d="M28 72 C62 22, 95 92, 130 46 S184 62, 202 24" />
          </svg>
        </div>
        {/* <div className="hero-time-card">
          <strong>4h</strong>
          <small>3个地点</small>
        </div> */}
      </div>
    </section>
  );
}
