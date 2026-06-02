import { Bus, CarFront, Clock3, Footprints, MapPinned, Navigation } from "lucide-react";
import { TimelineNode } from "../../components/ui";
import type { RouteSegment } from "../../types/agent";
import type { PlanStopView } from "../../utils/planViewModel";

interface TimelineViewProps {
  stops: PlanStopView[];
  routeSegments?: RouteSegment[];
  selectedStopId: string | null;
  onHoverStop: (stopId: string | null) => void;
  onOpenPlace: (stop: PlanStopView) => void;
  onModify: (stop?: PlanStopView) => void;
}

interface TransferView {
  id: string;
  modeLabel: string;
  timeRange: string;
  durationText: string;
  distanceText: string;
  routeTitle: string;
}

function isUsefulTime(value?: string | null): value is string {
  return Boolean(value && value !== "--:--" && value !== "待定");
}

function getTimeRange(from: PlanStopView, to: PlanStopView): string {
  const start = from.raw.end_time;
  const end = to.raw.start_time;
  if (isUsefulTime(start) && isUsefulTime(end)) {
    return `${start} - ${end}`;
  }
  return "";
}

function normalizeTransportMode(mode?: string): string {
  const value = String(mode || "").toLowerCase();
  if (value.includes("walk") || value.includes("步行")) {
    return "步行";
  }
  if (value.includes("bus") || value.includes("transit") || value.includes("metro") || value.includes("地铁") || value.includes("公交")) {
    return "公共交通";
  }
  if (value.includes("taxi") || value.includes("打车")) {
    return "打车";
  }
  if (value.includes("drive") || value.includes("car") || value.includes("驾车") || value.includes("自驾")) {
    return "驾车";
  }
  return mode || "交通";
}

function getTransportIcon(modeLabel: string) {
  if (modeLabel === "步行") return Footprints;
  if (modeLabel === "公共交通") return Bus;
  if (modeLabel === "驾车" || modeLabel === "打车") return CarFront;
  return Navigation;
}

function buildTransfer(from: PlanStopView, to: PlanStopView, segment?: RouteSegment): TransferView | null {
  const timeRange = getTimeRange(from, to);
  const modeLabel = normalizeTransportMode(segment?.transport_mode);
  const durationText = typeof segment?.duration_min === "number" && segment.duration_min > 0 ? `约 ${Math.round(segment.duration_min)} 分钟` : "";
  const distanceText = typeof segment?.distance_km === "number" && segment.distance_km > 0 ? `${segment.distance_km.toFixed(1)} 公里` : "";
  const routeTitle = segment?.title && segment.title !== "交通" ? segment.title : `${from.label} 到 ${to.label}`;

  if (!timeRange && !durationText && !distanceText && modeLabel === "交通") {
    return null;
  }

  return {
    id: `${from.id}-${to.id}-transfer`,
    modeLabel,
    timeRange,
    durationText,
    distanceText,
    routeTitle,
  };
}

function TimelineTransfer({ transfer }: { transfer: TransferView }) {
  const Icon = getTransportIcon(transfer.modeLabel);

  return (
    <div className="timeline-transfer-row" aria-label={`${transfer.modeLabel}交通段`}>
      <div className="timeline-transfer-pin" aria-hidden="true">
        <span>
          <Icon size={18} />
        </span>
      </div>
      <div className="timeline-transfer-card">
        <div className="timeline-transfer-main">
          <strong>{transfer.modeLabel}</strong>
          <small>{transfer.routeTitle}</small>
        </div>
        <div className="timeline-transfer-meta">
          {transfer.timeRange ? (
            <span>
              <Clock3 size={14} />
              {transfer.timeRange}
            </span>
          ) : null}
          {transfer.durationText ? <span>{transfer.durationText}</span> : null}
          {transfer.distanceText ? (
            <span>
              <MapPinned size={14} />
              {transfer.distanceText}
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function TimelineView({ stops, routeSegments = [], selectedStopId, onHoverStop, onOpenPlace, onModify }: TimelineViewProps) {
  return (
    <section className="timeline-view" aria-label="行程时间轴">
      {stops.map((stop, index) => (
        <div className="timeline-entry" key={stop.id} style={{ animationDelay: `${index * 0.04}s` }}>
          <TimelineNode
            stop={stop}
            selected={selectedStopId === stop.id}
            onHover={onHoverStop}
            onOpen={onOpenPlace}
            onModify={onModify}
          />
          {index < stops.length - 1 ? (
            (() => {
              const transfer = buildTransfer(stop, stops[index + 1], routeSegments[index]);
              return transfer ? <TimelineTransfer transfer={transfer} /> : null;
            })()
          ) : null}
        </div>
      ))}
    </section>
  );
}
