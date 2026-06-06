import { MapPinned, Maximize2 } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { loadAmap } from "../lib/amap";
import type { Location, Plan, PlanStep, RouteSegment } from "../types/agent";

interface AmapRouteCardProps {
  plan: Plan;
  large?: boolean;
  activeStopId?: string;
  onStopSelect?: (stopId: string) => void;
  onOpenFullMap?: () => void;
  footer?: ReactNode;
}

type AMapAny = any;

interface MarkerStopView {
  id: string;
  order: number;
  label: string;
  title: string;
  startTime: string;
  endTime: string;
  location: Location;
  origin: boolean;
}

function getSegments(plan: Plan): RouteSegment[] {
  if (plan.route?.segments?.length) {
    return plan.route.segments;
  }
  return [
    {
      type: "travel",
      title: "完整路线",
      color: "#5BA8FF",
      polyline: plan.route?.polyline ?? [],
    },
  ];
}

function toLngLat(point: { lat: number; lng: number }) {
  return [point.lng, point.lat];
}

function escapeHtml(value: string) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function markerTimeText(start?: string, end?: string) {
  if (start && end && start !== "--:--" && end !== "--:--") {
    return `${start}-${end}`;
  }
  if (start && start !== "--:--") {
    return start;
  }
  return "时间待定";
}

function isOriginStep(step?: PlanStep) {
  return step?.type === "buffer" || step?.target_id === "origin";
}

function originFallbackLocation(plan: Plan): Location | null {
  const firstRoutePoint = plan.route?.segments?.flatMap((segment) => segment.polyline)[0] ?? plan.route?.polyline?.[0];
  if (!firstRoutePoint) return null;
  return {
    name: "起点",
    lat: firstRoutePoint.lat,
    lng: firstRoutePoint.lng,
    address: "起点",
  };
}

function stepMarkerLocation(plan: Plan, step: PlanStep, index: number): Location | null {
  if (step.location) return step.location;
  if (index === 0 && isOriginStep(step)) return originFallbackLocation(plan);
  return null;
}

function markerStops(plan: Plan): MarkerStopView[] {
  const stopsFromSteps = plan.steps
    .map((step, index) => {
      const location = stepMarkerLocation(plan, step, index);
      if (!location) return null;
      const origin = isOriginStep(step);
      const label = String.fromCharCode(65 + index);
      return {
        id: step.target_id || `${index}`,
        order: index + 1,
        label,
        title: origin ? `起点 ${label}` : step.title,
        startTime: step.start_time,
        endTime: step.end_time,
        location,
        origin,
      };
    })
    .filter((stop): stop is MarkerStopView => stop !== null);

  if (stopsFromSteps.length) {
    return stopsFromSteps;
  }

  return (plan.route?.stops ?? [])
    .map((stop, index) => {
      if (!stop.location) return null;
      const sourceStep = plan.steps[index];
      const origin = isOriginStep(sourceStep);
      const label = String.fromCharCode(65 + index);
      return {
        id: sourceStep?.target_id || `${index}`,
        order: stop.order || index + 1,
        label,
        title: origin ? `起点 ${label}` : stop.title,
        startTime: stop.start_time,
        endTime: stop.end_time,
        location: stop.location,
        origin,
      };
    })
    .filter((stop): stop is MarkerStopView => stop !== null);
}

export function AmapRouteCard({ plan, large = false, activeStopId, onStopSelect, onOpenFullMap, footer }: AmapRouteCardProps) {
  const mapRef = useRef<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<AMapAny>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const segments = useMemo(() => getSegments(plan), [plan]);
  const stops = useMemo(() => markerStops(plan), [plan]);

  useEffect(() => {
    if (!mapRef.current) return;

    let disposed = false;

    async function drawMap() {
      try {
        const AMap = (await loadAmap()) as AMapAny;
        if (disposed || !mapRef.current) return;

        setConfigured(true);
        mapInstanceRef.current?.destroy?.();

        const firstPoint = segments.flatMap((segment) => segment.polyline)[0] ?? stops[0]?.location;

        const map = new AMap.Map(mapRef.current, {
          zoom: 13,
          center: firstPoint ? [firstPoint.lng, firstPoint.lat] : [116.48, 39.996],
          viewMode: "2D",
          mapStyle: "amap://styles/light",
          features: ["bg", "road", "building", "point"],
          resizeEnable: true,
        });
        mapInstanceRef.current = map;

        const bounds: AMapAny[] = [];

        segments.forEach((segment, index) => {
          const path = segment.polyline.map(toLngLat);
          path.forEach((point) => bounds.push(point));
          if (path.length > 1) {
            map.add(
              new AMap.Polyline({
                path,
                strokeColor: segment.color || (index % 2 ? "#7EDFC0" : "#5BA8FF"),
                strokeWeight: large ? 8 : 6,
                strokeOpacity: 0.88,
                lineJoin: "round",
                lineCap: "round",
              })
            );
          }
        });

        const infoWindow = new AMap.InfoWindow({
          offset: new AMap.Pixel(0, -38),
          closeWhenClickMap: true,
        });

        stops.forEach((stop) => {
          const safeTitle = escapeHtml(stop.title);
          const safeAddress = escapeHtml(stop.location.address ?? "");
          const safeTime = escapeHtml(markerTimeText(stop.startTime, stop.endTime));
          const activeClass = activeStopId === stop.id ? " is-active" : "";
          const originClass = stop.origin ? " is-origin" : "";
          const marker = new AMap.Marker({
            position: [stop.location.lng, stop.location.lat],
            title: stop.title,
            zIndex: 100 + stop.order,
            content: `
              <div class="amap-stop-marker${activeClass}${originClass}">
                <div class="amap-stop-index">${stop.label}</div>
                <div class="amap-stop-bubble">
                  <strong>${safeTitle}</strong>
                  <span>${stop.origin ? "起点" : safeTime}</span>
                </div>
              </div>
            `,
            offset: new AMap.Pixel(-16, -42),
          });
          marker.on("click", () => {
            onStopSelect?.(stop.id);
            infoWindow.setContent(`
              <div class="amap-info-window">
                <strong>${safeTitle}</strong>
                <span>${stop.origin ? "起点" : safeTime}</span>
                <small>${safeAddress}</small>
              </div>
            `);
            infoWindow.open(map, [stop.location.lng, stop.location.lat]);
          });
          map.add(marker);
          bounds.push([stop.location.lng, stop.location.lat]);
        });

        if (bounds.length > 1) {
          map.setFitView();
        }
        setStatus(null);
      } catch (error) {
        const message = (error as Error).message;
        setConfigured(!message.includes("未配置"));
        setStatus(message);
      }
    }

    void drawMap();

    return () => {
      disposed = true;
      mapInstanceRef.current?.destroy?.();
      mapInstanceRef.current = null;
    };
  }, [activeStopId, large, onStopSelect, segments, stops]);

  return (
    <article className={`amap-route-card ${large ? "is-large" : ""}`}>
      <div className="map-card-head">
        <div>
          <span>地图路线</span>
        </div>
        {onOpenFullMap && (
          <button type="button" className="apple-button apple-button-ghost apple-button-sm" onClick={onOpenFullMap}>
            <Maximize2 size={15} />
            放大
          </button>
        )}
      </div>
      <div className="amap-container" ref={mapRef}>
        {configured === false && (
          <div className="map-config-state">
            <MapPinned size={30} />
            <strong>高德地图未配置</strong>
            <p>请在 frontend/public/app-config.json 中配置公开的 AMap JS Key。</p>
          </div>
        )}
        {configured !== false && status && (
          <div className="map-config-state">
            <MapPinned size={30} />
            <strong>地图加载失败</strong>
            <p>{status}</p>
          </div>
        )}
      </div>
      {footer}
    </article>
  );
}
