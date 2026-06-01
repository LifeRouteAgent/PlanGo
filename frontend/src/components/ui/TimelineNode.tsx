import { ArrowRightLeft, Clock3, Eye, MapPin, RefreshCw, WalletCards } from "lucide-react";
import type { PlanStopView } from "../../utils/planViewModel";
import { AppleButton } from "./AppleButton";
import { SoftTag } from "./SoftTag";

interface TimelineNodeProps {
  stop: PlanStopView;
  selected?: boolean;
  onHover: (stopId: string | null) => void;
  onOpen: (stop: PlanStopView) => void;
  onModify: (stop: PlanStopView) => void;
}

export function TimelineNode({ stop, selected = false, onHover, onOpen, onModify }: TimelineNodeProps) {
  return (
    <article
      className={`timeline-node ${selected ? "is-selected" : ""}`}
      onMouseEnter={() => onHover(stop.id)}
      onMouseLeave={() => onHover(null)}
    >
      <div className="timeline-node-pin" aria-hidden="true">
        <span>{stop.label}</span>
      </div>
      <button type="button" className="timeline-node-main" onClick={() => onOpen(stop)}>
        <div className="timeline-node-head">
          <time>
            <Clock3 size={15} />
            {stop.time}
          </time>
          <h3>{stop.title}</h3>
        </div>
        <p>{stop.reason}</p>
        <div className="timeline-node-tags">
          {stop.tags.slice(0, 3).map((tag) => (
            <SoftTag key={tag} tone="blue" tabIndex={-1}>
              {tag}
            </SoftTag>
          ))}
        </div>
        <div className="timeline-node-meta">
          <span>
            <MapPin size={14} />
            {stop.address}
          </span>
          <span>
            <WalletCards size={14} />
            {stop.cost ? `约 ¥${Math.round(stop.cost)}` : "预算待估"}
          </span>
          <span>
            <ArrowRightLeft size={14} />
            {stop.traffic}
          </span>
        </div>
      </button>
      <div className="timeline-node-actions">
        <AppleButton type="button" variant="ghost" size="sm" onClick={() => onOpen(stop)}>
          <Eye size={15} />
          详情
        </AppleButton>
        <AppleButton type="button" variant="secondary" size="sm" onClick={() => onModify(stop)}>
          <RefreshCw size={15} />
          替换
        </AppleButton>
      </div>
    </article>
  );
}
