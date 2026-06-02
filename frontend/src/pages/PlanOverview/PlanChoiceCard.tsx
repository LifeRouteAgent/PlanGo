import { ArrowRight, CheckCircle2, Clock3, Heart, Route, TriangleAlert, WalletCards } from "lucide-react";
import { AppleButton, GlassCard } from "../../components/ui";
import type { PlanViewModel } from "../../utils/planViewModel";

interface PlanChoiceCardProps {
  order: number;
  plan: PlanViewModel;
  onOpenDetail: (plan: PlanViewModel) => void;
}

function firstCoverImage(plan: PlanViewModel) {
  return plan.stops.find((stop) => Boolean(stop.imageUrl))?.imageUrl ?? plan.raw.recommendation?.cover_image ?? null;
}

function displayTitle(title: string) {
  const clean = title.replace(/^《|》$/g, "").trim();
  return `《${clean || "本地生活路线"}》`;
}

export function PlanChoiceCard({ order, plan, onOpenDetail }: PlanChoiceCardProps) {
  const coverImage = firstCoverImage(plan);
  const orderText = String(order + 1).padStart(2, "0");
  const shortStops = plan.summaryStops.slice(0, 4);
  const tags = [plan.styleTag, ...plan.stops.flatMap((stop) => stop.tags)].filter(Boolean).slice(0, 3);

  return (
    <GlassCard as="article" className="route-choice-card route-choice-card-v2" hoverable>
      <div className="route-card-topline">
        <div className="route-card-badges">
          <span className="route-card-index">{orderText}</span>
        </div>
        <button className="route-card-like" type="button" aria-label="收藏方案">
          <Heart size={18} />
        </button>
      </div>

      <div className="route-card-cover">
        {coverImage ? <img src={coverImage} alt={plan.title} loading="lazy" /> : <div className="route-card-cover-fallback" />}
        <div className="route-card-cover-shade" />
        <div className="route-card-cover-content">
          <h2>{displayTitle(plan.title)}</h2>
          <div className="route-card-tags">
            {tags.map((tag) => (
              <span key={tag}>{tag}</span>
            ))}
          </div>
        </div>
      </div>

      <dl className="route-card-metrics" aria-label="方案指标">
        <div>
          <Clock3 size={15} />
          <dt>总时长</dt>
          <dd>{plan.durationText}</dd>
        </div>
        <div>
          <WalletCards size={15} />
          <dt>预算</dt>
          <dd>{plan.budgetText}</dd>
        </div>
        <div>
          <Route size={15} />
          <dt>距离</dt>
          <dd>{plan.distanceText}</dd>
        </div>
      </dl>

      <div className="route-card-timeline" aria-label="简短时间轴">
        {shortStops.map((stop) => (
          <div className="route-card-stop" key={stop.id}>
            <span>{stop.label}</span>
            <div>
              <strong>{stop.time}</strong>
              <p>{stop.title}</p>
            </div>
            <em>{stop.tags[0] || "地点"}</em>
          </div>
        ))}
      </div>

      <div className="route-card-pros-notes">
        <div>
          <strong>
            <CheckCircle2 size={15} />
            优点
          </strong>
          <ul>
            {plan.pros.slice(0, 3).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
        <div>
          <strong>
            <TriangleAlert size={15} />
            注意
          </strong>
          <ul>
            {plan.cons.slice(0, 3).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      </div>

      <AppleButton className="route-card-cta" type="button" variant="secondary" full onClick={() => onOpenDetail(plan)}>
        查看完整行程
        <ArrowRight size={17} className="button-arrow" />
      </AppleButton>
    </GlassCard>
  );
}
