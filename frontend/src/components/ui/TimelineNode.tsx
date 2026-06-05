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

export function TimelineNode({ stop, selected = false, onHover, onOpen, onModify }: TimelineNodeProps) {
  const isOrigin = stop.raw.type === "buffer" && stop.title === "起点";
  const originLike = isOrigin || stop.raw.type === "buffer" || stop.raw.target_id === "origin";
  const openFromKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (originLike) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onOpen(stop);
    }
  };

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
        onClick={() => {
          if (!originLike) onOpen(stop);
        }}
        onKeyDown={openFromKeyboard}
      >
        <div className="timeline-node-time">
          <Clock3 size={15} />
          <time>{stop.time}</time>
        </div>
        {!originLike ? (
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
        ) : null}
        <div className="timeline-node-body">
          {stop.imageUrl ? <img src={stop.imageUrl} alt={stop.title} loading="lazy" /> : null}
          <div className="timeline-node-content">
            <div className="timeline-node-title-row">
              <h3>{originLike ? "起点" : stop.title}</h3>
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
        {/* <div className="timeline-node-actions">
          <AppleButton type="button" variant="ghost" size="sm" onClick={() => onOpen(stop)}>
            <Eye size={15} />
            详情
          </AppleButton>
          <AppleButton type="button" variant="secondary" size="sm" onClick={() => onModify(stop)}>
            <RefreshCw size={15} />
            替换
          </AppleButton>
        </div> */}
    </article>
  );
}
