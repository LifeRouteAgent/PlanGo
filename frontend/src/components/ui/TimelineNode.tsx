import { ArrowRightLeft, Clock3, MapPin, RefreshCw, WalletCards } from "lucide-react";
import type { KeyboardEvent } from "react";
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

function isOriginStop(stop: PlanStopView) {
  return stop.raw.type === "buffer" || stop.raw.target_id === "origin";
}

export function TimelineNode({ stop, selected = false, onHover, onOpen, onModify }: TimelineNodeProps) {
  const originLike = isOriginStop(stop);
  const openFromKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (originLike) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onOpen(stop);
    }
  };

  if (originLike) {
    return (
      <article
        className={`timeline-node timeline-node-v2 timeline-node-origin ${selected ? "is-selected" : ""}`}
        onMouseEnter={() => onHover(stop.id)}
        onMouseLeave={() => onHover(null)}
      >
        <div className="timeline-node-pin" aria-hidden="true">
          <span>{stop.label}</span>
        </div>
        <div className="timeline-node-main timeline-origin-main" aria-label={`${stop.label} 起点`}>
          <strong>起点</strong>
        </div>
      </article>
    );
  }

  return (
    <article
      className={`timeline-node timeline-node-v2 ${selected ? "is-selected" : ""}`}
      onMouseEnter={() => onHover(stop.id)}
      onMouseLeave={() => onHover(null)}
    >
      <div className="timeline-node-pin" aria-hidden="true">
        <span>{stop.label}</span>
      </div>
      <div
        className="timeline-node-main"
        role="button"
        tabIndex={0}
        onClick={() => onOpen(stop)}
        onKeyDown={openFromKeyboard}
      >
        <div className="timeline-node-time">
          <Clock3 size={15} />
          <time>{stop.time}</time>
        </div>
        <AppleButton
          type="button"
          variant="secondary"
          size="sm"
          className="timeline-node-replace"
          onClick={(event) => {
            event.stopPropagation();
            onModify(stop);
          }}
        >
          <RefreshCw size={14} />
          替换
        </AppleButton>
        <div className="timeline-node-body">
          {stop.imageUrl ? <img src={stop.imageUrl} alt={stop.title} loading="lazy" /> : null}
          <div className="timeline-node-content">
            <div className="timeline-node-title-row">
              <h3>{stop.title}</h3>
              {stop.cost ? (
                <span className="timeline-node-cost">
                  <WalletCards size={14} />
                  约 ¥{Math.round(stop.cost)}
                </span>
              ) : null}
            </div>
            {stop.tags.length ? (
              <div className="timeline-node-tags">
                {stop.tags.slice(0, 3).map((tag) => (
                  <SoftTag key={tag} tone="blue" tabIndex={-1}>
                    {tag}
                  </SoftTag>
                ))}
              </div>
            ) : null}
            <p>{stop.reason}</p>
            <div className="timeline-node-meta">
              {stop.address ? (
                <span>
                  <MapPin size={14} />
                  {stop.address}
                </span>
              ) : null}
              {stop.traffic ? (
                <span>
                  <ArrowRightLeft size={14} />
                  {stop.traffic}
                </span>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </article>
  );
}
