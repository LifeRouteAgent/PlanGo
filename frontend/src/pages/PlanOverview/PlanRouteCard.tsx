import { ArrowRight, CheckCircle2, Clock3, Heart, Route, TriangleAlert, WalletCards } from "lucide-react";
import { AppleButton, GlassCard, SoftTag } from "../../components/ui";
import type { PlanViewModel } from "../../utils/planViewModel";

interface PlanRouteCardProps {
  order: number;
  plan: PlanViewModel;
  selected?: boolean;
  onOpenDetail: (plan: PlanViewModel) => void;
}

function firstCoverImage(plan: PlanViewModel) {
  return plan.stops.find((stop) => Boolean(stop.imageUrl))?.imageUrl ?? null;
}

function cleanTitle(title: string) {
  return title.replace(/^《|》$/g, "");
}

export function PlanRouteCard({ order, plan, selected = false, onOpenDetail }: PlanRouteCardProps) {
  const coverImage = firstCoverImage(plan);
  const orderText = String(order + 1).padStart(2, "0");
  const shortStops = plan.summaryStops.slice(0, 3);
  const tags = [plan.styleTag, plan.badge].filter(Boolean).slice(0, 3);

  return (
    <GlassCard as="article" className="route-choice-card" hoverable selected={selected}>
      <div className="route-card-topline">
        <div className="route-card-badges">
          <span className="route-card-index">{orderText}</span>
          {order === 0 ? (
            <SoftTag tone="mint" tabIndex={-1}>
              主推方案
            </SoftTag>
          ) : null}
        </div>
        <button className="route-card-like" type="button" aria-label="收藏方案">
          <Heart size={18} />
        </button>
      </div>

      <div className="route-card-cover">
        {coverImage ? <img src={coverImage} alt={plan.title} /> : <div className="route-card-cover-fallback" />}
        <div className="route-card-cover-shade" />
        <div className="route-card-cover-content">
          <h2>《{cleanTitle(plan.title)}》</h2>
          <div className="route-card-tags">
            {tags.map((tag) => (
              <span key={tag}>{tag}</span>
            ))}
          </div>
        </div>
      </div>

      <p className="route-card-reason">{plan.reason}</p>

      <dl className="route-card-metrics" aria-label="方案指标">
        <div>
          <Clock3 size={15} />
          <dt>总时长</dt>
          <dd>{plan.durationText}</dd>
          <small>含停留与交通</small>
        </div>
        <div>
          <WalletCards size={15} />
          <dt>预算</dt>
          <dd>{plan.budgetText}</dd>
          <small>按当前方案</small>
        </div>
        <div>
          <Route size={15} />
          <dt>距离</dt>
          <dd>{plan.distanceText}</dd>
          <small>路线总距离</small>
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
