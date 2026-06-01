import { MapPinned, Maximize2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { loadAmap } from "../lib/amap";
import type { Plan, RouteSegment } from "../types/agent";

interface AmapRouteCardProps {
  plan: Plan;
  large?: boolean;
  activeStopId?: string;
  onStopSelect?: (stopId: string) => void;
  onOpenFullMap?: () => void;
}

type AMapAny = any;

function getSegments(plan: Plan): RouteSegment[] {
  if (plan.route?.segments?.length) {
    return plan.route.segments;
  }
  return [
    {
      type: "travel",
      title: "完整路线",
      color: "#5BA8FF",
      polyline: plan.route?.polyline ?? []
    }
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

export function AmapRouteCard({ plan, large = false, activeStopId, onStopSelect, onOpenFullMap }: AmapRouteCardProps) {
  const mapRef = useRef<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<AMapAny>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const segments = useMemo(() => getSegments(plan), [plan]);

  useEffect(() => {
    if (!mapRef.current) return;

    let disposed = false;

    async function drawMap() {
      try {
        const AMap = (await loadAmap()) as AMapAny;
        if (disposed || !mapRef.current) return;

        setConfigured(true);
        mapInstanceRef.current?.destroy?.();

        const firstPoint =
          segments.flatMap((segment) => segment.polyline)[0] ??
          plan.route?.stops.find((stop) => stop.location)?.location;

        const map = new AMap.Map(mapRef.current, {
          zoom: 13,
          center: firstPoint ? [firstPoint.lng, firstPoint.lat] : [116.48, 39.996],
          viewMode: "2D",
          mapStyle: "amap://styles/light",
          features: ["bg", "road", "building", "point"],
          resizeEnable: true
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
                lineCap: "round"
              })
            );
          }
        });

        const infoWindow = new AMap.InfoWindow({
          offset: new AMap.Pixel(0, -38),
          closeWhenClickMap: true
        });

        plan.route?.stops.forEach((stop, index) => {
          if (!stop.location) return;
          const sourceStep = plan.steps[index];
          const stopId = sourceStep?.target_id || `${index}`;
          const label = String.fromCharCode(65 + index);
          const safeTitle = escapeHtml(stop.title);
          const safeAddress = escapeHtml(stop.location.address ?? "");
          const safeTime = escapeHtml(markerTimeText(stop.start_time, stop.end_time));
          const activeClass = activeStopId === stopId ? " is-active" : "";
          const marker = new AMap.Marker({
            position: [stop.location.lng, stop.location.lat],
            title: stop.title,
            zIndex: 100 + stop.order,
            content: `
              <div class="amap-stop-marker${activeClass}">
                <div class="amap-stop-index">${label}</div>
                <div class="amap-stop-bubble">
                  <strong>${safeTitle}</strong>
                  <span>${safeTime}</span>
                </div>
              </div>
            `,
            offset: new AMap.Pixel(-16, -42)
          });
          marker.on("click", () => {
            onStopSelect?.(stopId);
            infoWindow.setContent(`
              <div class="amap-info-window">
                <strong>${safeTitle}</strong>
                <span>${safeTime}</span>
                <small>${safeAddress}</small>
              </div>
            `);
            infoWindow.open(map, [stop.location!.lng, stop.location!.lat]);
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
  }, [activeStopId, large, onStopSelect, plan, segments]);

  return (
    <article className={`amap-route-card ${large ? "is-large" : ""}`}>
      <div className="map-card-head">
        <div>
          <span>地图路线</span>
          <h2>真实地图与节点时间</h2>
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
    </article>
  );
}
